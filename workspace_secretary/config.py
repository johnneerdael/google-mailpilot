"""Configuration handling for IMAP MCP server."""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import yaml  # type: ignore
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


# Load environment variables from .env file if it exists
load_dotenv()


@dataclass
class OAuth2Config:
    """OAuth2 configuration for IMAP authentication."""

    client_id: str
    client_secret: str
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None
    token_expiry: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["OAuth2Config"]:
        """Create OAuth2 configuration from dictionary."""
        if not data:
            return None

        # OAuth2 credentials can be specified in environment variables
        client_id = data.get("client_id") or os.environ.get("GMAIL_CLIENT_ID")
        client_secret = data.get("client_secret") or os.environ.get(
            "GMAIL_CLIENT_SECRET"
        )
        refresh_token = data.get("refresh_token") or os.environ.get(
            "GMAIL_REFRESH_TOKEN"
        )

        if not client_id or not client_secret:
            return None

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            access_token=data.get("access_token"),
            token_expiry=data.get("token_expiry"),
        )


@dataclass
class ImapConfig:
    """IMAP server configuration."""

    host: str
    port: int
    username: str
    password: Optional[str] = None
    oauth2: Optional[OAuth2Config] = None
    use_ssl: bool = True

    @property
    def is_gmail(self) -> bool:
        """Check if this is a Gmail configuration."""
        return self.host.endswith("gmail.com") or self.host.endswith("googlemail.com")

    @property
    def requires_oauth2(self) -> bool:
        """Check if this configuration requires OAuth2."""
        return self.is_gmail and self.oauth2 is not None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImapConfig":
        """Create configuration from dictionary."""
        # Create OAuth2 config if present
        oauth2_config = OAuth2Config.from_dict(data.get("oauth2", {}))

        # Password can be specified in environment variable
        password = data.get("password") or os.environ.get("IMAP_PASSWORD")

        # For Gmail, we need either password (for app-specific password) or OAuth2 credentials
        host = data.get("host", "")
        is_gmail = host.endswith("gmail.com") or host.endswith("googlemail.com")

        if is_gmail and not oauth2_config and not password:
            raise ValueError(
                "Gmail requires either an app-specific password or OAuth2 credentials"
            )
        elif not is_gmail and not password:
            raise ValueError(
                "IMAP password must be specified in config or IMAP_PASSWORD environment variable"
            )

        return cls(
            host=data["host"],
            port=data.get("port", 993 if data.get("use_ssl", True) else 143),
            username=data["username"],
            password=password,
            oauth2=oauth2_config,
            use_ssl=data.get("use_ssl", True),
        )


@dataclass
class CalendarConfig:
    """Calendar configuration."""

    enabled: bool = False
    verified_client: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarConfig":
        """Create Calendar configuration from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            verified_client=data.get("verified_client"),
        )


@dataclass
class WorkingHoursConfig:
    """Working hours configuration for scheduling."""

    start: str
    end: str
    workdays: List[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])

    def __post_init__(self):
        """Validate working hours configuration."""
        import re

        # Validate time format (must be exactly HH:MM)
        time_pattern = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

        if not time_pattern.match(self.start):
            raise ValueError(
                f"start time '{self.start}' must be in HH:MM format (e.g., 09:00)"
            )
        if not time_pattern.match(self.end):
            raise ValueError(
                f"end time '{self.end}' must be in HH:MM format (e.g., 17:00)"
            )

        # Parse times for comparison
        start_h, start_m = map(int, self.start.split(":"))
        end_h, end_m = map(int, self.end.split(":"))

        # Validate start < end
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        if start_minutes >= end_minutes:
            raise ValueError(
                f"Working hours start time must be before end time (start: {self.start}, end: {self.end})"
            )

        # Validate workdays
        if not self.workdays:
            raise ValueError("workdays must contain at least one workday")

        for day in self.workdays:
            if not (1 <= day <= 7):
                raise ValueError(
                    f"Invalid workday: {day}. workdays must be between 1 and 7 (1=Monday, 7=Sunday)"
                )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkingHoursConfig":
        """Create WorkingHoursConfig from dictionary."""
        return cls(
            start=data.get("start", "09:00"),
            end=data.get("end", "17:00"),
            workdays=data.get("workdays", [1, 2, 3, 4, 5]),
        )


@dataclass
class UserIdentityConfig:
    """User identity for email ownership detection."""

    email: str
    full_name: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.email = self.email.lower()
        if self.aliases is None:
            self.aliases = []
        self.aliases = [alias.lower() for alias in self.aliases]

    @property
    def name_parts(self) -> List[str]:
        """Split full_name into individual name parts (first, middle, last, etc.)."""
        if not self.full_name:
            return []
        return [part.strip() for part in self.full_name.split() if part.strip()]

    @property
    def first_name(self) -> Optional[str]:
        """Extract first name from full_name."""
        parts = self.name_parts
        return parts[0] if parts else None

    @property
    def last_name(self) -> Optional[str]:
        """Extract last name from full_name."""
        parts = self.name_parts
        return parts[-1] if len(parts) > 1 else None

    def matches_email(self, address: str) -> bool:
        """Check if an email address belongs to this user."""
        addr_lower = address.lower()
        if addr_lower == self.email:
            return True
        return addr_lower in self.aliases

    def matches_name(self, text: str) -> bool:
        """Check if text contains the user's name."""
        if not self.full_name:
            return False
        return self.full_name.lower() in text.lower()

    def matches_name_part(self, text: str) -> bool:
        """Check if text contains any part of user's name (first, last, etc.)."""
        if not self.name_parts:
            return False
        text_lower = text.lower()
        return any(part.lower() in text_lower for part in self.name_parts)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserIdentityConfig":
        return cls(
            email=data["email"],
            full_name=data.get("full_name"),
            aliases=data.get("aliases", []),
        )


