"""One-time OAuth setup for Gmail adapter.

Run this script once to authenticate and generate token.json:
    python -m glc.channels.catalogue.gmail.auth_setup

It will open a browser for Google OAuth consent. After approval,
token.json is saved in this directory with a refresh token so the
adapter can authenticate without user interaction going forward.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DIR = Path(__file__).parent
CREDENTIALS_FILE = DIR / "credentials.json"
TOKEN_FILE = DIR / "token.json"

# Default Pub/Sub topic; override with GMAIL_PUBSUB_TOPIC.
DEFAULT_PUBSUB_TOPIC = "projects/prompt-wars-491605/topics/gmail-notifications"


def _client_config_from_env() -> dict | None:
    """Build an installed-app OAuth client config from the environment.

    Returns None when GMAIL_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_SECRET are
    not both set, so the caller can fall back to credentials.json.
    """
    client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def authenticate() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        print("Already authenticated. Token is valid.")
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
    else:
        env_config = _client_config_from_env()
        if env_config is not None:
            print("Opening browser for OAuth consent (credentials from env)...")
            flow = InstalledAppFlow.from_client_config(env_config, SCOPES)
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Set GMAIL_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_SECRET, or "
                    f"provide {CREDENTIALS_FILE} (OAuth credentials from Google Cloud Console)."
                )
            print("Opening browser for OAuth consent...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {TOKEN_FILE}")
    return creds


def setup_watch(creds: Credentials, topic: str) -> dict:
    """Call gmail.users.watch() to start Pub/Sub push notifications."""
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    result = (
        service.users()
        .watch(
            userId="me",
            body={
                "topicName": topic,
                "labelIds": ["INBOX"],
            },
        )
        .execute()
    )
    print(f"Watch registered: historyId={result['historyId']}, expiration={result['expiration']}")
    return result


if __name__ == "__main__":
    creds = authenticate()

    topic_name = os.getenv("GMAIL_PUBSUB_TOPIC", DEFAULT_PUBSUB_TOPIC)
    print(f"\nSetting up Gmail watch on topic: {topic_name}")
    setup_watch(creds, topic_name)
    print("\nDone! Gmail will now push notifications to your Pub/Sub topic.")
