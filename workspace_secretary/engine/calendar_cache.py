import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

CALENDAR_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id TEXT PRIMARY KEY,
    summary TEXT,
    description TEXT,
    timezone TEXT,
    access_role TEXT,
    sync_token TEXT,
    last_sync TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    location TEXT,
    start_time TEXT,
    end_time TEXT,
    all_day INTEGER DEFAULT 0,
    status TEXT,
    organizer_email TEXT,
    recurrence TEXT,
    recurring_event_id TEXT,
    html_link TEXT,
    hangout_link TEXT,
    created TEXT,
    updated TEXT,
    etag TEXT,
    raw_json TEXT,
    FOREIGN KEY (calendar_id) REFERENCES calendars(id)
);

CREATE TABLE IF NOT EXISTS attendees (
    event_id TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    response_status TEXT,
    is_organizer INTEGER DEFAULT 0,
    is_self INTEGER DEFAULT 0,
    PRIMARY KEY (event_id, email),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_calendar ON events(calendar_id);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
CREATE INDEX IF NOT EXISTS idx_events_end ON events(end_time);
CREATE INDEX IF NOT EXISTS idx_events_recurring ON events(recurring_event_id);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_attendees_email ON attendees(email);
"""


class CalendarCache:
    def __init__(self, db_path: str = "config/calendar_cache.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            conn.executescript(CALENDAR_CACHE_SCHEMA)
            conn.commit()
        logger.info(f"Calendar cache initialized at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def upsert_calendar(
        self,
        calendar_id: str,
        summary: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
        access_role: Optional[str] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO calendars (id, summary, description, timezone, access_role, last_sync)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    description = excluded.description,
                    timezone = excluded.timezone,
                    access_role = excluded.access_role,
                    last_sync = excluded.last_sync
                """,
                (
                    calendar_id,
                    summary,
                    description,
                    timezone,
                    access_role,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def update_sync_token(self, calendar_id: str, sync_token: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE calendars SET sync_token = ?, last_sync = ? WHERE id = ?",
                (sync_token, datetime.utcnow().isoformat(), calendar_id),
            )
            conn.commit()

    def get_sync_token(self, calendar_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT sync_token FROM calendars WHERE id = ?", (calendar_id,)
            ).fetchone()
            return row["sync_token"] if row else None

    def upsert_event(self, event: dict[str, Any], calendar_id: str) -> None:
        import json

        event_id = event.get("id")
        if not event_id:
            return

        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime") or start.get("date")
        end_time = end.get("dateTime") or end.get("date")
        all_day = "date" in start and "dateTime" not in start

        organizer = event.get("organizer", {})
        recurrence = (
            json.dumps(event.get("recurrence")) if event.get("recurrence") else None
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id, calendar_id, summary, description, location,
                    start_time, end_time, all_day, status, organizer_email,
                    recurrence, recurring_event_id, html_link, hangout_link,
                    created, updated, etag, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    description = excluded.description,
                    location = excluded.location,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    all_day = excluded.all_day,
                    status = excluded.status,
                    organizer_email = excluded.organizer_email,
                    recurrence = excluded.recurrence,
                    recurring_event_id = excluded.recurring_event_id,
                    html_link = excluded.html_link,
                    hangout_link = excluded.hangout_link,
                    updated = excluded.updated,
                    etag = excluded.etag,
                    raw_json = excluded.raw_json
                """,
                (
                    event_id,
                    calendar_id,
                    event.get("summary"),
                    event.get("description"),
                    event.get("location"),
                    start_time,
                    end_time,
                    1 if all_day else 0,
                    event.get("status"),
                    organizer.get("email"),
                    recurrence,
                    event.get("recurringEventId"),
                    event.get("htmlLink"),
                    event.get("hangoutLink"),
                    event.get("created"),
                    event.get("updated"),
                    event.get("etag"),
                    json.dumps(event),
                ),
            )

            conn.execute("DELETE FROM attendees WHERE event_id = ?", (event_id,))
            for attendee in event.get("attendees", []):
                conn.execute(
                    """
                    INSERT INTO attendees (event_id, email, display_name, response_status, is_organizer, is_self)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        attendee.get("email"),
                        attendee.get("displayName"),
                        attendee.get("responseStatus"),
                        1 if attendee.get("organizer") else 0,
                        1 if attendee.get("self") else 0,
                    ),
                )
            conn.commit()

    def delete_event(self, event_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM attendees WHERE event_id = ?", (event_id,))
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
            conn.commit()

    def get_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        import json

        query = "SELECT * FROM events WHERE calendar_id = ?"
        params: list[Any] = [calendar_id]

        if time_min:
            query += " AND end_time >= ?"
            params.append(time_min)
        if time_max:
            query += " AND start_time <= ?"
            params.append(time_max)

        query += " ORDER BY start_time ASC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            events = []
            for row in rows:
                event = json.loads(row["raw_json"]) if row["raw_json"] else dict(row)
                events.append(event)
            return events

    def get_event(self, event_id: str) -> Optional[dict[str, Any]]:
        import json

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row and row["raw_json"]:
                return json.loads(row["raw_json"])
            return dict(row) if row else None

    def search_events(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        import json

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events 
                WHERE summary LIKE ? OR description LIKE ? OR location LIKE ?
                ORDER BY start_time DESC LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            return [
                json.loads(row["raw_json"]) if row["raw_json"] else dict(row)
                for row in rows
            ]

    def get_events_for_date_range(
        self, start_date: str, end_date: str, calendar_id: str = "primary"
    ) -> list[dict[str, Any]]:
        return self.get_events(
            calendar_id=calendar_id,
            time_min=start_date,
            time_max=end_date,
            limit=500,
        )

    def clear_calendar(self, calendar_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM attendees WHERE event_id IN (SELECT id FROM events WHERE calendar_id = ?)",
                (calendar_id,),
            )
            conn.execute("DELETE FROM events WHERE calendar_id = ?", (calendar_id,))
            conn.execute(
                "UPDATE calendars SET sync_token = NULL WHERE id = ?", (calendar_id,)
            )
            conn.commit()
