"""Live server for Gmail adapter — uses history polling (no ngrok needed).

Run:
    cd glc_v1
    uv run python -m glc.channels.catalogue.gmail.server

Polls Gmail via history.list for new messages. No public URL required.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import UTC, datetime
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from glc.channels.catalogue.gmail.adapter import Adapter
from glc.channels.catalogue.gmail.artifacts import cleanup_expired
from glc.channels.envelope import ChannelReply
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

DIR = Path(__file__).parent
TOKEN_FILE = DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

POLL_INTERVAL = 5

# ─── ANSI colors ─────────────────────────────────────────────────────────────
DIM = "\033[38;5;250m"  # light grey instead of dim
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[38;5;114m"
CYAN = "\033[38;5;81m"
YELLOW = "\033[38;5;221m"
MAGENTA = "\033[38;5;176m"
RED = "\033[38;5;203m"
BLUE = "\033[38;5;111m"
WHITE = "\033[97m"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def header_box(title: str, subtitle: str = "") -> str:
    width = 66
    lines = [
        f"\n{CYAN}{'━' * width}",
        f"┃  {BOLD}{WHITE}{title}{RESET}{CYAN}",
    ]
    if subtitle:
        lines.append(f"┃  {DIM}{subtitle}{RESET}{CYAN}")
    lines.append(f"{'━' * width}{RESET}\n")
    return "\n".join(lines)


def section(icon: str, label: str, detail: str = "") -> str:
    if detail:
        return f"  {icon}  {BOLD}{label}{RESET} {DIM}{detail}{RESET}"
    return f"  {icon}  {BOLD}{label}{RESET}"


def field(label: str, value: str, color: str = "") -> str:
    c = color or DIM
    return f"     {DIM}{label:12s}{RESET} {c}{value}{RESET}"


def divider() -> str:
    return f"  {DIM}{'─' * 58}{RESET}"


# ─── Gmail Client ────────────────────────────────────────────────────────────


def get_credentials() -> Credentials:
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


class LiveGmailClient:
    def __init__(self, service):
        self.service = service
        self.send_log: list[dict] = []
        self._disconnect_pending = False
        self._history_cache: dict[int, list[str]] = {}
        self._message_cache: dict[str, dict] = {}

    def history_list(self, start_history_id: int) -> dict:
        if start_history_id in self._history_cache:
            msg_ids = self._history_cache.pop(start_history_id)
            messages_added = []
            for m in msg_ids:
                cached = self._message_cache.get(m, {})
                tid = cached.get("threadId", m)
                messages_added.append({"message": {"id": m, "threadId": tid}})
            return {
                "history": [{"id": str(start_history_id), "messagesAdded": messages_added}],
                "historyId": str(start_history_id),
            }
        try:
            result = (
                self.service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=str(start_history_id),
                    historyTypes=["messageAdded"],
                )
                .execute()
            )
            return result
        except Exception:
            return {"history": []}

    def messages_get(self, message_id: str) -> dict:
        if message_id in self._message_cache:
            return self._message_cache.pop(message_id)
        return self.service.users().messages().get(userId="me", id=message_id, format="raw").execute()

    async def send(self, payload: dict) -> dict:
        result = self.service.users().messages().send(userId="me", body=payload).execute()
        self.send_log.append(payload)
        return result

    def pop_disconnect(self) -> bool:
        return False


# ─── Helpers ─────────────────────────────────────────────────────────────────


def extract_sender(raw_b64: str) -> str | None:
    padded = raw_b64 + "=" * (-len(raw_b64) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded.encode())
    parser = BytesParser(policy=email_policy.default)
    email_msg = parser.parsebytes(raw_bytes)
    return email_msg["From"]


def extract_email_only(addr: str) -> str:
    if "<" in addr and ">" in addr:
        return addr.split("<")[1].split(">")[0]
    return addr.strip()


def extract_subject(raw_b64: str) -> str | None:
    padded = raw_b64 + "=" * (-len(raw_b64) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded.encode())
    parser = BytesParser(policy=email_policy.default)
    email_msg = parser.parsebytes(raw_bytes)
    return email_msg["Subject"]


def format_bytes(n: int) -> str:
    if n > 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n > 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


# ─── Main Loop ───────────────────────────────────────────────────────────────


def main():
    import asyncio

    print(header_box("GLC v1 — Gmail Channel Adapter", "Group 6 | Session 11 | Live Demo"))

    print(section("[*]", "Authenticating..."))
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email_address = profile["emailAddress"]
    print(field("account", email_address, GREEN))
    print(field("messages", str(profile.get("messagesTotal", "?"))))
    print(field("threads", str(profile.get("threadsTotal", "?"))))
    print()

    OWNER_EMAIL = os.environ.get("GLC_GMAIL_OWNER")
    store = get_pairing_store()
    if OWNER_EMAIL:
        store.force_pair_owner("gmail", OWNER_EMAIL, user_handle="owner")
        print(section("[+]", "Owner Paired"))
        print(field("email", OWNER_EMAIL, GREEN))
        print(field("trust", "owner_paired", GREEN))
    else:
        print(section("[!]", "No owner paired"))
        print(field("set", "export GLC_GMAIL_OWNER=you@gmail.com", YELLOW))
        print(field("note", "All senders will be classified as untrusted", DIM))
    print()

    last_history_id = int(profile["historyId"])
    gmail_client = LiveGmailClient(service)
    adapter = Adapter(config={"client": gmail_client})

    processed_ids: set[str] = set()

    print(section("[~]", "Adapter Ready", f"polling every {POLL_INTERVAL}s"))
    print(field("send to", email_address, CYAN))
    print(field("stop", "Ctrl+C"))
    print(f"\n  {DIM}Waiting for incoming emails...{RESET}\n")

    while True:
        try:
            history = gmail_client.history_list(last_history_id)

            if "history" in history:
                for record in history["history"]:
                    messages_added = record.get("messagesAdded", [])
                    for added in messages_added:
                        msg_id = added["message"]["id"]

                        if msg_id in processed_ids:
                            continue
                        processed_ids.add(msg_id)

                        # Fetch
                        try:
                            full_msg = gmail_client.messages_get(msg_id)
                        except Exception:
                            continue

                        raw_b64 = full_msg.get("raw", "")
                        if not raw_b64:
                            continue

                        sender = extract_sender(raw_b64)
                        sender_bare = extract_email_only(sender) if sender else ""
                        subject = extract_subject(raw_b64)

                        if sender_bare == email_address:
                            continue

                        # ── Display incoming ──
                        size = full_msg.get("sizeEstimate", 0)
                        print(f"\n{CYAN}{'━' * 66}{RESET}")
                        print(f"  {BOLD}>> INCOMING EMAIL{RESET}  {DIM}{ts()}{RESET}")
                        print(f"{CYAN}{'━' * 66}{RESET}")
                        print()
                        print(field("from", sender_bare, WHITE))
                        print(field("subject", subject or "(no subject)", WHITE))
                        print(field("size", format_bytes(size)))
                        print(field("msg_id", msg_id, DIM))
                        print()

                        # ── Adapter processing ──
                        record_history_id = int(record.get("id", last_history_id))
                        gmail_client._history_cache[record_history_id] = [msg_id]
                        gmail_client._message_cache[msg_id] = full_msg

                        inner = json.dumps({"emailAddress": email_address, "historyId": record_history_id})
                        data = base64.b64encode(inner.encode()).decode()
                        envelope = {
                            "message": {
                                "data": data,
                                "messageId": f"poll-{msg_id}",
                                "publishTime": datetime.now(UTC).isoformat(),
                            },
                            "subscription": "projects/eagv3s11/subscriptions/gmail-poll",
                        }

                        # Show the raw Pub/Sub data
                        inner_json = json.dumps(
                            {"emailAddress": email_address, "historyId": record_history_id}
                        )
                        raw_b64_snippet = raw_b64[:60]

                        print(divider())
                        print(section("::", "ADAPTER PIPELINE — adapter.on_message()", ts()))
                        print()

                        # Step 1
                        print(f"  {BOLD}Step 1: _parse_pubsub_envelope(raw){RESET}")
                        print(
                            f'     {DIM}IN:{RESET}  message.data = "{base64.b64encode(inner_json.encode()).decode()[:50]}..."'
                        )
                        print(f"     {DIM}DO:{RESET}  base64.decode(message.data)")
                        print(
                            f'     {DIM}OUT:{RESET} {CYAN}{{"emailAddress": "{email_address}", "historyId": {record_history_id}}}{RESET}'
                        )
                        print()

                        # Step 2
                        print(f"  {BOLD}Step 2: _fetch_history(historyId={record_history_id}){RESET}")
                        print(f"     {DIM}IN:{RESET}  start_history_id = {record_history_id}")
                        print(
                            f"     {DIM}DO:{RESET}  GET gmail/v1/users/me/history?startHistoryId={record_history_id}&historyTypes=messageAdded"
                        )
                        print(
                            f'     {DIM}OUT:{RESET} {CYAN}{{"history": [{{"messagesAdded": [{{"message": {{"id": "{msg_id}", "threadId": "{full_msg.get("threadId")}"}}}}]}}]}}{RESET}'
                        )
                        print()

                        # Step 3
                        print(f'  {BOLD}Step 3: _fetch_message(id="{msg_id}"){RESET}')
                        print(f'     {DIM}IN:{RESET}  message_id = "{msg_id}"')
                        print(f"     {DIM}DO:{RESET}  GET gmail/v1/users/me/messages/{msg_id}?format=raw")
                        print(
                            f'     {DIM}OUT:{RESET} {CYAN}{{"id": "{msg_id}", "raw": "{raw_b64_snippet}...", "sizeEstimate": {size}}}{RESET}'
                        )
                        print()

                        # Step 4: Extract sender + resolve trust (before expensive parsing)
                        print(f"  {BOLD}Step 4: _extract_email(From header) + _resolve_trust_level(){RESET}")
                        print(f'     {DIM}IN:{RESET}  From: "{sender}"')
                        print(f'     {DIM}DO:{RESET}  Strip display name → "{sender_bare}"')
                        trust = classify("gmail", sender_bare)
                        trust_color = (
                            GREEN if trust == "owner_paired" else YELLOW if trust == "user_paired" else RED
                        )
                        print("         SELECT trust_level FROM pairings")
                        print(f"         WHERE channel='gmail' AND channel_user_id='{sender_bare}'")
                        print(f"     {DIM}OUT:{RESET} {trust_color}trust_level = {trust}{RESET}")
                        print()

                        msg = asyncio.run(adapter.on_message(envelope))

                        if msg is None:
                            print(f"  {RED}DROPPED — untrusted sender in public channel mode{RESET}")

                        else:
                            n_att = len(msg.attachments)

                            # Step 5
                            print(f"  {BOLD}Step 5: _extract_text_plain(email_msg){RESET}")
                            print(f"     {DIM}IN:{RESET}  MIME parts: [text/plain, text/html, ...]")
                            print(
                                f"     {DIM}DO:{RESET}  Walk MIME tree, pick first text/plain, discard text/html"
                            )
                            print(f'     {DIM}OUT:{RESET} {CYAN}"{(msg.text or "").strip()[:500]}"{RESET}')
                            print()

                            # Step 6
                            print(f"  {BOLD}Step 6: _extract_attachments(email_msg){RESET}")
                            print(f"     {DIM}IN:{RESET}  MIME tree ({format_bytes(size)})")
                            print(
                                f"     {DIM}DO:{RESET}  For each non-text part: sha256(bytes)[:16] → art:<hash>, write to disk"
                            )
                            if n_att:
                                for att in msg.attachments:
                                    fname = att.metadata.get("filename", "unnamed")
                                    fsize = format_bytes(att.metadata.get("size_bytes", 0))
                                    print(
                                        f'     {DIM}OUT:{RESET} {CYAN}Attachment(kind="{att.kind}", mime="{att.mime}", ref="{att.ref}", file="{fname}", size={fsize}){RESET}'
                                    )
                            else:
                                print(f"     {DIM}OUT:{RESET} {DIM}[]{RESET}")
                            print()

                            # Output envelope
                            print(divider())
                            print(section("<<", "OUTPUT: ChannelMessage"))
                            print()
                            print(f'     {DIM}channel         ={RESET} {WHITE}"gmail"{RESET}')
                            print(f'     {DIM}channel_user_id ={RESET} {WHITE}"{msg.channel_user_id}"{RESET}')
                            print(f"     {DIM}trust_level     ={RESET} {trust_color}{msg.trust_level}{RESET}")
                            print(f'     {DIM}thread_id       ={RESET} {WHITE}"{msg.thread_id}"{RESET}')
                            print(
                                f'     {DIM}text            ={RESET} {WHITE}"{(msg.text or "").strip()[:500]}"{RESET}'
                            )
                            print(
                                f"     {DIM}arrived_at      ={RESET} {WHITE}{msg.arrived_at.strftime('%H:%M:%S.%f')[:-3]}{RESET}"
                            )
                            if msg.attachments:
                                print(f"     {DIM}attachments     ={RESET} {WHITE}[{RESET}")
                                for att in msg.attachments:
                                    fname = att.metadata.get("filename", "unnamed")
                                    fsize = format_bytes(att.metadata.get("size_bytes", 0))
                                    print(
                                        f'       {CYAN}Attachment(kind="{att.kind}", mime="{att.mime}", ref="{att.ref}"){RESET}'
                                    )
                                    print(f'       {DIM}  filename="{fname}", size={fsize}{RESET}')
                                print(f"     {WHITE}]{RESET}")
                            else:
                                print(f"     {DIM}attachments     ={RESET} {WHITE}[]{RESET}")
                            print()

                            # Outbound
                            print(divider())
                            print(section("->", "OUTBOUND — adapter.send(ChannelReply)", ts()))
                            print()
                            reply_text = (
                                f"[GLC Echo] Got your message: {msg.text[:500] if msg.text else '(empty)'}"
                            )
                            reply = ChannelReply(
                                channel="gmail",
                                channel_user_id=msg.channel_user_id,
                                text=reply_text,
                                thread_id=msg.thread_id,
                            )
                            raw_mime = adapter._format_reply(reply)
                            print(f"  {BOLD}Step 1: _format_reply(ChannelReply){RESET}")
                            print(
                                f'     {DIM}IN:{RESET}  ChannelReply(to="{msg.channel_user_id}", text="{reply_text[:50]}...", thread="{msg.thread_id}")'
                            )
                            print(
                                f"     {DIM}DO:{RESET}  EmailMessage() → To/From/In-Reply-To/Subject → base64url(bytes)"
                            )
                            print(f'     {DIM}OUT:{RESET} {CYAN}"{raw_mime[:70]}..."{RESET}')
                            print()
                            print(f"  {BOLD}Step 2: Gmail API messages.send(){RESET}")
                            print(
                                f'     {DIM}IN:{RESET}  {{"raw": "{raw_mime[:40]}...", "threadId": "{msg.thread_id}"}}'
                            )
                            print(f"     {DIM}DO:{RESET}  POST gmail/v1/users/me/messages/send")
                            result = asyncio.run(adapter.send(reply))
                            print(
                                f'     {DIM}OUT:{RESET} {GREEN}{{"id": "{result.get("id")}", "threadId": "{result.get("threadId")}", "labelIds": ["SENT"]}}{RESET}'
                            )
                            if result.get("id"):
                                processed_ids.add(result["id"])

                        # Artifacts are NOT deleted here — the agent may still
                        # need them. They auto-expire after 5 minutes via
                        # cleanup_expired() which runs each poll cycle.
                        if msg and msg.attachments:
                            print(
                                f"  {DIM}Artifacts stored: {len(msg.attachments)} file(s) — TTL 5min{RESET}"
                            )

                        elapsed = (datetime.now(UTC) - msg.arrived_at).total_seconds() if msg else 0
                        print()
                        print(divider())
                        if elapsed:
                            print(f"  {GREEN}Done{RESET} in {WHITE}{elapsed:.1f}s{RESET}")
                        print(f"{CYAN}{'━' * 66}{RESET}\n")

            # Periodically clean expired artifacts
            cleanup_expired()

            # Update historyId
            if "historyId" in history:
                new_id = int(history["historyId"])
                if new_id > last_history_id:
                    last_history_id = new_id

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n  {DIM}Shutting down...{RESET}\n")
            break
        except Exception as e:
            print(f"\n  {RED}ERROR: {e}{RESET}\n")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
