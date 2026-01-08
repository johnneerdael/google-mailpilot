"""Tests for the config module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from workspace_secretary.config import (
    ImapConfig,
    ServerConfig,
    WorkingHoursConfig,
    OAuth2Config,
    OAuthMode,
    UserIdentityConfig,
    load_config,
)


class TestImapConfig:
    """Test cases for the ImapConfig class."""

    def test_init(self):
        """Test ImapConfig initialization."""
        config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="password",
        )

        assert config.host == "imap.example.com"
        assert config.port == 993
        assert config.username == "test@example.com"
        assert config.password == "password"
        assert config.use_ssl is True  # Default value

        # Test with custom SSL setting
        config = ImapConfig(
            host="imap.example.com",
            port=143,
            username="test@example.com",
            password="password",
            use_ssl=False,
        )
        assert config.use_ssl is False

    def test_from_dict(self):
        """Test creating ImapConfig from a dictionary."""
        data = {
            "host": "imap.example.com",
            "port": 993,
            "username": "test@example.com",
            "password": "password",
            "use_ssl": True,
        }

        config = ImapConfig.from_dict(data)
        assert config.host == "imap.example.com"
        assert config.port == 993
        assert config.username == "test@example.com"
        assert config.password == "password"
        assert config.use_ssl is True

        # Test with minimal data and defaults
        minimal_data = {
            "host": "imap.example.com",
            "username": "test@example.com",
            "password": "password",
        }

        config = ImapConfig.from_dict(minimal_data)
        assert config.host == "imap.example.com"
        assert config.port == 993  # Default with SSL
        assert config.username == "test@example.com"
        assert config.password == "password"
        assert config.use_ssl is True  # Default

        # Test with non-SSL port default
        non_ssl_data = {
            "host": "imap.example.com",
            "username": "test@example.com",
            "password": "password",
            "use_ssl": False,
        }

        config = ImapConfig.from_dict(non_ssl_data)
        assert config.port == 143  # Default non-SSL port

    def test_from_dict_with_env_password(self, monkeypatch):
        """Test creating ImapConfig with password from environment variable."""
        # Set environment variable
        monkeypatch.setenv("IMAP_PASSWORD", "env_password")

        data = {
            "host": "imap.example.com",
            "username": "test@example.com",
            # No password in dict
        }

        config = ImapConfig.from_dict(data)
        assert config.password == "env_password"

        # Test that dict password takes precedence
        data_with_password = {
            "host": "imap.example.com",
            "username": "test@example.com",
            "password": "dict_password",
        }

        config = ImapConfig.from_dict(data_with_password)
        assert config.password == "dict_password"

    def test_from_dict_missing_password(self, monkeypatch):
        """Test error when password is missing from both dict and environment."""
        # Ensure environment variable is not set
        monkeypatch.delenv("IMAP_PASSWORD", raising=False)

        data = {
            "host": "imap.example.com",
            "username": "test@example.com",
            # No password
        }

        with pytest.raises(ValueError) as excinfo:
            ImapConfig.from_dict(data)

        assert "IMAP password must be specified" in str(excinfo.value)

    def test_from_dict_missing_required_fields(self):
        """Test error when required fields are missing."""
        # Missing host
        with pytest.raises(KeyError):
            ImapConfig.from_dict(
                {"username": "test@example.com", "password": "password"}
            )

        # Missing username
        with pytest.raises(KeyError):
            ImapConfig.from_dict({"host": "imap.example.com", "password": "password"})


class TestServerConfig:
    """Test cases for the ServerConfig class."""

    def test_init(self):
        """Test ServerConfig initialization."""
        imap_config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="password",
        )

        working_hours = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )

        # Test without allowed folders
        server_config = ServerConfig(
            imap=imap_config,
            timezone="America/Los_Angeles",
            working_hours=working_hours,
            vip_senders=[],
            oauth_mode=OAuthMode.API,
            identity=UserIdentityConfig(email="test@example.com"),
        )
        assert server_config.imap == imap_config
        assert server_config.allowed_folders is None
        assert server_config.timezone == "America/Los_Angeles"
        assert server_config.working_hours == working_hours
        assert server_config.vip_senders == []

        # Test with allowed folders
        allowed_folders = ["INBOX", "Sent", "Archive"]
        server_config = ServerConfig(
            imap=imap_config,
            timezone="America/Los_Angeles",
            working_hours=working_hours,
            vip_senders=["boss@example.com"],
            allowed_folders=allowed_folders,
            oauth_mode=OAuthMode.API,
            identity=UserIdentityConfig(email="test@example.com"),
        )
        assert server_config.imap == imap_config
        assert server_config.allowed_folders == allowed_folders
        assert server_config.vip_senders == ["boss@example.com"]

    def test_from_dict(self, monkeypatch):
        """Test creating ServerConfig from a dictionary."""
        monkeypatch.setenv("OAUTH_MODE", "api")
        data = {
            "imap": {
                "host": "imap.example.com",
                "port": 993,
                "username": "test@example.com",
                "password": "password",
            },
            "timezone": "America/Los_Angeles",
            "working_hours": {
                "start": "09:00",
                "end": "17:00",
                "workdays": [1, 2, 3, 4, 5],
            },
            "vip_senders": ["boss@example.com"],
            "allowed_folders": ["INBOX", "Sent"],
        }

        config = ServerConfig.from_dict(data)
        assert config.imap.host == "imap.example.com"
        assert config.imap.port == 993
        assert config.imap.username == "test@example.com"
        assert config.imap.password == "password"
        assert config.allowed_folders == ["INBOX", "Sent"]
        assert config.timezone == "America/Los_Angeles"
        assert config.working_hours.start == "09:00"
        assert config.vip_senders == ["boss@example.com"]

        # Test with minimal data (no allowed_folders, empty vip_senders)
        minimal_data = {
            "imap": {
                "host": "imap.example.com",
                "username": "test@example.com",
                "password": "password",
            },
            "oauth_mode": "api",
            "timezone": "UTC",
            "working_hours": {
                "start": "09:00",
                "end": "17:00",
                "workdays": [1, 2, 3, 4, 5],
            },
            "vip_senders": [],
        }

        config = ServerConfig.from_dict(minimal_data)
        assert config.imap.host == "imap.example.com"
        assert config.allowed_folders is None

        # Test with empty dict (needs env password)
        monkeypatch.setenv("IMAP_PASSWORD", "env_password")
        with pytest.raises((KeyError, ValueError)):
            # Should fail because required fields are missing
            ServerConfig.from_dict({})


class TestLoadConfig:
    """Test cases for the load_config function."""

    def test_load_from_file(self, monkeypatch):
        """Test loading configuration from a file."""
        monkeypatch.setenv("OAUTH_MODE", "api")
        config_data = {
            "imap": {
                "host": "imap.example.com",
                "port": 993,
                "username": "test@example.com",
                "password": "password",
            },
            "timezone": "America/New_York",
            "working_hours": {
                "start": "09:00",
                "end": "17:00",
                "workdays": [1, 2, 3, 4, 5],
            },
            "vip_senders": ["vip@example.com"],
            "allowed_folders": ["INBOX", "Sent"],
        }

        # Create temporary config file
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w+") as temp_file:
            yaml.dump(config_data, temp_file)
            temp_file.flush()

            # Load config from the temp file
            config = load_config(temp_file.name)

            # Verify config data
            assert config.imap.host == "imap.example.com"
            assert config.imap.port == 993
            assert config.imap.username == "test@example.com"
            assert config.imap.password == "password"
            assert config.allowed_folders == ["INBOX", "Sent"]
            assert config.timezone == "America/New_York"
            assert config.working_hours.start == "09:00"
            assert config.vip_senders == ["vip@example.com"]

    def test_load_from_default_locations(self, monkeypatch, tmp_path):
        """Test loading configuration from default locations."""
        # Clear any environment variables that might affect the test
        for env_var in [
            "IMAP_HOST",
            "IMAP_PORT",
            "IMAP_USERNAME",
            "IMAP_PASSWORD",
            "IMAP_USE_SSL",
            "IMAP_ALLOWED_FOLDERS",
        ]:
            monkeypatch.delenv(env_var, raising=False)

        monkeypatch.setenv("OAUTH_MODE", "api")
        config_data = {
            "imap": {
                "host": "imap.example.com",
                "username": "test@example.com",
                "password": "password",
            },
            "timezone": "UTC",
            "working_hours": {
                "start": "09:00",
                "end": "17:00",
                "workdays": [1, 2, 3, 4, 5],
            },
            "vip_senders": [],
        }

        # Create a temporary config file in one of the default locations
        temp_dir = tmp_path / ".config" / "workspace-secretary"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / "config.yaml"

        with open(temp_file, "w") as f:
            yaml.dump(config_data, f)

        # Monkeypatch Path.expanduser to return our temp path
        original_expanduser = Path.expanduser

        def mock_expanduser(self):
            if str(self) == "~/.config/workspace-secretary/config.yaml":
                return temp_file
            return original_expanduser(self)

        monkeypatch.setattr(Path, "expanduser", mock_expanduser)

        # Monkeypatch to ensure no other config file is found
        def mock_exists(path):
            if path == temp_file:
                return True
            return False

        monkeypatch.setattr(Path, "exists", mock_exists)

        # Load config without specifying path (should find default)
        config = load_config()

        # Verify config data
        assert config.imap.host == "imap.example.com"
        assert config.imap.username == "test@example.com"
        assert config.imap.password == "password"

    def test_load_from_env_variables(self, monkeypatch):
        """Test loading configuration from environment variables."""
        # Set environment variables
        monkeypatch.setenv("OAUTH_MODE", "api")
        monkeypatch.setenv("IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("IMAP_PORT", "993")
        monkeypatch.setenv("IMAP_USERNAME", "test@example.com")
        monkeypatch.setenv("IMAP_PASSWORD", "env_password")
        monkeypatch.setenv("IMAP_USE_SSL", "true")
        monkeypatch.setenv("IMAP_ALLOWED_FOLDERS", "INBOX,Sent,Archive")

        # Mock open to raise FileNotFoundError
        original_open = open

        def mock_open(*args, **kwargs):
            if args[0] == "nonexistent_file.yaml":
                raise FileNotFoundError(f"No such file: {args[0]}")
            return original_open(*args, **kwargs)

        # Need to patch the built-in open function
        with patch("builtins.open", side_effect=mock_open):
            # Load config (will use env variables since file doesn't exist)
            config = load_config("nonexistent_file.yaml")

            # Verify config data
            assert config.imap.host == "imap.example.com"
            assert config.imap.port == 993
            assert config.imap.username == "test@example.com"
            assert config.imap.password == "env_password"
            assert config.imap.use_ssl is True
            assert config.allowed_folders == ["INBOX", "Sent", "Archive"]

            # Test with non-SSL setting
            monkeypatch.setenv("IMAP_USE_SSL", "false")
            config = load_config("nonexistent_file.yaml")
            assert config.imap.use_ssl is False

    def test_load_missing_required_env(self, monkeypatch):
        """Test error when required environment variables are missing."""
        # Ensure IMAP_HOST is not set
        monkeypatch.delenv("IMAP_HOST", raising=False)

        # Mock open to raise FileNotFoundError
        original_open = open

        def mock_open(*args, **kwargs):
            if args[0] == "nonexistent_file.yaml":
                raise FileNotFoundError(f"No such file: {args[0]}")
            return original_open(*args, **kwargs)

        # Need to patch the built-in open function
        with patch("builtins.open", side_effect=mock_open):
            with pytest.raises(ValueError) as excinfo:
                load_config("nonexistent_file.yaml")

            assert "IMAP_HOST environment variable not set" in str(excinfo.value)

    def test_invalid_config(self):
        """Test error when config is invalid."""
        # Create a config file with invalid data
        config_data = {
            "imap": {
                # Missing required host
                "username": "test@example.com",
                "password": "password",
            }
        }

        # Create temporary config file
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w+") as temp_file:
            yaml.dump(config_data, temp_file)
            temp_file.flush()

            # Load should raise ValueError
            with pytest.raises(ValueError) as excinfo:
                load_config(temp_file.name)

            # Error should mention missing required configuration
            assert "Missing required" in str(excinfo.value) or "timezone" in str(
                excinfo.value
            )


class TestWorkingHoursConfig:
    """Test cases for the WorkingHoursConfig class."""

    def test_valid_working_hours(self):
        """Test valid working hours configuration."""
        config = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )
        assert config.start == "09:00"
        assert config.end == "17:00"
        assert config.workdays == [1, 2, 3, 4, 5]

    def test_invalid_time_format(self):
        """Test invalid time format raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="9:00", end="17:00", workdays=[1, 2, 3, 4, 5])
        assert "must be in HH:MM format" in str(excinfo.value)

        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="09:00", end="5:00 PM", workdays=[1, 2, 3, 4, 5])
        assert "must be in HH:MM format" in str(excinfo.value)

    def test_start_after_end(self):
        """Test start time after end time raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="17:00", end="09:00", workdays=[1, 2, 3, 4, 5])
        assert "start time must be before end time" in str(excinfo.value)

    def test_invalid_workdays(self):
        """Test invalid workdays raise ValueError."""
        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="09:00", end="17:00", workdays=[0, 1, 2])
        assert "workdays must be between 1 and 7" in str(excinfo.value)

        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="09:00", end="17:00", workdays=[1, 2, 8])
        assert "workdays must be between 1 and 7" in str(excinfo.value)

    def test_empty_workdays(self):
        """Test empty workdays list raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            WorkingHoursConfig(start="09:00", end="17:00", workdays=[])
        assert "at least one workday" in str(excinfo.value)


