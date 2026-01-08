"""IMAP client implementation."""

import email
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union, Any, cast

import imapclient

from workspace_secretary.config import ImapConfig
from workspace_secretary.models import Email
from workspace_secretary.oauth2 import get_access_token

logger = logging.getLogger(__name__)


class ImapClient:
    """IMAP client for interacting with email servers."""

    def __init__(self, config: ImapConfig, allowed_folders: Optional[List[str]] = None):
        """Initialize IMAP client.

        Args:
            config: IMAP configuration
            allowed_folders: List of allowed folders (None means all folders)
        """
        self.config = config
        self.allowed_folders = set(allowed_folders) if allowed_folders else None
        self.client: Optional[imapclient.IMAPClient] = None
        self.folder_cache: Dict[str, List[str]] = {}
        self.connected = False
        self.count_cache: Dict[
            str, Dict[str, Tuple[int, datetime]]
        ] = {}  # Cache for message counts
        self.current_folder: Optional[str] = None  # Store the currently selected folder
        self.folder_message_counts: Dict[
            str, Dict[str, int]
        ] = {}  # Cache for folder message counts

    def connect(self) -> None:
        """Connect to IMAP server.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            self.client = imapclient.IMAPClient(
                self.config.host,
                port=self.config.port,
                ssl=self.config.use_ssl,
            )

            # Use OAuth2 for Gmail if configured
            if self.config.requires_oauth2:
                logger.info(f"Using OAuth2 authentication for {self.config.host}")

                # Get fresh access token
                if not self.config.oauth2:
                    raise ValueError("OAuth2 configuration is required for Gmail")

                access_token, _ = get_access_token(self.config.oauth2)

                # Authenticate with XOAUTH2
                # Use the oauth_login method which properly formats the XOAUTH2 string
                if self.client:
                    self.client.oauth2_login(self.config.username, access_token)
            else:
                # Standard password authentication
                if not self.config.password:
                    raise ValueError("Password is required for authentication")

                if self.client:
                    self.client.login(self.config.username, self.config.password)

            self.connected = True
            logger.info(f"Connected to IMAP server {self.config.host}")
        except Exception as e:
            self.connected = False
            logger.error(f"Failed to connect to IMAP server: {e}")
            raise ConnectionError(f"Failed to connect to IMAP server: {e}")

    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self.client:
            try:
                self.client.logout()
            except Exception as e:
                logger.warning(f"Error during IMAP logout: {e}")
            finally:
                self.client = None
                self.connected = False
                logger.info("Disconnected from IMAP server")

    def ensure_connected(self) -> None:
        """Ensure that we are connected to the IMAP server.

        Raises:
            ConnectionError: If connection fails
        """
        if not self.connected or not self.client:
            self.connect()

        # Type narrowing for static analysis - use assert to help mypy
        # but also provide a runtime check for safety
        if self.client is None:
            raise ConnectionError("Failed to initialize IMAP client")

    def _get_client(self) -> imapclient.IMAPClient:
        """Get the IMAP client, ensuring it is connected.

        Returns:
            The connected IMAP client.

        Raises:
            ConnectionError: If not connected and connection fails.
        """
        self.ensure_connected()
        if self.client is None:
            raise ConnectionError("IMAP client not initialized")
        return self.client

    def get_capabilities(self) -> List[str]:
        """Get IMAP server capabilities.

        Returns:
            List of server capabilities

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()
        raw_capabilities = client.capabilities()

        # Convert byte strings to regular strings and normalize case
        capabilities = []
        for cap in raw_capabilities:
            if isinstance(cap, bytes):
                cap = cap.decode("utf-8")
            capabilities.append(cap.upper())

        return capabilities

    def list_folders(self, refresh: bool = False) -> List[str]:
        """List available folders.

        Args:
            refresh: Force refresh folder list cache

        Returns:
            List of folder names

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()

        # Check cache first
        if not refresh and self.folder_cache:
            return list(self.folder_cache.keys())

        # Get folders from server
        folders = []
        new_cache = {}
        for flags, delimiter, name in client.list_folders():
            if isinstance(name, bytes):
                # Convert bytes to string if necessary
                name = name.decode("utf-8")

            # Filter folders if allowed_folders is set
            if self.allowed_folders is not None and name not in self.allowed_folders:
                continue

            folders.append(name)
            new_cache[name] = flags

        self.folder_cache = new_cache
        logger.debug(f"Listed {len(folders)} folders")
        return folders

    def folder_exists(self, folder: str) -> bool:
        """Check if a folder exists.

        Args:
            folder: Folder name to check

        Returns:
            True if folder exists, False otherwise
        """
        # Ensure cache is populated
        if not self.folder_cache:
            self.list_folders(refresh=True)

        return folder in self.folder_cache

    def create_folder(self, folder: str) -> bool:
        """Create a new folder.

        Args:
            folder: Folder name to create

        Returns:
            True if successful

        Raises:
            ConnectionError: If connection fails
        """
        client = self._get_client()

        # Check if already exists
        if self.folder_exists(folder):
            logger.info(f"Folder '{folder}' already exists")
            return True

        try:
            client.create_folder(folder)
            logger.info(f"Created folder '{folder}'")
            # Refresh cache
            self.list_folders(refresh=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create folder '{folder}': {e}")
            return False

    def _is_folder_allowed(self, folder: str) -> bool:
        """Check if a folder is allowed.

        Args:
            folder: Folder to check

        Returns:
            True if folder is allowed, False otherwise
        """
        # If no allowed_folders specified, all folders are allowed
        if self.allowed_folders is None:
            return True

        # If allowed_folders is specified, check if folder is in it
        return folder in self.allowed_folders

    def select_folder(self, folder: str, readonly: bool = False) -> Dict[Any, Any]:
        """Select folder on IMAP server.

        Args:
            folder: Folder to select
            readonly: If True, select folder in read-only mode

        Returns:
            Dictionary with folder information

        Raises:
            ValueError: If folder is not allowed
            ConnectionError: If connection error occurs
        """
        # Make sure the folder is allowed
        if not self._is_folder_allowed(folder):
            raise ValueError(f"Folder '{folder}' is not allowed")

        client = self._get_client()
        try:
            result = client.select_folder(folder, readonly=readonly)
            self.current_folder = folder
            logger.debug(f"Selected folder '{folder}'")
            return cast(Dict[Any, Any], result)
        except imapclient.IMAPClient.Error as e:
            logger.error(f"Error selecting folder {folder}: {e}")
            raise ConnectionError(f"Failed to select folder {folder}: {e}")

    def search(
        self,
        criteria: Union[str, List, Tuple, Dict[str, Any]],
        folder: str = "INBOX",
        charset: Optional[str] = None,
    ) -> List[int]:
        """Search for messages.

        Args:
            criteria: Search criteria (predefined string, list, or advanced dictionary)
            folder: Folder to search in
            charset: Character set for search criteria

        Returns:
            List of message UIDs

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()
        self.select_folder(folder, readonly=True)

        if isinstance(criteria, str):
            # Predefined criteria strings
            criteria_map: Dict[str, Union[str, List[Union[str, datetime, object]]]] = {
                "all": "ALL",
                "unseen": "UNSEEN",
                "seen": "SEEN",
                "answered": "ANSWERED",
                "unanswered": "UNANSWERED",
                "deleted": "DELETED",
                "undeleted": "UNDELETED",
                "flagged": "FLAGGED",
                "unflagged": "UNFLAGGED",
                "recent": "RECENT",
                "today": ["SINCE", datetime.now().date()],
                "yesterday": [
                    "SINCE",
                    (datetime.now() - timedelta(days=1)).date(),
                    "BEFORE",
                    datetime.now().date(),
                ],
                "week": ["SINCE", (datetime.now() - timedelta(days=7)).date()],
                "month": ["SINCE", (datetime.now() - timedelta(days=30)).date()],
            }

            if criteria.lower() in criteria_map:
                criteria = criteria_map[criteria.lower()]

        elif isinstance(criteria, dict):
            # Advanced search mapping
            search_list = []

            # 1. Handle Keywords (Subject/Body)
            if "keyword" in criteria:
                search_list.extend(["TEXT", criteria["keyword"]])
            if "subject" in criteria:
                search_list.extend(["SUBJECT", criteria["subject"]])
            if "body" in criteria:
                search_list.extend(["BODY", criteria["body"]])

            # 2. Handle Identity (Wildcards supported by most IMAP servers via string match)
            if "from" in criteria:
                search_list.extend(["FROM", criteria["from"]])
            if "to" in criteria:
                search_list.extend(["TO", criteria["to"]])
            if "cc" in criteria:
                search_list.extend(["CC", criteria["cc"]])

            # 3. Handle Date Ranges (YYYY-MM-DD or relative keywords)
            def parse_search_date(d_val: Union[str, datetime]) -> object:
                if isinstance(d_val, datetime):
                    return d_val.date()
                if isinstance(d_val, str):
                    try:
                        return datetime.strptime(d_val, "%Y-%m-%d").date()
                    except ValueError:
                        pass
                return d_val

            if "since" in criteria:
                search_list.extend(["SINCE", parse_search_date(criteria["since"])])
            if "before" in criteria:
                search_list.extend(["BEFORE", parse_search_date(criteria["before"])])

            # 4. Handle Labels (Gmail specific)
            if "label" in criteria:
                search_list.extend(["X-GM-LABELS", criteria["label"]])

            # 5. Handle Flags
            if criteria.get("unread"):
                search_list.append("UNSEEN")
            if criteria.get("flagged"):
                search_list.append("FLAGGED")

            # Default to ALL if no specific criteria provided
            if not search_list:
                search_list = ["ALL"]

            criteria = search_list

        # Cast to any because imapclient search criteria type is complex
        from typing import Any

        search_criteria: Any = criteria
        results = client.search(search_criteria, charset=charset)
        logger.debug(f"Search returned {len(results)} results for {search_criteria}")
        return list(results)

    def fetch_email(self, uid: int, folder: str = "INBOX") -> Optional[Email]:
        """Fetch a single email by UID.

        Args:
            uid: Email UID
            folder: Folder to fetch from

        Returns:
            Email object or None if not found

        Raises:
            ConnectionError: If not connected and connection fails
        """
        emails = self.fetch_emails([uid], folder=folder)
        return emails.get(uid)

    def fetch_emails(
        self,
        uids: List[int],
        folder: str = "INBOX",
        limit: Optional[int] = None,
    ) -> Dict[int, Email]:
        """Fetch multiple emails by UIDs.

        Args:
            uids: List of email UIDs
            folder: Folder to fetch from
            limit: Maximum number of emails to fetch

        Returns:
            Dictionary mapping UIDs to Email objects

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()
        self.select_folder(folder, readonly=True)

        # Apply limit if specified
        if limit is not None and limit > 0:
            uids = uids[:limit]

        # Fetch message data
        if not uids:
            return {}

        # Fetch messages with full metadata including Gmail extensions if supported
        fetch_attributes = ["BODY.PEEK[]", "FLAGS"]

        # Add Gmail-specific attributes if we're on Gmail
        capabilities = self.get_capabilities()
        is_gmail = "X-GM-EXT-1" in capabilities
        if is_gmail:
            fetch_attributes.extend(["X-GM-THRID", "X-GM-LABELS"])

        # Cast results to Any to avoid "Envelope is not iterable" errors from imapclient's poor typing
        from typing import Any

        result = client.fetch(uids, fetch_attributes)
        typed_result: Any = result

        # Parse emails
        emails = {}
        for uid, message_data in typed_result.items():
            # Handle potential None or missing keys safely
            raw_message = message_data.get(b"BODY[]") or message_data.get(
                b"BODY.PEEK[]"
            )
            flags = message_data.get(b"FLAGS", [])

            if not raw_message:
                logger.warning(f"No body found for message {uid}")
                continue

            # Gmail extensions
            gmail_thread_id = None
            gmail_labels = None
            if is_gmail:
                gmail_thread_id_raw = message_data.get(b"X-GM-THRID")
                if isinstance(gmail_thread_id_raw, bytes):
                    gmail_thread_id = gmail_thread_id_raw.decode("utf-8")
                elif gmail_thread_id_raw is not None:
                    gmail_thread_id = str(gmail_thread_id_raw)

                gmail_labels_raw = message_data.get(b"X-GM-LABELS")
                if gmail_labels_raw and isinstance(gmail_labels_raw, (list, tuple)):
                    gmail_labels = [
                        label.decode("utf-8")
                        if isinstance(label, bytes)
                        else str(label)
                        for label in gmail_labels_raw
                    ]

            # Convert flags to strings
            str_flags = []
            if flags and isinstance(flags, (list, tuple)):
                str_flags = [
                    f.decode("utf-8") if isinstance(f, bytes) else str(f) for f in flags
                ]

            # Parse email
            if not isinstance(raw_message, bytes):
                logger.warning(f"Message data for {uid} is not bytes")
                continue

            message = email.message_from_bytes(raw_message)
            email_obj = Email.from_message(
                message,
                uid=uid,
                folder=folder,
                gmail_thread_id=gmail_thread_id,
                gmail_labels=gmail_labels,
            )
            email_obj.flags = str_flags

            emails[uid] = email_obj

        return emails

    def fetch_thread(self, uid: int, folder: str = "INBOX") -> List[Email]:
        """Fetch all emails in a thread.

        This method retrieves the initial email identified by the UID, and then
        searches for all related emails that belong to the same thread using
        Message-ID, In-Reply-To, References headers, and Subject matching as a fallback.

        Args:
            uid: UID of any email in the thread
            folder: Folder to fetch from

        Returns:
            List of Email objects in the thread, sorted chronologically

        Raises:
            ConnectionError: If not connected and connection fails
            ValueError: If the initial email cannot be found
        """
        self.ensure_connected()
        self.select_folder(folder, readonly=True)

        # Fetch the initial email
        initial_email = self.fetch_email(uid, folder)
        if not initial_email:
            raise ValueError(
                f"Initial email with UID {uid} not found in folder {folder}"
            )

        # Get thread identifiers from the initial email
        gmail_thread_id = initial_email.gmail_thread_id
        message_id = initial_email.headers.get("Message-ID", "")
        subject = initial_email.subject

        # Set to store all UIDs that belong to the thread
        thread_uids = {uid}

        # Optimization for Gmail: use X-GM-THRID if available
        capabilities = self.get_capabilities()
        if gmail_thread_id and "X-GM-EXT-1" in capabilities:
            try:
                thread_results = self.search_by_thread_id(gmail_thread_id, folder)
                thread_uids.update(thread_results)
                # If we have Gmail thread results, we can skip manual header-based traversal
                # as X-GM-THRID is much more reliable and faster.
                thread_emails = self.fetch_emails(list(thread_uids), folder)
                return sorted(
                    thread_emails.values(),
                    key=lambda e: e.date if e.date else datetime.min,
                )
            except Exception as e:
                logger.warning(f"Error searching by Gmail thread ID: {e}")

        # Strip "Re:", "Fwd:", etc. from the subject for better matching
        clean_subject = re.sub(
            r"^(?:Re|Fwd|Fw|FWD|RE|FW):\s*", "", subject, flags=re.IGNORECASE
        )

        # Set to store all UIDs that belong to the thread
        thread_uids = {uid}

        # Search for emails with this Message-ID in the References or In-Reply-To headers
        if message_id:
            # Look for emails that reference this message ID
            references_query = f'HEADER References "{message_id}"'
            try:
                references_results = self.search(references_query, folder)
                thread_uids.update(references_results)
            except Exception as e:
                logger.warning(f"Error searching for References: {e}")

            # Look for direct replies to this message
            inreplyto_query = f'HEADER In-Reply-To "{message_id}"'
            try:
                inreplyto_results = self.search(inreplyto_query, folder)
                thread_uids.update(inreplyto_results)
            except Exception as e:
                logger.warning(f"Error searching for In-Reply-To: {e}")

            # If the initial email has References or In-Reply-To, fetch those messages too
            initial_references = initial_email.headers.get("References", "")
            initial_inreplyto = initial_email.headers.get("In-Reply-To", "")

            # Extract all message IDs from the References header
            if initial_references:
                for ref_id in re.findall(r"<[^>]+>", initial_references):
                    query = f'HEADER Message-ID "{ref_id}"'
                    try:
                        results = self.search(query, folder)
                        thread_uids.update(results)
                    except Exception as e:
                        logger.warning(
                            f"Error searching for Referenced message {ref_id}: {e}"
                        )

            # Look for the message that this is a reply to
            if initial_inreplyto:
                query = f'HEADER Message-ID "{initial_inreplyto}"'
                try:
                    results = self.search(query, folder)
                    thread_uids.update(results)
                except Exception as e:
                    logger.warning(f"Error searching for In-Reply-To message: {e}")

        # If we still have only the initial email or a small thread, try subject-based matching
        if len(thread_uids) <= 2 and clean_subject:
            # Look for emails with the same or related subject (Re: Subject)
            # This is a fallback for email clients that don't properly use References/In-Reply-To
            subject_query = f'SUBJECT "{clean_subject}"'
            try:
                subject_results = self.search(subject_query, folder)

                # Filter out emails that are unlikely to be part of the thread
                # For example, avoid including all emails with a common subject like "Hello"
                if len(subject_results) < 20:  # Set a reasonable limit
                    thread_uids.update(subject_results)
                else:
                    # If there are too many results, try a more strict approach
                    # Look for exact subject match or common Re: pattern
                    strict_matches = []
                    strict_subjects = [
                        clean_subject,
                        f"Re: {clean_subject}",
                        f"RE: {clean_subject}",
                        f"Fwd: {clean_subject}",
                        f"FWD: {clean_subject}",
                        f"Fw: {clean_subject}",
                        f"FW: {clean_subject}",
                    ]

                    # Fetch subjects for all candidate emails
                    candidate_emails = self.fetch_emails(subject_results, folder)
                    for candidate_uid, candidate_email in candidate_emails.items():
                        if candidate_email.subject in strict_subjects:
                            strict_matches.append(candidate_uid)

                    thread_uids.update(strict_matches)
            except Exception as e:
                logger.warning(f"Error searching by subject: {e}")

        # Fetch all discovered thread emails
        thread_emails = self.fetch_emails(list(thread_uids), folder)

        # Sort emails by date (chronologically)
        sorted_emails = sorted(
            thread_emails.values(), key=lambda e: e.date if e.date else datetime.min
        )

        return sorted_emails

    def mark_email(
        self,
        uid: int,
        folder: str,
        flag: str,
        value: bool = True,
    ) -> bool:
        """Mark email with flag.

        Args:
            uid: Email UID
            folder: Folder containing the email
            flag: Flag to set or remove
            value: True to set, False to remove

        Returns:
            True if successful

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()
        self.select_folder(folder)

        try:
            if value:
                client.add_flags([uid], flag)
                logger.debug(f"Added flag {flag} to message {uid}")
            else:
                client.remove_flags([uid], flag)
                logger.debug(f"Removed flag {flag} from message {uid}")
            return True
        except Exception as e:
            logger.error(f"Failed to mark email: {e}")
            return False

    def move_email(self, uid: int, source_folder: str, target_folder: str) -> bool:
        """Move email to another folder.

        Args:
            uid: Email UID
            source_folder: Source folder
            target_folder: Target folder

        Returns:
            True if successful

        Raises:
            ConnectionError: If not connected and connection fails
            ValueError: If folder is not allowed
        """
        client = self._get_client()

        # Check if folders are allowed
        if self.allowed_folders is not None:
            if source_folder not in self.allowed_folders:
                raise ValueError(f"Source folder '{source_folder}' is not allowed")
            if target_folder not in self.allowed_folders:
                raise ValueError(f"Target folder '{target_folder}' is not allowed")

        # Select source folder
        self.select_folder(source_folder)

        try:
            # Move email (copy + delete)
            client.copy([uid], target_folder)
            client.add_flags([uid], r"\Deleted")
            client.expunge()
            logger.debug(f"Moved message {uid} from {source_folder} to {target_folder}")
            return True
        except Exception as e:
            logger.error(f"Failed to move email: {e}")
            return False

    def delete_email(self, uid: int, folder: str) -> bool:
        """Delete email.

        Args:
            uid: Email UID
            folder: Folder containing the email

        Returns:
            True if successful

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()
        self.select_folder(folder)

        try:
            client.add_flags([uid], r"\Deleted")
            client.expunge()
            logger.debug(f"Deleted message {uid} from {folder}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete email: {e}")
            return False

    def set_gmail_labels(self, uid: int, folder: str, labels: List[str]) -> bool:
        """Set Gmail labels for an email.

        Args:
            uid: Email UID
            folder: Folder containing the email
            labels: List of labels to set

        Returns:
            True if successful
        """
        client = self._get_client()

        capabilities = self.get_capabilities()
        if "X-GM-EXT-1" not in capabilities:
            logger.warning("Gmail extensions not supported by server")
            return False

        self.select_folder(folder)

        try:
            # X-GM-LABELS requires the server to support X-GM-EXT-1
            client.set_gmail_labels([uid], labels)
            return True
        except Exception as e:
            logger.error(f"Failed to set Gmail labels: {e}")
            return False

    def add_gmail_labels(self, uid: int, folder: str, labels: List[str]) -> bool:
        """Add Gmail labels to an email.

        Args:
            uid: Email UID
            folder: Folder containing the email
            labels: List of labels to add

        Returns:
            True if successful
        """
        client = self._get_client()

        capabilities = self.get_capabilities()
        if "X-GM-EXT-1" not in capabilities:
            logger.warning("Gmail extensions not supported by server")
            return False

        self.select_folder(folder)

        try:
            client.add_gmail_labels([uid], labels)
            return True
        except Exception as e:
            logger.error(f"Failed to add Gmail labels: {e}")
            return False

    def remove_gmail_labels(self, uid: int, folder: str, labels: List[str]) -> bool:
        """Remove Gmail labels from an email.

        Args:
            uid: Email UID
            folder: Folder containing the email
            labels: List of labels to remove

        Returns:
            True if successful
        """
        client = self._get_client()

        capabilities = self.get_capabilities()
        if "X-GM-EXT-1" not in capabilities:
            logger.warning("Gmail extensions not supported by server")
            return False

        self.select_folder(folder)

        try:
            client.remove_gmail_labels([uid], labels)
            return True
        except Exception as e:
            logger.error(f"Failed to remove Gmail labels: {e}")
            return False

    def search_by_thread_id(self, thread_id: str, folder: str = "INBOX") -> List[int]:
        """Search for emails by Gmail thread ID.

        Args:
            thread_id: Gmail thread ID (X-GM-THRID)
            folder: Folder to search in

        Returns:
            List of message UIDs
        """
        client = self._get_client()

        capabilities = self.get_capabilities()
        if "X-GM-EXT-1" not in capabilities:
            logger.warning("Gmail extensions not supported by server")
            return []

        self.select_folder(folder, readonly=True)

        try:
            # imapclient supports X-GM-THRID in search
            results = client.search([f"X-GM-THRID", thread_id])  # type: ignore
            return list(results)
        except Exception as e:
            logger.error(f"Error searching by thread ID: {e}")
            return []

    def get_message_count(
        self, folder: str = "INBOX", status: str = "TOTAL", refresh: bool = False
    ) -> int:
        """Get message count for a folder.

        Args:
            folder: Folder name
            status: Status type (TOTAL, UNSEEN, SEEN, RECENT, DELETED)
            refresh: Force refresh cache

        Returns:
            Message count
        """
        client = self._get_client()

        # Check cache
        if not refresh and folder in self.folder_message_counts:
            if status.upper() in self.folder_message_counts[folder]:
                return self.folder_message_counts[folder][status.upper()]

        # Select folder
        try:
            # folder_status is better for this as it doesn't change selection and returns multiple counts
            status_keys = [b"MESSAGES", b"RECENT", b"UNSEEN"]
            status_res = client.folder_status(folder, status_keys)

            total = status_res.get(b"MESSAGES", 0)
            unseen = status_res.get(b"UNSEEN", 0)
            recent = status_res.get(b"RECENT", 0)

            counts = {
                "TOTAL": total,
                "UNSEEN": unseen,
                "RECENT": recent,
                "SEEN": total - unseen if total >= unseen else 0,
            }

            # If DELETED is specifically requested, we still have to search as it's not usually in STATUS
            if status.upper() == "DELETED":
                self.select_folder(folder, readonly=True)
                uids = client.search("DELETED")
                counts["DELETED"] = len(uids)

            self.folder_message_counts[folder] = counts
            return cast(int, counts.get(status.upper(), 0))
        except Exception as e:
            logger.error(f"Error getting message count for {folder}: {e}")
            if not self._is_folder_allowed(folder):
                raise ValueError(f"Folder '{folder}' is not allowed")
            return 0

    def get_unread_messages(
        self,
        folder: str = "INBOX",
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "date",
        sort_order: str = "desc",
    ) -> Dict[int, Email]:
        """Get unread messages from a folder.

        Args:
            folder: Folder name
            limit: Maximum number of messages to return
            offset: Number of messages to skip
            sort_by: Field to sort by (date, subject, from)
            sort_order: Sort order (asc, desc)

        Returns:
            Dictionary mapping UIDs to Email objects

        Raises:
            ValueError: If parameters are invalid
            ConnectionError: If connection fails
        """
        if limit <= 0:
            raise ValueError("Limit must be positive")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        if sort_by.lower() not in ["date", "subject", "from"]:
            raise ValueError(f"Invalid sort_by: {sort_by}")
        if sort_order.lower() not in ["asc", "desc"]:
            raise ValueError(f"Invalid sort_order: {sort_order}")

        self.ensure_connected()

        # Search for unread messages
        uids = self.search("UNSEEN", folder=folder)

        if not uids:
            return {}

        # Fetch messages
        emails = self.fetch_emails(uids, folder=folder)

        # Sort emails
        email_list = list(emails.values())

        reverse = sort_order.lower() == "desc"
        if sort_by.lower() == "date":
            email_list.sort(key=lambda e: e.date or datetime.min, reverse=reverse)
        elif sort_by.lower() == "subject":
            email_list.sort(key=lambda e: e.subject.lower(), reverse=reverse)
        elif sort_by.lower() == "from":
            email_list.sort(key=lambda e: str(e.from_).lower(), reverse=reverse)

        # Apply pagination
        paginated_emails = email_list[offset : offset + limit]

        # Return as dict
        return {e.uid: e for e in paginated_emails if e.uid is not None}

    def _get_drafts_folder(self) -> str:
        """Get the drafts folder name for the current server.

        Returns:
            The name of the drafts folder, or "INBOX" as fallback
        """
        self.ensure_connected()
        folders = self.list_folders(refresh=True)

        # Check for Gmail's special folders structure
        if self.config.host and "gmail" in self.config.host.lower():
            gmail_drafts = [f for f in folders if f.lower().endswith("/drafts")]
            if gmail_drafts:
                logger.debug(f"Using Gmail drafts folder: {gmail_drafts[0]}")
                return gmail_drafts[0]

        # Look for standard drafts folder names (case-insensitive)
        drafts_folder_names = [
            "Drafts",
            "Draft",
            "Brouillons",
            "Borradores",
            "Entwürfe",
        ]
        for folder in folders:
            if folder.lower() in [name.lower() for name in drafts_folder_names]:
                logger.debug(f"Using drafts folder: {folder}")
                return folder

        # Fallback to INBOX if no drafts folder found
        logger.warning("No drafts folder found, using INBOX as fallback")
        return "INBOX"

    def save_draft_mime(self, message: Any) -> Optional[int]:
        """Save a MIME message as a draft.

        Args:
            message: email.message.Message object to save as draft

        Returns:
            UID of the saved draft if available, None otherwise

        Raises:
            ConnectionError: If not connected and connection fails
        """
        client = self._get_client()

        # Get the drafts folder
        drafts_folder = self._get_drafts_folder()

        try:
            # Convert message to bytes if it's not already
            if hasattr(message, "as_bytes"):
                message_bytes = message.as_bytes()
            else:
                message_bytes = message.as_string().encode("utf-8")

            # Save the draft with Draft flag
            response = client.append(drafts_folder, message_bytes, flags=(r"\Draft",))

            # Try to extract the UID from the response
            uid = None
            if isinstance(response, bytes) and b"APPENDUID" in response:
                # Parse the APPENDUID response (format: [APPENDUID <uidvalidity> <uid>])
                try:
                    # Use a more robust parsing approach
                    match = re.search(rb"APPENDUID\s+\d+\s+(\d+)", response)
                    if match:
                        uid = int(match.group(1))
                        logger.debug(f"Draft saved with UID: {uid}")
                except (IndexError, ValueError) as e:
                    logger.warning(f"Could not parse UID from response: {e}")

            if uid is None:
                logger.warning(
                    f"Could not extract UID from append response: {response}"
                )

            return uid

        except Exception as e:
            logger.error(f"Failed to save draft: {e}")
            return None
