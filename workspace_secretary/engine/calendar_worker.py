import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from workspace_secretary.engine.database import create_database, DatabaseInterface
from workspace_secretary.engine.calendar_sync import CalendarClient
from workspace_secretary.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("calendar_worker")


class CalendarWorker:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = config_path
        self.config = None
        self.db: DatabaseInterface
        self.calendar_client: CalendarClient
        self.running = False
        self.window_days_past = 30
        self.window_days_future = 90

    def initialize(self):
        logger.info("Calendar worker starting...")

        self.config = load_config(self.config_path)

        self.db = create_database(self.config.database)
        self.db.initialize()
        logger.info(f"Database initialized: {self.config.database.backend}")

        calendar_config = self.config.calendar
        if not calendar_config or not calendar_config.enabled:
            logger.warning(
                "Calendar not enabled in config - worker will exit gracefully"
            )
            logger.info(
                "To enable calendar sync, set calendar.enabled: true in config.yaml"
            )
            sys.exit(0)

        if not self.config.imap.oauth2:
            logger.warning(
                "OAuth2 not configured - calendar worker will exit gracefully"
            )
            logger.info("Calendar sync requires OAuth2. Run auth_setup to configure.")
            sys.exit(0)

        logger.info("OAuth2 configuration found")

        try:
            self.calendar_client = CalendarClient(self.config)
            self.calendar_client.connect()
            logger.info("Calendar client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize calendar client: {e}")
            logger.info("Calendar worker will exit. Check OAuth2 token validity.")
            sys.exit(0)

        self.running = True
        logger.info("Calendar worker ready for sync operations")

    def compute_window(self):
        now = datetime.utcnow()
        window_start = (now - timedelta(days=self.window_days_past)).isoformat() + "Z"
        window_end = (now + timedelta(days=self.window_days_future)).isoformat() + "Z"
        return window_start, window_end

    def sync_calendar_list(self):
        try:
            calendars = self.calendar_client.list_calendars()
            logger.info(f"Discovered {len(calendars)} calendars")
            return [cal["id"] for cal in calendars]
        except Exception as e:
            logger.error(f"Failed to list calendars: {e}")
            return []

    def flush_outbox(self):
        try:
            pending_ops = self.db.list_calendar_outbox(statuses=["pending"])
            if not pending_ops:
                return

            logger.info(f"Processing {len(pending_ops)} pending outbox operations")

            for op in pending_ops:
                op_id = op["id"]
                op_type = op["op_type"]
                calendar_id = op["calendar_id"]
                event_id = op.get("event_id")
                local_temp_id = op.get("local_temp_id")
                payload = op["payload_json"]

                try:
                    if op_type == "create":
                        logger.info(
                            f"Creating event (outbox {op_id}) in calendar {calendar_id}"
                        )
                        created_event = self.calendar_client.create_event(
                            payload, calendar_id
                        )

                        real_event_id = created_event["id"]

                        if local_temp_id:
                            self.db.delete_calendar_event_cache(
                                calendar_id, local_temp_id
                            )

                        self._upsert_event_to_cache(
                            calendar_id, created_event, local_status="synced"
                        )

                        self.db.update_calendar_outbox_status(
                            op_id, "applied", event_id=real_event_id
                        )
                        logger.info(f"Created event {real_event_id} successfully")

                    elif op_type == "patch":
                        if not event_id:
                            logger.error(f"Patch operation {op_id} missing event_id")
                            self.db.update_calendar_outbox_status(
                                op_id, "failed", error="Missing event_id"
                            )
                            continue

                        logger.info(f"Updating event {event_id} (outbox {op_id})")
                        updated_event = self.calendar_client.update_event(
                            calendar_id, event_id, payload
                        )

                        self._upsert_event_to_cache(
                            calendar_id, updated_event, local_status="synced"
                        )

                        self.db.update_calendar_outbox_status(op_id, "applied")
                        logger.info(f"Updated event {event_id} successfully")

                    elif op_type == "delete":
                        if not event_id:
                            logger.error(f"Delete operation {op_id} missing event_id")
                            self.db.update_calendar_outbox_status(
                                op_id, "failed", error="Missing event_id"
                            )
                            continue

                        logger.info(f"Deleting event {event_id} (outbox {op_id})")
                        self.calendar_client.delete_event(calendar_id, event_id)

                        self.db.delete_calendar_event_cache(calendar_id, event_id)

                        self.db.update_calendar_outbox_status(op_id, "applied")
                        logger.info(f"Deleted event {event_id} successfully")

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"Outbox operation {op_id} failed: {error_msg}")

                    if (
                        "etag" in error_msg.lower()
                        or "precondition" in error_msg.lower()
                    ):
                        self.db.update_calendar_outbox_status(
                            op_id, "conflict", error=error_msg
                        )
                        logger.warning(
                            f"Marked outbox {op_id} as conflict (server-wins)"
                        )
                    else:
                        attempt_count = op.get("attempt_count", 0)
                        if attempt_count >= 5:
                            self.db.update_calendar_outbox_status(
                                op_id, "failed", error=error_msg
                            )
                            logger.error(
                                f"Outbox {op_id} failed permanently after 5 attempts"
                            )
                        else:
                            self.db.update_calendar_outbox_status(
                                op_id, "pending", error=error_msg
                            )

        except Exception as e:
            logger.error(f"Error flushing outbox: {e}")

    def sync_calendar_incremental(self, calendar_id: str):
        sync_state = None
        sync_token = None

        try:
            sync_state = self.db.get_calendar_sync_state(calendar_id)
            sync_token = sync_state.get("sync_token") if sync_state else None

            if not sync_token:
                logger.info(f"No sync token for {calendar_id}, performing initial sync")
                self.sync_calendar_full(calendar_id)
                return

            logger.info(f"Incremental sync for {calendar_id}")

            try:
                events = []
                page_token = None

                while True:
                    result = (
                        self.calendar_client.service.events()
                        .list(
                            calendarId=calendar_id,
                            syncToken=sync_token,
                            singleEvents=True,
                            showDeleted=True,
                            pageToken=page_token,
                        )
                        .execute()
                    )

                    events.extend(result.get("items", []))
                    page_token = result.get("nextPageToken")

                    if not page_token:
                        break

                new_sync_token = result.get("nextSyncToken")

                logger.info(
                    f"Incremental sync for {calendar_id}: {len(events)} changes"
                )

                for event in events:
                    if event.get("status") == "cancelled":
                        self.db.delete_calendar_event_cache(calendar_id, event["id"])
                    else:
                        self._upsert_event_to_cache(
                            calendar_id, event, local_status="synced"
                        )

                window_start, window_end = self.compute_window()
                self.db.upsert_calendar_sync_state(
                    calendar_id=calendar_id,
                    window_start=window_start,
                    window_end=window_end,
                    sync_token=new_sync_token,
                    status="ok",
                    last_incremental_sync_at=datetime.utcnow().isoformat(),
                )

                logger.info(
                    f"Incremental sync for {calendar_id} completed successfully"
                )

            except Exception as e:
                if "410" in str(e) or "invalid" in str(e).lower():
                    logger.warning(
                        f"Sync token invalid for {calendar_id}, performing full sync"
                    )
                    self.sync_calendar_full(calendar_id)
                else:
                    raise

        except Exception as e:
            logger.error(f"Incremental sync failed for {calendar_id}: {e}")
            window_start_fallback = (
                (sync_state.get("window_start") or "") if sync_state else ""
            )
            window_end_fallback = (
                (sync_state.get("window_end") or "") if sync_state else ""
            )
            sync_token_fallback = sync_token or ""

            self.db.upsert_calendar_sync_state(
                calendar_id=calendar_id,
                window_start=window_start_fallback,
                window_end=window_end_fallback,
                sync_token=sync_token_fallback,
                status="error",
                last_error=str(e),
            )

    def sync_calendar_full(self, calendar_id: str):
        window_start = ""
        window_end = ""

        try:
            window_start, window_end = self.compute_window()

            logger.info(
                f"Full sync for {calendar_id} (window: {window_start} to {window_end})"
            )

            events = []
            page_token = None

            while True:
                result = (
                    self.calendar_client.service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=window_start,
                        timeMax=window_end,
                        singleEvents=True,
                        showDeleted=True,
                        pageToken=page_token,
                    )
                    .execute()
                )

                events.extend(result.get("items", []))
                page_token = result.get("nextPageToken")

                if not page_token:
                    break

            next_sync_token = result.get("nextSyncToken")

            logger.info(f"Full sync for {calendar_id}: fetched {len(events)} events")

            for event in events:
                if event.get("status") != "cancelled":
                    self._upsert_event_to_cache(
                        calendar_id, event, local_status="synced"
                    )

            self.db.upsert_calendar_sync_state(
                calendar_id=calendar_id,
                window_start=window_start,
                window_end=window_end,
                sync_token=next_sync_token,
                status="ok",
                last_full_sync_at=datetime.utcnow().isoformat(),
                last_incremental_sync_at=datetime.utcnow().isoformat(),
            )

            logger.info(f"Full sync for {calendar_id} completed successfully")

        except Exception as e:
            logger.error(f"Full sync failed for {calendar_id}: {e}")
            self.db.upsert_calendar_sync_state(
                calendar_id=calendar_id,
                window_start=window_start,
                window_end=window_end,
                sync_token="",
                status="error",
                last_error=str(e),
            )

    def _upsert_event_to_cache(
        self, calendar_id: str, event: dict, local_status: str = "synced"
    ):
        from dateutil import parser as dateutil_parser

        event_id = event["id"]
        etag = event.get("etag")
        updated = event.get("updated")
        status = event.get("status")
        summary = event.get("summary")
        location = event.get("location")

        start = event.get("start", {})
        end = event.get("end", {})

        is_all_day = "date" in start

        if is_all_day:
            start_date = start.get("date")
            end_date = end.get("date")
            start_ts_utc = None
            end_ts_utc = None
        else:
            start_ts = start.get("dateTime")
            end_ts = end.get("dateTime")

            start_dt = dateutil_parser.parse(start_ts) if start_ts else None
            end_dt = dateutil_parser.parse(end_ts) if end_ts else None

            start_ts_utc = start_dt.isoformat() if start_dt else None
            end_ts_utc = end_dt.isoformat() if end_dt else None
            start_date = None
            end_date = None

        self.db.upsert_calendar_event_cache(
            calendar_id=calendar_id,
            event_id=event_id,
            raw_json=event,
            etag=etag,
            updated=updated,
            status=status,
            start_ts_utc=start_ts_utc,
            end_ts_utc=end_ts_utc,
            start_date=start_date,
            end_date=end_date,
            is_all_day=is_all_day,
            summary=summary,
            location=location,
            local_status=local_status,
        )

    def run_sync_cycle(self):
        logger.info("=== Starting sync cycle ===")

        self.flush_outbox()

        calendar_ids = self.sync_calendar_list()

        for calendar_id in calendar_ids:
            self.sync_calendar_incremental(calendar_id)

        logger.info("=== Sync cycle completed ===")

    def run(self):
        logger.info("Calendar worker running (sync interval: 60s)")

        last_full_refresh = time.time()
        full_refresh_interval = 86400

        while self.running:
            try:
                self.run_sync_cycle()

                if time.time() - last_full_refresh > full_refresh_interval:
                    logger.info("Daily full refresh triggered")
                    calendar_ids = self.sync_calendar_list()
                    for calendar_id in calendar_ids:
                        self.sync_calendar_full(calendar_id)
                    last_full_refresh = time.time()

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Error in sync cycle: {e}", exc_info=True)

            if self.running:
                time.sleep(60)

        logger.info("Calendar worker stopped")

    def stop(self):
        self.running = False


def main():
    worker = CalendarWorker()
    worker.initialize()

    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Shutting down calendar worker...")
        worker.stop()
    finally:
        if worker.db:
            worker.db.close()
        logger.info("Calendar worker shutdown complete")


if __name__ == "__main__":
    main()
