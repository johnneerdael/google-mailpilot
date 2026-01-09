"""Command-line tool for setting up OAuth2 authentication for Gmail."""

import argparse
import json
import logging
import os
import secrets
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import yaml
from flask import Flask, redirect, request, url_for

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"

OAUTH_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
]

DEFAULT_CALLBACK_PORT = 8080
DEFAULT_CALLBACK_HOST = "localhost"
CALLBACK_PATH = "/oauth2callback"
SUCCESS_PATH = "/success"


def _notify_engine_to_enroll() -> None:
    """Notify running Engine to trigger enrollment after credentials are saved."""
    import requests

    engine_url = os.environ.get("ENGINE_URL", "http://localhost:8000")
    try:
        response = requests.post(f"{engine_url}/api/enroll", timeout=5)
        if response.status_code == 200:
            result = response.json()
            if result.get("enrolled"):
                print("✓ Engine notified - sync starting")
            else:
                print(f"Note: {result.get('message', 'Engine enrollment pending')}")
        else:
            print("Note: Engine will detect credentials within 5 seconds")
    except requests.exceptions.ConnectionError:
        print("Note: Engine not running - credentials saved for next startup")
    except Exception as e:
        logger.debug(f"Could not notify engine: {e}")
        print("Note: Engine will detect credentials within 5 seconds")


auth_tokens: Dict[str, Any] = {
    "access_token": None,
    "refresh_token": None,
    "token_expiry": None,
}


def load_client_credentials(credentials_file: str) -> Tuple[str, str]:
    """Load client credentials from the downloaded JSON file."""
    if not credentials_file:
        raise ValueError("No credentials file specified")

    credentials_path = Path(credentials_file)
    if not credentials_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {credentials_file}")

    with open(credentials_path) as f:
        try:
            credentials = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in credentials file: {credentials_file}. Error: {str(e)}"
            )

    if "installed" in credentials:
        client_config = credentials["installed"]
    elif "web" in credentials:
        client_config = credentials["web"]
    else:
        raise ValueError(f"Invalid credentials format in {credentials_file}")

    client_id = client_config.get("client_id")
    client_secret = client_config.get("client_secret")

    if not client_id or not client_secret:
        raise ValueError(f"Missing client_id or client_secret in {credentials_file}")

    return client_id, client_secret


def create_oauth_app() -> Flask:
    """Create the Flask app for OAuth2 callback handling."""
    app = Flask(__name__)

    @app.route(CALLBACK_PATH)
    def oauth2callback():
        code = request.args.get("code")
        if not code:
            return "Error: No authorization code received", 400

        client_id = app.config.get("client_id")
        client_secret = app.config.get("client_secret")

        try:
            import requests

            token_data = {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": app.config.get("redirect_uri"),
                "grant_type": "authorization_code",
            }

            response = requests.post(GMAIL_TOKEN_URL, data=token_data)
            response.raise_for_status()

            tokens = response.json()

            auth_tokens["access_token"] = tokens.get("access_token")
            auth_tokens["refresh_token"] = tokens.get("refresh_token")
            auth_tokens["token_expiry"] = int(time.time()) + tokens.get(
                "expires_in", 3600
            )

            logger.info("Successfully obtained OAuth2 tokens")

            return redirect(url_for("success"))

        except Exception as e:
            logger.error(f"Error exchanging authorization code: {e}")
            return f"Error: Failed to exchange authorization code: {e}", 500

    @app.route(SUCCESS_PATH)
    def success():
        return """
        <html>
        <head>
            <title>Authentication Successful</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    margin: 30px;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }
                .success {
                    background-color: #d4edda;
                    color: #155724;
                    padding: 15px;
                    border-radius: 4px;
                    margin: 20px 0;
                }
            </style>
        </head>
        <body>
            <h1>Authentication Successful!</h1>
            <div class="success">
                <p>You have successfully authenticated with Gmail.</p>
                <p>You may now close this browser window and return to the application.</p>
            </div>
        </body>
        </html>
        """

    return app