class TestServerConfigWithNewFields:
    """Test cases for ServerConfig with new timezone, working_hours, and vip_senders fields."""

    def test_valid_server_config_with_new_fields(self):
        """Test valid ServerConfig with timezone, working_hours, and vip_senders."""
        imap_config = ImapConfig(
            host="imap.gmail.com",
            port=993,
            username="test@gmail.com",
            password="password",
        )

        working_hours = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )

        server_config = ServerConfig(
            imap=imap_config,
            timezone="America/Los_Angeles",
            working_hours=working_hours,
            vip_senders=["boss@example.com", "ceo@example.com"],
            oauth_mode=OAuthMode.API,
            identity=UserIdentityConfig(email="test@gmail.com"),
        )

        assert server_config.timezone == "America/Los_Angeles"
        assert server_config.working_hours == working_hours
        assert server_config.vip_senders == ["boss@example.com", "ceo@example.com"]

    def test_invalid_timezone(self):
        """Test invalid timezone raises ValueError."""
        imap_config = ImapConfig(
            host="imap.gmail.com",
            port=993,
            username="test@gmail.com",
            password="password",
        )

        working_hours = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )

        with pytest.raises(ValueError) as excinfo:
            ServerConfig(
                imap=imap_config,
                timezone="Invalid/Timezone",
                working_hours=working_hours,
                vip_senders=[],
                oauth_mode=OAuthMode.API,
                identity=UserIdentityConfig(email="test@gmail.com"),
            )
        assert "Invalid timezone" in str(excinfo.value)

    def test_vip_senders_normalization(self):
        """Test VIP senders are normalized to lowercase."""
        imap_config = ImapConfig(
            host="imap.gmail.com",
            port=993,
            username="test@gmail.com",
            password="password",
        )

        working_hours = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )

        server_config = ServerConfig(
            imap=imap_config,
            timezone="America/Los_Angeles",
            working_hours=working_hours,
            vip_senders=["Boss@Example.com", "CEO@Example.COM"],
            oauth_mode=OAuthMode.API,
            identity=UserIdentityConfig(email="test@gmail.com"),
        )

        assert server_config.vip_senders == ["boss@example.com", "ceo@example.com"]

    def test_missing_timezone(self):
        """Test missing timezone raises TypeError."""
        imap_config = ImapConfig(
            host="imap.gmail.com",
            port=993,
            username="test@gmail.com",
            password="password",
        )

        working_hours = WorkingHoursConfig(
            start="09:00", end="17:00", workdays=[1, 2, 3, 4, 5]
        )
        identity = UserIdentityConfig(email="test@gmail.com")

        # This should raise TypeError because timezone is a required field
        with pytest.raises(TypeError):
            ServerConfig(
                imap=imap_config,
                working_hours=working_hours,
                vip_senders=[],
                oauth_mode=OAuthMode.IMAP,
                identity=identity,
            )

    def test_missing_working_hours(self):
        """Test missing working_hours raises TypeError."""
        imap_config = ImapConfig(
            host="imap.gmail.com",
            port=993,
            username="test@gmail.com",
            password="password",
        )
        identity = UserIdentityConfig(email="test@gmail.com")

        # This should raise TypeError because working_hours is a required field
        with pytest.raises(TypeError):
            ServerConfig(
                imap=imap_config,
                timezone="America/Los_Angeles",
                vip_senders=[],
                oauth_mode=OAuthMode.IMAP,
                identity=identity,
            )

    def test_from_dict_with_new_fields(self, monkeypatch):
        """Test creating ServerConfig from dict with new fields."""
        monkeypatch.setenv("OAUTH_MODE", "api")
        data = {
            "imap": {
                "host": "imap.gmail.com",
                "username": "test@gmail.com",
                "password": "password",
            },
            "timezone": "America/New_York",
            "working_hours": {
                "start": "08:00",
                "end": "18:00",
                "workdays": [1, 2, 3, 4, 5],
            },
            "vip_senders": ["important@example.com", "vip@example.com"],
        }

        config = ServerConfig.from_dict(data)
        assert config.timezone == "America/New_York"
        assert config.working_hours.start == "08:00"
        assert config.working_hours.end == "18:00"
        assert config.working_hours.workdays == [1, 2, 3, 4, 5]
        assert config.vip_senders == ["important@example.com", "vip@example.com"]
