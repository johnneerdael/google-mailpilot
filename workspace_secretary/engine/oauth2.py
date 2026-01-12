"""OAuth2 utilities for IMAP authentication."""

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import requests  # type: ignore
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from workspace_secretary.config import OAuth2Config

logger = logging.getLogger(__name__)

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
]


class OAuthValidationResult:
    def __init__(self, valid: bool, can_refresh: bool, error: Optional[str] = None):
        self.valid = valid
        self.can_refresh = can_refresh
        self.error = error

    @property
    def needs_auth(self) -> bool:
        return not self.valid and not self.can_refresh


def validate_oauth_config(
    oauth2_config: Optional[OAuth2Config],
) -> OAuthValidationResult:
    """Check if OAuth config has valid/refreshable tokens without making API calls."""
    if not oauth2_config:
        return OAuthValidationResult(False, False, "No OAuth2 config provided")

    if not oauth2_config.client_id or not oauth2_config.client_secret:
        return OAuthValidationResult(False, False, "Missing client_id or client_secret")

    if oauth2_config.refresh_token:
        return OAuthValidationResult(False, True, None)

    if oauth2_config.access_token:
        current_time = int(time.time())
        token_expiry = _parse_token_expiry(oauth2_config.token_expiry)
        if token_expiry > current_time + 300:
            return OAuthValidationResult(True, False, None)
        return OAuthValidationResult(
            False, False, "Access token expired, no refresh token"
        )

    return OAuthValidationResult(
        False, False, "No tokens available - authentication required"
    )


def _parse_token_expiry(token_expiry) -> int:
    if not token_expiry:
        return 0
    try:
        return int(token_expiry)
    except (ValueError, TypeError):
        try:
            from datetime import datetime

            expiry_dt = datetime.fromisoformat(str(token_expiry).replace("Z", "+00:00"))
            return int(expiry_dt.timestamp())
        except (ValueError, TypeError):
            return 0


def _save_refreshed_tokens(
    oauth2_config: OAuth2Config, access_token: str, expiry: int
) -> None:
    token_path = Path(os.environ.get("TOKEN_PATH", "config/token.json"))

    if not token_path.exists():
        logger.warning(f"Token file {token_path} does not exist, skipping persist")
        return

    try:
        with open(token_path, "r") as f:
            token_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read token file for update: {e}, skipping persist")
        return

    token_data["access_token"] = access_token
    token_data["token_expiry"] = expiry

    try:
        token_path_tmp = token_path.with_suffix(".tmp")
        with open(token_path_tmp, "w") as f:
            json.dump(token_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        token_path_tmp.replace(token_path)
        logger.info(f"Persisted refreshed tokens to {token_path}")
    except IOError as e:
        logger.error(f"Failed to persist refreshed tokens: {e}")


def get_access_token(oauth2_config: OAuth2Config) -> Tuple[str, int]:
    current_time = int(time.time())
    token_expiry = _parse_token_expiry(oauth2_config.token_expiry)

    if oauth2_config.access_token and token_expiry > current_time + 300:
        return oauth2_config.access_token, token_expiry

    if not oauth2_config.refresh_token:
        raise ValueError("Refresh token is required for OAuth2 authentication")

    logger.info("Refreshing Gmail access token")

    data = {
        "client_id": oauth2_config.client_id,
        "client_secret": oauth2_config.client_secret,
        "refresh_token": oauth2_config.refresh_token,
        "grant_type": "refresh_token",
    }

    response = requests.post(GMAIL_TOKEN_URI, data=data)
    if response.status_code != 200:
        logger.error(f"Failed to refresh token: {response.text}")
        raise ValueError(
            f"Failed to refresh token: {response.status_code} - {response.text}"
        )

    token_data = response.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 3600)
    expiry = int(time.time()) + expires_in

    oauth2_config.access_token = access_token
    oauth2_config.token_expiry = expiry
    _save_refreshed_tokens(oauth2_config, access_token, expiry)

    return access_token, expiry


def generate_oauth2_string(username: str, access_token: str) -> str:
    """Generate the SASL XOAUTH2 string for IMAP authentication.

    Args:
        username: Email address
        access_token: OAuth2 access token

    Returns:
        Base64-encoded XOAUTH2 string for IMAP authentication
    """
    auth_string = f"user={username}\1auth=Bearer {access_token}\1\1"
    return base64.b64encode(auth_string.encode()).decode()


def get_authorization_url(oauth2_config: OAuth2Config) -> str:
    """Generate the URL for the OAuth2 authorization flow.

    Args:
        oauth2_config: OAuth2 configuration

    Returns:
        URL to redirect the user to for authorization
    """
    params = {
        "client_id": oauth2_config.client_id,
        "redirect_uri": "http://localhost",
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GMAIL_AUTH_BASE_URL}?{query_string}"


def exchange_code_for_tokens(
    oauth2_config: OAuth2Config, code: str
) -> Tuple[str, str, int]:
    """Exchange authorization code for access and refresh tokens.

    Args:
        oauth2_config: OAuth2 configuration
        code: Authorization code from the redirect

    Returns:
        Tuple of (access_token, refresh_token, expiry_timestamp)

    Raises:
        ValueError: If unable to exchange the code
    """
    data = {
        "client_id": oauth2_config.client_id,
        "client_secret": oauth2_config.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": "http://localhost",
    }

    response = requests.post(GMAIL_TOKEN_URI, data=data)
    if response.status_code != 200:
        raise ValueError(
            f"Failed to exchange code: {response.status_code} - {response.text}"
        )

    token_data = response.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    expires_in = token_data.get("expires_in", 3600)  # Default to 1 hour
    expiry = int(time.time()) + expires_in

    return access_token, refresh_token, expiry