def _run_manual_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    auth_url: str,
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Manual OAuth flow where user pastes the redirect URL."""
    import requests

    print("\n" + "=" * 60)
    print("MANUAL AUTHENTICATION MODE")
    print("=" * 60)
    print("\n1. Open this URL in your browser:\n")
    print(auth_url)
    print("\n2. Complete the authentication in your browser.")
    print("\n3. You will be redirected to a URL that may not load.")
    print("   Copy the ENTIRE URL from your browser's address bar.")
    print(
        "   It will look like: http://localhost:8080/oauth2callback?code=...&state=..."
    )
    print("\n" + "-" * 60)

    redirect_response = input("\nPaste the full redirect URL here: ").strip()

    if not redirect_response:
        print("Error: No URL provided.")
        return None, None, None

    try:
        parsed = urlparse(redirect_response)
        query_params = parse_qs(parsed.query)

        code = query_params.get("code", [None])[0]
        if not code:
            print("Error: No authorization code found in URL.")
            print("Make sure you copied the entire URL including the ?code=... part.")
            return None, None, None

        token_data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        response = requests.post(GMAIL_TOKEN_URL, data=token_data)
        response.raise_for_status()

        tokens = response.json()

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        token_expiry = int(time.time()) + tokens.get("expires_in", 3600)

        print("\n✓ Authentication successful!")
        return access_token, refresh_token, token_expiry

    except Exception as e:
        logger.error(f"Error in manual OAuth flow: {e}")
        print(f"\nError: {e}")
        return None, None, None


def _run_server_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    auth_url: str,
    port: int,
    host: str,
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Server-based OAuth flow with local callback server."""
    app = create_oauth_app()

    app.config.update(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )

    auth_tokens["access_token"] = None
    auth_tokens["refresh_token"] = None
    auth_tokens["token_expiry"] = None

    print(f"\nOpening browser for Gmail authentication...")
    webbrowser.open(auth_url)

    print(f"\nWaiting for authentication at http://{host}:{port}{CALLBACK_PATH}")
    print(
        "\nIf the browser doesn't open or callback fails, restart with --manual flag."
    )

    import threading

    server_should_stop = threading.Event()

    def run_server():
        from werkzeug.serving import make_server

        server = make_server(host, port, app, threaded=True)
        server.timeout = 0.5

        while not server_should_stop.is_set():
            server.handle_request()

    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()

    try:
        max_wait_time = 5 * 60
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            if auth_tokens["access_token"] is not None:
                break
            time.sleep(1)

        if auth_tokens["access_token"] is None:
            print("\nAuthentication timed out. Please try again.")
            print(
                "Tip: If running in Docker or the callback isn't working, use --manual flag."
            )
            return None, None, None

    finally:
        server_should_stop.set()
        server_thread.join(timeout=5)

    return (
        auth_tokens["access_token"],
        auth_tokens["refresh_token"],
        auth_tokens["token_expiry"],
    )


