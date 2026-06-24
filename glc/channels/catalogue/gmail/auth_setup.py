"""One-time OAuth setup for Gmail adapter.

Run this script once to authenticate and generate token.json:
    python -m glc.channels.catalogue.gmail.auth_setup

It will open a browser for Google OAuth consent. After approval,
token.json is saved in this directory with a refresh token so the
adapter can authenticate without user interaction going forward.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DIR = Path(__file__).parent
CREDENTIALS_FILE = DIR / "credentials.json"
TOKEN_FILE = DIR / "token.json"


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
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Missing {CREDENTIALS_FILE}. Download OAuth credentials from Google Cloud Console."
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

    topic_name = "projects/eagv3s11/topics/gmail-notifications"
    print(f"\nSetting up Gmail watch on topic: {topic_name}")
    setup_watch(creds, topic_name)
    print("\nDone! Gmail will now push notifications to your Pub/Sub topic.")
