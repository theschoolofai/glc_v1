"""IMAP/SMTP live demo server — Zoho Mail.

Connects to a Zoho Mail INBOX over IMAP SSL, polls every 5 seconds for
new messages, runs each through the full adapter pipeline, and sends an
echo reply via SMTP STARTTLS.

Each pipeline step is logged so you can observe the adapter processing
a real email end-to-end:

    [BOOT ] Owner paired: you@example.com → owner_paired
    [BOOT ] IMAP/SMTP server started — polling every 5s
    [IMAP ] Connected to imap.zoho.in:993
    [IMAP ] Watching INBOX
    [FETCH] UID 1042 — From: alice@example.com — Subject: Hello
    [MSG  ] From=alice@example.com | trust=owner_paired | text='Hello bot!'
    [REPLY] {'status': 250, 'message_id': '<...@glc>'}

━━━ Zoho Mail setup (one-time) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Create a free account at https://www.zoho.com/mail/
  2. Enable IMAP/SMTP:
       Settings → Mail Accounts → IMAP/SMTP Access → Enable IMAP
  3. Generate an App Password (do NOT use your login password):
       https://accounts.zoho.in/home → Security → App Passwords → Add
  4. Copy values into a .env file (see .env.example in this directory)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Usage:
    # Set environment variables (or use a .env file with python-dotenv)
    export IMAP_HOST=imap.zoho.in
    export IMAP_PORT=993
    export IMAP_USER=bot@yourdomain.com
    export IMAP_PASSWORD=<zoho-app-password>
    export SMTP_HOST=smtp.zoho.in
    export SMTP_PORT=587
    export SMTP_USER=bot@yourdomain.com
    export SMTP_PASSWORD=<zoho-app-password>
    export BOT_FROM=bot@yourdomain.com
    export GLC_IMAP_OWNER=you@personal.com   # your personal email

    uv run python -m glc.channels.catalogue.imap.server
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from glc.channels.catalogue.imap.adapter import Adapter
from glc.channels.catalogue.imap.connection import ImapConnection
from glc.channels.envelope import ChannelReply
from glc.security.pairing import get_pairing_store

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = 5


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    # Read configuration from environment
    imap_host = _env("IMAP_HOST", "imap.zoho.in")
    imap_port = int(_env("IMAP_PORT", "993"))
    imap_user = _env("IMAP_USER")
    imap_password = _env("IMAP_PASSWORD")
    smtp_host = _env("SMTP_HOST", "smtp.zoho.in")
    smtp_port = int(_env("SMTP_PORT", "587"))
    smtp_user = _env("SMTP_USER")
    smtp_password = _env("SMTP_PASSWORD")
    bot_from = _env("BOT_FROM") or imap_user
    owner_email = _env("GLC_IMAP_OWNER")

    # Validate required variables
    missing = [k for k, v in {
        "IMAP_USER": imap_user,
        "IMAP_PASSWORD": imap_password,
        "GLC_IMAP_OWNER": owner_email,
    }.items() if not v]
    if missing:
        log.error("[BOOT ] Missing required environment variables: %s", ", ".join(missing))
        log.error("[BOOT ] See glc/channels/catalogue/imap/.env.example")
        sys.exit(1)

    # Register the owner in the pairing store (trust = owner_paired)
    store = get_pairing_store()
    store.force_pair_owner("imap", owner_email, user_handle="owner")
    log.info("[BOOT ] Owner paired: %s → owner_paired", owner_email)

    # Initialise the adapter (production mode — no mock)
    adapter = Adapter(
        config={
            "bot_from": bot_from,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "smtp_password": smtp_password,
        }
    )

    # Open the IMAP connection
    conn = ImapConnection(
        host=imap_host,
        port=imap_port,
        user=imap_user,
        password=imap_password,
    )
    conn.connect()
    log.info("[BOOT ] IMAP/SMTP server started — polling every %ss", POLL_INTERVAL_SECONDS)
    log.info("[BOOT ] Send an email to %s to test the pipeline", imap_user)

    # Poll loop
    while True:
        try:
            events = conn.fetch_unseen()
            for ev in events:
                uid = ev.get("uid", "?")
                raw = ev.get("raw", b"")
                # Quick header peek for logging (adapter re-parses below)
                import email as _email
                import email.policy as _policy
                _msg = _email.message_from_bytes(raw, policy=_policy.default) if raw else None
                _from = _msg.get("From", "?") if _msg else "?"
                _subj = _msg.get("Subject", "(no subject)") if _msg else "?"
                log.info("[FETCH] UID %s — From: %s — Subject: %s", uid, _from, _subj)

                msg = await adapter.on_message(ev)
                if msg is None:
                    log.info("[DROP ] UID %s — untrusted sender or unparseable", uid)
                    conn.mark_seen(int(uid) if isinstance(uid, int) else 0)
                    continue

                log.info(
                    "[MSG  ] From=%s | trust=%s | text=%r | attachments=%d",
                    msg.channel_user_id,
                    msg.trust_level,
                    (msg.text or "")[:80],
                    len(msg.attachments),
                )

                # Echo reply back to sender in the same thread
                reply = ChannelReply(
                    channel="imap",
                    channel_user_id=msg.channel_user_id,
                    text=f"[GLC Echo] {msg.text}",
                    thread_id=msg.thread_id,
                )
                result = await adapter.send(reply)
                log.info("[REPLY] %s", result)

                conn.mark_seen(int(uid) if isinstance(uid, int) else 0)

        except (ConnectionResetError, TimeoutError, OSError) as exc:
            log.warning("[IMAP ] Connection lost: %s — reconnecting…", exc)
            conn.reconnect()

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
