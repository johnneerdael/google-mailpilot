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

        # Log warning if credentials missing - server will start but remain unenrolled
        if is_gmail and not oauth2_config and not password:
            logger.warning(
                "Gmail credentials not configured. Choose one method:\n\n"
                "  Option 1 - OAuth2 (recommended):\n"
                "    docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \\\n"
                "      --client-id='YOUR_CLIENT_ID' \\\n"
                "      --client-secret='YOUR_CLIENT_SECRET'\n\n"
                "  Option 2 - App Password:\n"
                "    docker exec -it workspace-secretary uv run python -m workspace_secretary.app_password"
            )
        elif not is_gmail and not password:
            logger.warning(
                "IMAP password not configured - server will start but email sync disabled"
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

    POSTGRES = "postgres"

    @classmethod
    def from_string(cls, value: str) -> "DatabaseBackend":
        normalized = value.lower().strip()
        if normalized in ("postgres", "postgresql"):
            return cls.POSTGRES
        raise ValueError(f"Invalid database backend '{value}'. Must be 'postgres'.")


class WebAuthMethod(Enum):
    """Web authentication method."""

    NONE = "none"
    PASSWORD = "password"
    OIDC = "oidc"
    SAML2 = "saml2"

    @classmethod
    def from_string(cls, value: str) -> "WebAuthMethod":
        normalized = value.lower().strip()
        if normalized == "none":
            return cls.NONE
        elif normalized == "password":
            return cls.PASSWORD
        elif normalized == "oidc":
            return cls.OIDC
        elif normalized == "saml2":
            return cls.SAML2
        else:
            raise ValueError(
                f"Invalid auth method '{value}'. Must be 'none', 'password', 'oidc', or 'saml2'."
            )


class WebApiFormat(Enum):
    """Web agent API format."""

    OPENAI_CHAT = "openai.chat"
    OPENAI_RESPONSES = "openai.responses"
    ANTHROPIC_CHAT = "anthropic.chat"

    @classmethod
    def from_string(cls, value: str) -> "WebApiFormat":
        normalized = value.lower().strip()
        if normalized in ("openai.chat", "openai.chat.completions"):
            return cls.OPENAI_CHAT
        elif normalized in ("openai.responses",):
            return cls.OPENAI_RESPONSES
        elif normalized in ("anthropic.chat", "anthropic.chat.completions"):
            return cls.ANTHROPIC_CHAT
        else:
            raise ValueError(
                f"Invalid API format '{value}'. Must be 'openai.chat', 'openai.responses', or 'anthropic.chat'."
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
    provider: str = "gemini"  # gemini | cohere | openai_compat
    fallback_provider: Optional[str] = None  # Optional fallback on rate limit
    endpoint: str = "https://api.openai.com/v1/embeddings"
    model: str = "text-embedding-3-small"
    api_key: str = ""
    dimensions: int = 3072  # 3072 recommended for best quality
    batch_size: int = 100
    max_chars: int = 8000  # Gemini limit
    # Cohere-specific options
    input_type: str = "search_document"  # Cohere: search_document | search_query
    truncate: str = "END"  # Cohere: NONE | START | END
    # Gemini-specific options
    gemini_api_key: str = ""
    gemini_model: str = "text-embedding-004"
    task_type: str = "RETRIEVAL_DOCUMENT"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingsConfig":
        api_key = (
            data.get("api_key")
            or os.environ.get("EMBEDDINGS_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        gemini_api_key = data.get("gemini_api_key") or os.environ.get(
            "GEMINI_API_KEY", ""
        )
        return cls(
            enabled=data.get("enabled", False),
            provider=data.get("provider", "gemini"),
            fallback_provider=data.get("fallback_provider"),
            endpoint=data.get("endpoint", "https://api.openai.com/v1/embeddings"),
            model=data.get("model", "text-embedding-3-small"),
            api_key=api_key,
            dimensions=data.get("dimensions", 3072),
            batch_size=data.get("batch_size", 100),
            max_chars=data.get("max_chars", 8000),
            input_type=data.get("input_type", "search_document"),
            truncate=data.get("truncate", "END"),
            gemini_api_key=gemini_api_key,
            gemini_model=data.get("gemini_model", "text-embedding-004"),
            task_type=data.get("task_type", "RETRIEVAL_DOCUMENT"),
        )


@dataclass
class DatabaseConfig:
    """Database configuration."""

    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.POSTGRES

    def __post_init__(self):
        if self.embeddings.enabled and not self.embeddings.api_key:
            raise ValueError("Embeddings API key required when embeddings are enabled")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseConfig":
        backend_str = data.get("backend", "postgres")
        backend = DatabaseBackend.from_string(backend_str)
        if backend is not DatabaseBackend.POSTGRES:
            raise ValueError("Only postgres is supported")

        postgres_config = PostgresConfig.from_dict(data.get("postgres", {}))
        embeddings_config = EmbeddingsConfig.from_dict(data.get("embeddings", {}))

        return cls(
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
    web: Optional["WebConfig"] = None

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

        web_config = (
            WebConfig.from_dict(data.get("web", {})) if data.get("web") else None
        )

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
            web=web_config,
        )


@dataclass
class WebAgentConfig:
    base_url: str = "https://api.openai.com/v1"
    api_format: WebApiFormat = WebApiFormat.OPENAI_CHAT
    model: str = "gpt-4o"
    token_limit: int = 128000
    api_key: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebAgentConfig":
        api_key = (
            data.get("api_key")
            or os.environ.get("WEB_AGENT_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        api_format_str = data.get("api_format", "openai.chat")
        return cls(
            base_url=data.get("base_url", "https://api.openai.com/v1"),
            api_format=WebApiFormat.from_string(api_format_str),
            model=data.get("model", "gpt-4o"),
            token_limit=data.get("token_limit", 128000),
            api_key=api_key,
        )


@dataclass
class WebOIDCConfig:
    provider_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: List[str] = field(default_factory=lambda: ["openid", "profile", "email"])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebOIDCConfig":
        return cls(
            provider_url=data.get("provider_url", ""),
            client_id=data.get("client_id") or os.environ.get("OIDC_CLIENT_ID", ""),
            client_secret=data.get("client_secret")
            or os.environ.get("OIDC_CLIENT_SECRET", ""),
            scopes=data.get("scopes", ["openid", "profile", "email"]),
        )


@dataclass
class WebSAML2Config:
    idp_metadata_url: str = ""
    sp_entity_id: str = ""
    sp_acs_url: str = ""
    sp_sls_url: str = ""
    certificate_path: str = ""
    private_key_path: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebSAML2Config":
        return cls(
            idp_metadata_url=data.get("idp_metadata_url", ""),
            sp_entity_id=data.get("sp_entity_id", ""),
            sp_acs_url=data.get("sp_acs_url", ""),
            sp_sls_url=data.get("sp_sls_url", ""),
            certificate_path=data.get("certificate_path", ""),
            private_key_path=data.get("private_key_path", ""),
        )


@dataclass
class WebAuthConfig:
    method: WebAuthMethod = WebAuthMethod.NONE
    password_hash: str = ""
    session_secret: str = ""
    session_expiry_hours: int = 24
    oidc: Optional[WebOIDCConfig] = None
    saml2: Optional[WebSAML2Config] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebAuthConfig":
        method_str = data.get("method", "none")
        method = WebAuthMethod.from_string(method_str)

        session_secret = data.get("session_secret") or os.environ.get(
            "WEB_SESSION_SECRET", ""
        )
        password_hash = data.get("password_hash") or os.environ.get(
            "WEB_PASSWORD_HASH", ""
        )

        oidc_config = (
            WebOIDCConfig.from_dict(data.get("oidc", {})) if data.get("oidc") else None
        )
        saml2_config = (
            WebSAML2Config.from_dict(data.get("saml2", {}))
            if data.get("saml2")
            else None
        )

        return cls(
            method=method,
            password_hash=password_hash,
            session_secret=session_secret,
            session_expiry_hours=data.get("session_expiry_hours", 24),
            oidc=oidc_config,
            saml2=saml2_config,
        )


@dataclass
class WebConfig:
    theme: str = "dark"
    agent: WebAgentConfig = field(default_factory=WebAgentConfig)
    auth: WebAuthConfig = field(default_factory=WebAuthConfig)

    def __post_init__(self):
        if self.theme not in ("light", "dark", "system"):
            raise ValueError(
                f"Invalid theme '{self.theme}'. Must be 'light', 'dark', or 'system'."
            )

        if self.auth.method == WebAuthMethod.OIDC and not self.auth.oidc:
            raise ValueError("OIDC configuration required when auth method is 'oidc'")
        if self.auth.method == WebAuthMethod.SAML2 and not self.auth.saml2:
            raise ValueError("SAML2 configuration required when auth method is 'saml2'")
        if self.auth.method == WebAuthMethod.PASSWORD and not self.auth.password_hash:
            raise ValueError("password_hash required when auth method is 'password'")
        if self.auth.method != WebAuthMethod.NONE and not self.auth.session_secret:
            raise ValueError("session_secret required when authentication is enabled")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebConfig":
        return cls(
            theme=data.get("theme", "dark"),
            agent=WebAgentConfig.from_dict(data.get("agent", {})),
            auth=WebAuthConfig.from_dict(data.get("auth", {})),
        )


_last_loaded_config_path: Optional[Path] = None


def get_last_loaded_config_path() -> Optional[Path]:
    return _last_loaded_config_path


def save_config(config: ServerConfig, config_path: Optional[str] = None) -> Path:
    path: Optional[Path]
    if config_path:
        path = Path(config_path).expanduser()
    else:
        path = get_last_loaded_config_path()

    if path is None:
        raise RuntimeError("No config file path available for persistence")

    data: Dict[str, Any] = {
        "imap": {
            "host": config.imap.host,
            "port": config.imap.port,
            "username": config.imap.username,
            "password": config.imap.password or "",
            "use_ssl": config.imap.use_ssl,
        },
        "timezone": config.timezone,
        "working_hours": {
            "start": config.working_hours.start,
            "end": config.working_hours.end,
            "workdays": config.working_hours.workdays,
        },
        "identity": {
            "email": config.identity.email,
            "full_name": config.identity.full_name or "",
            "aliases": config.identity.aliases or [],
        },
        "vip_senders": config.vip_senders or [],
        "allowed_folders": config.allowed_folders or None,
        "bearer_auth": {
            "enabled": config.bearer_auth.enabled,
            "token": config.bearer_auth.token or "",
        },
        "database": {
            "backend": DatabaseBackend.POSTGRES.value,
            "postgres": {
                "host": config.database.postgres.host,
                "port": config.database.postgres.port,
                "database": config.database.postgres.database,
                "user": config.database.postgres.user,
                "password": config.database.postgres.password,
                "ssl_mode": config.database.postgres.ssl_mode,
            },
            "embeddings": {
                "enabled": config.database.embeddings.enabled,
                "provider": config.database.embeddings.provider,
                "fallback_provider": config.database.embeddings.fallback_provider,
                "endpoint": config.database.embeddings.endpoint,
                "model": config.database.embeddings.model,
                "api_key": config.database.embeddings.api_key,
                "dimensions": config.database.embeddings.dimensions,
                "batch_size": config.database.embeddings.batch_size,
                "max_chars": config.database.embeddings.max_chars,
                "input_type": config.database.embeddings.input_type,
                "truncate": config.database.embeddings.truncate,
                "gemini_api_key": config.database.embeddings.gemini_api_key,
                "gemini_model": config.database.embeddings.gemini_model,
                "task_type": config.database.embeddings.task_type,
            },
        },
    }

    if config.calendar:
        data["calendar"] = {
            "enabled": config.calendar.enabled,
            "verified_client": config.calendar.verified_client,
        }

    if config.web:
        data["web"] = {
            "theme": config.web.theme,
            "agent": {
                "base_url": config.web.agent.base_url,
                "api_format": config.web.agent.api_format.value,
                "model": config.web.agent.model,
                "token_limit": config.web.agent.token_limit,
                "api_key": config.web.agent.api_key,
            },
            "auth": {
                "method": config.web.auth.method.value,
                "password_hash": config.web.auth.password_hash,
                "session_secret": config.web.auth.session_secret,
                "session_expiry_hours": config.web.auth.session_expiry_hours,
                "oidc": (
                    {
                        "provider_url": config.web.auth.oidc.provider_url,
                        "client_id": config.web.auth.oidc.client_id,
                        "client_secret": config.web.auth.oidc.client_secret,
                        "scopes": config.web.auth.oidc.scopes,
                    }
                    if config.web.auth.oidc
                    else None
                ),
                "saml2": (
                    {
                        "idp_metadata_url": config.web.auth.saml2.idp_metadata_url,
                        "sp_entity_id": config.web.auth.saml2.sp_entity_id,
                        "sp_acs_url": config.web.auth.saml2.sp_acs_url,
                        "sp_sls_url": config.web.auth.saml2.sp_sls_url,
                        "certificate_path": config.web.auth.saml2.certificate_path,
                        "private_key_path": config.web.auth.saml2.private_key_path,
                    }
                    if config.web.auth.saml2
                    else None
                ),
            },
        }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    tmp_path.replace(path)

    global _last_loaded_config_path
    _last_loaded_config_path = path

    return path


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
        Path("config/config.yaml"),
        Path("config/config.yml"),
        Path("config.yaml"),
        Path("config.yml"),
        Path("~/.config/workspace-secretary/config.yaml"),
        Path("/etc/workspace-secretary/config.yaml"),
    ]

    # Load from specified path or try default locations
    config_data: Dict[str, Any] = {}
    global _last_loaded_config_path

    if config_path:
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
            logger.info(f"Loaded configuration from {config_path}")
            _last_loaded_config_path = Path(config_path).expanduser()
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {config_path}")
    else:
        for path in default_locations:
            expanded_path = path.expanduser()
            if expanded_path.exists():
                with open(expanded_path, "r") as f:
                    config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {expanded_path}")
                _last_loaded_config_path = expanded_path
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