@dataclass
class BearerAuthConfig:
    """Bearer token authentication configuration."""

    enabled: bool = False
    token: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BearerAuthConfig":
        return cls(
            enabled=data.get("enabled", False),
            token=data.get("token"),
        )


class DatabaseBackend(Enum):
    """Database backend type."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"

    @classmethod
    def from_string(cls, value: str) -> "DatabaseBackend":
        normalized = value.lower().strip()
        if normalized == "sqlite":
            return cls.SQLITE
        elif normalized in ("postgres", "postgresql"):
            return cls.POSTGRES
        else:
            raise ValueError(
                f"Invalid database backend '{value}'. Must be 'sqlite' or 'postgres'."
            )


@dataclass
class SqliteConfig:
    """SQLite database configuration."""

    email_cache_path: str = "config/email_cache.db"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SqliteConfig":
        return cls(
            email_cache_path=data.get("email_cache_path", "config/email_cache.db"),
        )


@dataclass
class PostgresConfig:
    """PostgreSQL database configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "secretary"
    user: str = "secretary"
    password: str = ""
    ssl_mode: str = "prefer"

    @property
    def connection_string(self) -> str:
        """Generate PostgreSQL connection string."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.ssl_mode}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostgresConfig":
        return cls(
            host=data.get("host") or os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(data.get("port") or os.environ.get("POSTGRES_PORT", "5432")),
            database=data.get("database")
            or os.environ.get("POSTGRES_DATABASE", "secretary"),
            user=data.get("user") or os.environ.get("POSTGRES_USER", "secretary"),
            password=data.get("password") or os.environ.get("POSTGRES_PASSWORD", ""),
            ssl_mode=data.get("ssl_mode", "prefer"),
        )


@dataclass
class EmbeddingsConfig:
    """Embeddings configuration for semantic search."""

    enabled: bool = False
    endpoint: str = "https://api.openai.com/v1/embeddings"
    model: str = "text-embedding-3-small"
    api_key: str = ""
    dimensions: int = 1536
    batch_size: int = 100

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingsConfig":
        api_key = (
            data.get("api_key")
            or os.environ.get("EMBEDDINGS_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        return cls(
            enabled=data.get("enabled", False),
            endpoint=data.get("endpoint", "https://api.openai.com/v1/embeddings"),
            model=data.get("model", "text-embedding-3-small"),
            api_key=api_key,
            dimensions=data.get("dimensions", 1536),
            batch_size=data.get("batch_size", 100),
        )


@dataclass
class DatabaseConfig:
    """Database configuration."""

    backend: DatabaseBackend = DatabaseBackend.SQLITE
    sqlite: SqliteConfig = field(default_factory=SqliteConfig)
    postgres: Optional[PostgresConfig] = None
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)

    def __post_init__(self):
        """Validate database configuration."""
        if self.backend == DatabaseBackend.POSTGRES:
            if not self.postgres:
                raise ValueError(
                    "PostgreSQL configuration required when backend is 'postgres'"
                )
            if not self.embeddings.enabled:
                logger.warning(
                    "PostgreSQL backend without embeddings - consider using SQLite for simpler deployment"
                )
            if self.embeddings.enabled and not self.embeddings.api_key:
                raise ValueError(
                    "Embeddings API key required when embeddings are enabled"
                )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseConfig":
        backend_str = data.get("backend", "sqlite")
        backend = DatabaseBackend.from_string(backend_str)

        sqlite_config = SqliteConfig.from_dict(data.get("sqlite", {}))
        postgres_config = (
            PostgresConfig.from_dict(data.get("postgres", {}))
            if data.get("postgres")
            else None
        )
        embeddings_config = EmbeddingsConfig.from_dict(data.get("embeddings", {}))

        return cls(
            backend=backend,
            sqlite=sqlite_config,
            postgres=postgres_config,
            embeddings=embeddings_config,
        )


@dataclass
class ServerConfig:
    """MCP server configuration."""

    imap: ImapConfig
    timezone: str
    working_hours: WorkingHoursConfig
    identity: UserIdentityConfig
    allowed_folders: Optional[List[str]] = None
    calendar: Optional[CalendarConfig] = None
    vip_senders: List[str] = field(default_factory=list)
    bearer_auth: BearerAuthConfig = field(default_factory=BearerAuthConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    def __post_init__(self):
        """Validate server configuration."""
        # Validate timezone
        try:
            ZoneInfo(self.timezone)
        except Exception as e:
            raise ValueError(
                f"Invalid timezone '{self.timezone}': {e}. "
                "Must be a valid IANA timezone (e.g., 'America/Los_Angeles')"
            )

        # Normalize VIP senders to lowercase for case-insensitive matching
        self.vip_senders = [email.lower() for email in self.vip_senders]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerConfig":
        """Create configuration from dictionary."""
        # Timezone is required
        if "timezone" not in data:
            raise ValueError(
                "Missing required 'timezone' configuration. "
                "Please specify a valid IANA timezone (e.g., 'America/Los_Angeles')"
            )

        # Working hours is required
        if "working_hours" not in data:
            raise ValueError(
                "Missing required 'working_hours' configuration. "
                "Please specify start and end times (e.g., start: '09:00', end: '17:00')"
            )

        identity_data = data.get("identity", {})
        if not identity_data.get("email"):
            identity_data["email"] = data.get("imap", {}).get("username", "")

        return cls(
            imap=ImapConfig.from_dict(data.get("imap", {})),
            timezone=data["timezone"],
            working_hours=WorkingHoursConfig.from_dict(data["working_hours"]),
            identity=UserIdentityConfig.from_dict(identity_data),
            allowed_folders=data.get("allowed_folders"),
            calendar=CalendarConfig.from_dict(data.get("calendar", {})),
            vip_senders=data.get("vip_senders", []),
            bearer_auth=BearerAuthConfig.from_dict(data.get("bearer_auth", {})),
            database=DatabaseConfig.from_dict(data.get("database", {})),
        )


def load_config(config_path: Optional[str] = None) -> ServerConfig:
    """Load configuration from file or environment variables.

    Args:
        config_path: Path to configuration file

    Returns:
        Server configuration

    Raises:
        FileNotFoundError: If configuration file is not found
        ValueError: If configuration is invalid
    """
    # Default locations to check for config file
    # Container paths first (Docker), then local dev paths
    default_locations = [
        Path("/app/config/config.yaml"),
        Path("/app/config/config.yml"),
        Path("config.yaml"),
        Path("config.yml"),
        Path("~/.config/workspace-secretary/config.yaml"),
        Path("/etc/workspace-secretary/config.yaml"),
    ]

    # Load from specified path or try default locations
    config_data: Dict[str, Any] = {}
    if config_path:
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
            logger.info(f"Loaded configuration from {config_path}")
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {config_path}")
    else:
        for path in default_locations:
            expanded_path = path.expanduser()
            if expanded_path.exists():
                with open(expanded_path, "r") as f:
                    config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {expanded_path}")
                break

    # If environment variables are set, they take precedence
    if not config_data:
        logger.info("No configuration file found, using environment variables")
        if not os.environ.get("IMAP_HOST"):
            raise ValueError(
                "No configuration file found and IMAP_HOST environment variable not set"
            )

        config_data = {
            "imap": {
                "host": os.environ.get("IMAP_HOST"),
                "port": int(os.environ.get("IMAP_PORT", "993")),
                "username": os.environ.get("IMAP_USERNAME"),
                "password": os.environ.get("IMAP_PASSWORD"),
                "use_ssl": os.environ.get("IMAP_USE_SSL", "true").lower() == "true",
            },
            "timezone": os.environ.get("WORKSPACE_TIMEZONE", "UTC"),
            "working_hours": {
                "start": os.environ.get("WORKING_HOURS_START", "09:00"),
                "end": os.environ.get("WORKING_HOURS_END", "17:00"),
                "workdays": list(
                    map(
                        int,
                        os.environ.get("WORKING_HOURS_DAYS", "1,2,3,4,5").split(","),
                    )
                ),
            },
            "vip_senders": os.environ.get("VIP_SENDERS", "").split(",")
            if os.environ.get("VIP_SENDERS")
            else [],
        }

        if os.environ.get("IMAP_ALLOWED_FOLDERS"):
            allowed_folders_str = os.environ.get("IMAP_ALLOWED_FOLDERS")
            if allowed_folders_str:
                config_data["allowed_folders"] = allowed_folders_str.split(",")  # type: ignore

    # Create config object
    try:
        return ServerConfig.from_dict(config_data)
    except KeyError as e:
        raise ValueError(f"Missing required configuration: {e}")