def run_oauth_flow(
    client_id: str,
    client_secret: str,
    port: int = DEFAULT_CALLBACK_PORT,
    host: str = DEFAULT_CALLBACK_HOST,
    manual_mode: bool = False,
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Run the OAuth2 flow to obtain tokens."""
    redirect_uri = f"http://{host}:{port}{CALLBACK_PATH}"

    state = secrets.token_urlsafe(16)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    }
    auth_url = f"{GMAIL_AUTH_URL}?{urlencode(auth_params)}"

    if manual_mode:
        return _run_manual_flow(client_id, client_secret, redirect_uri, auth_url)
    else:
        return _run_server_flow(
            client_id, client_secret, redirect_uri, auth_url, port, host
        )


def setup_gmail_oauth2(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    credentials_file: Optional[str] = None,
    config_path: Optional[str] = None,
    config_output: Optional[str] = None,
    manual_mode: bool = True,
) -> Dict[str, Any]:
    """Set up OAuth2 authentication for Gmail."""
    if credentials_file and not (client_id and client_secret):
        try:
            logger.info(f"Loading credentials from {credentials_file}")
            client_id, client_secret = load_client_credentials(credentials_file)
            logger.info("Successfully loaded credentials from file")
        except Exception as e:
            logger.error(f"Failed to load credentials from file: {e}")
            sys.exit(1)

    if not client_id or not client_secret:
        logger.error("Client ID and Client Secret are required")
        print("\nYou must provide either:")
        print("  1. Client ID and Client Secret directly, or")
        print(
            "  2. Path to the credentials JSON file downloaded from Google Cloud Console"
        )
        sys.exit(1)

    print("\nStarting OAuth2 authentication flow...")
    if manual_mode:
        print(
            "Using manual mode - you will need to paste the redirect URL after authorization.\n"
        )
    else:
        print("Using automatic mode - a browser window will open for authorization.\n")

    try:
        access_token, refresh_token, token_expiry = run_oauth_flow(
            client_id=client_id,
            client_secret=client_secret,
            manual_mode=manual_mode,
        )
        if not refresh_token:
            logger.error("Failed to obtain refresh token")
            sys.exit(1)
        logger.info("Successfully obtained tokens")
    except Exception as e:
        logger.error(f"Failed to obtain tokens: {e}")
        sys.exit(1)

    oauth2_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "token_expiry": token_expiry,
    }

    config_data: Dict[str, Any] = {}
    if config_path:
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, "r") as f:
                config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded existing configuration from {config_path}")

    if "imap" not in config_data:
        config_data["imap"] = {}

    config_data["imap"]["oauth2"] = oauth2_data

    if config_output:
        output_file = Path(config_output)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)
            logger.info(f"Saved updated configuration to {config_output}")

    token_output_path = Path("/app/config/token.json")
    token_output_path.parent.mkdir(parents=True, exist_ok=True)

    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
    }
    with open(token_output_path, "w") as f:
        json.dump(token_data, f, indent=2)
        logger.info(f"Saved tokens to {token_output_path}")

    _notify_engine_to_enroll()

    print("\n" + "=" * 60)
    print("OAuth2 Setup Complete!")
    print("=" * 60)
    print("\nYour credentials have been saved. You can now start the server.")
    print("\nEnvironment variables (alternative to config file):")
    print(f"  GMAIL_CLIENT_ID={client_id}")
    print(f"  GMAIL_CLIENT_SECRET={client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN={oauth2_data['refresh_token']}")

    return config_data


def main() -> None:
    """Run the OAuth2 setup tool."""
    parser = argparse.ArgumentParser(
        description="Set up OAuth2 authentication for Gmail"
    )
    parser.add_argument(
        "--client-id",
        help="Google API client ID (optional if credentials file is provided)",
        default=os.environ.get("GMAIL_CLIENT_ID"),
    )
    parser.add_argument(
        "--client-secret",
        help="Google API client secret (optional if credentials file is provided). Use = syntax if secret starts with hyphen: --client-secret=-xyz",
        default=os.environ.get("GMAIL_CLIENT_SECRET"),
    )
    parser.add_argument(
        "--credentials-file",
        help="Path to the OAuth2 client credentials JSON file downloaded from Google Cloud Console",
    )
    parser.add_argument(
        "--config",
        help="Path to existing config file to update",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="Path to save the updated config file (default: don't write config)",
        default=None,
    )

    parser.add_argument(
        "--manual",
        action="store_true",
        default=True,
        help="Use manual OAuth flow (paste redirect URL). This is the default.",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use automatic browser-based OAuth flow (runs local server)",
    )

    args = parser.parse_args()

    manual_mode = not args.browser

    setup_gmail_oauth2(
        client_id=args.client_id,
        client_secret=args.client_secret,
        credentials_file=args.credentials_file,
        config_path=args.config,
        config_output=args.output,
        manual_mode=manual_mode,
    )


if __name__ == "__main__":
    main()
