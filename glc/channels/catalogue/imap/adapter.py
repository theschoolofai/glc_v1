"""IMAP/SMTP channel adapter — thin orchestrator.

Architecture
------------
This file is a pure orchestrator. All protocol logic lives in the
single-responsibility modules beside it:

  mime_parser.py  — pure MIME walker (text/plain, all attachment types)
  artifacts.py    — ephemeral attachment store (SHA256, TTL, path-guard)
  uid_tracker.py  — SQLite UID deduplication (no reprocessing on restart)
  smtp_sender.py  — stateless SMTP STARTTLS sender
  connection.py   — IMAP session manager (IDLE, exponential reconnect)
  server.py       — live demo (Zoho Mail poll loop)

Inbound pipeline  on_message(raw) → ChannelMessage | None
─────────────────────────────────────────────────────────
  1. mime_parser.parse()        → ParsedEmail (text, attachments, headers)
  2. trust_level.classify()     → owner_paired | user_paired | untrusted
  3. Public-channel gate        → drop untrusted in public-channel mode
  4. _store_attachment()        → art:<sha> ref per MIME part
  5. uid_tracker.mark_seen()    → dedup on reconnect (live mode only)
  6. Build ChannelMessage        → typed envelope to agent runtime

Outbound pipeline  send(reply) → dict
─────────────────────────────────────
  1. _format_reply()            → RFC 5322 EmailMessage
                                   From / To / Subject (Re: <original>)
                                   Message-ID (uuid4)
                                   In-Reply-To + References (thread chain)
                                   Date
  2. mock.send() or payload     → dispatch bytes via SMTP mock / real SMTP
  3. SMTP 421 → status 429      → normalise back-pressure code
"""

from __future__ import annotations

import hashlib
import smtplib
import uuid
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Literal

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.imap.artifacts import ArtifactStore
from glc.channels.catalogue.imap.mime_parser import parse as _mime_parse
from glc.channels.catalogue.imap.smtp_sender import SmtpSender
from glc.channels.catalogue.imap.uid_tracker import UidTracker
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.trust_level import classify

_BOT_FROM = "bot@example.com"

# Map MIME main-type to Attachment.kind
_KIND_MAP: dict[str, Literal["image", "audio", "video", "file", "location"]] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
}


class Adapter(ChannelAdapter):
    name = "imap"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.mock = self.config.get("mock")
        self.is_public_channel = self.config.get("is_public_channel", False)
        self._mailbox: str = self.config.get("mailbox", "INBOX")

        # Subject cache: Message-ID → Subject
        # Keyed by thread_id so each conversation thread gets the correct
        # "Re: <subject>" on reply, even when users have multiple open threads.
        self._subject_cache: dict[str, str] = {}

        # References cache: Message-ID → References chain
        # Used to build the RFC 5322 References thread header in replies.
        self._references_cache: dict[str, str] = {}

        # Real disk artifact store (production). In test mode the mock's
        # store_artifact() is used instead, so we skip the real store.
        self._artifact_store: ArtifactStore | None = None if self.mock is not None else ArtifactStore()

        # Real UID tracker (production). Not used in mock/test mode.
        self._uid_tracker: UidTracker | None = None if self.mock is not None else UidTracker()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _store_attachment(self, att: dict) -> Attachment:
        """Persist one MIME attachment blob and return a typed Attachment.

        In test mode: uses mock.store_artifact(sha, data).
        In production: uses the real ArtifactStore on disk.
        """
        data: bytes = att["data"]
        mime: str = att.get("mime", "application/octet-stream")
        filename: str = att.get("filename", "")

        if self.mock is not None:
            sha = hashlib.sha256(data).hexdigest()
            ref = self.mock.store_artifact(sha, data)
        else:
            assert self._artifact_store is not None
            ref = self._artifact_store.store(data, mime=mime, filename=filename)

        maintype = mime.split("/")[0]
        kind = _KIND_MAP.get(maintype, "file")
        return Attachment(kind=kind, mime=mime, ref=ref)

    def _format_reply(self, reply: ChannelReply) -> EmailMessage:
        """Build a complete RFC 5322 EmailMessage for the outbound reply.

        Thread-continuity headers (In-Reply-To, References) are set when
        the inbound Message-ID is available via the subject/references cache.
        A fresh Message-ID is generated per reply (uuid4).
        """
        out = EmailMessage()
        bot_from = self.config.get("bot_from", _BOT_FROM)
        out["From"] = bot_from
        out["To"] = reply.channel_user_id
        out["Message-ID"] = f"<{uuid.uuid4().hex}@glc>"
        out["Date"] = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

        # Subject: "Re: <original>" when thread_id resolves in cache
        if reply.thread_id and reply.thread_id in self._subject_cache:
            out["Subject"] = f"Re: {self._subject_cache[reply.thread_id]}"
        else:
            out["Subject"] = self.config.get("default_subject", "Message from bot")

        # Thread headers for MUA thread grouping (RFC 2822 §3.6.4)
        if reply.thread_id:
            out["In-Reply-To"] = reply.thread_id
            prior_refs = self._references_cache.get(reply.thread_id, "")
            ref_chain = f"{prior_refs} {reply.thread_id}".strip() if prior_refs else reply.thread_id
            out["References"] = ref_chain

        out.set_content(reply.text or "")
        return out

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        """Parse a raw IMAP FETCH envelope into a ChannelMessage.

        Accepts:
          - {"uid": int, "raw": bytes}   — standard IMAP FETCH dict
          - bare bytes                   — direct injection (tests)

        Returns None on empty input, unparseable MIME, or when an
        untrusted sender is silently dropped in public-channel mode.
        """
        # Transparent IDLE/disconnect handling: the IDLE connection can
        # drop without notice. Consuming the disconnect signal here lets
        # the server loop re-IDLE and process the next message normally.
        if self.mock is not None and self.mock.pop_disconnect():
            pass  # reconnect handled; fall through

        raw_bytes: bytes | None = raw.get("raw") if isinstance(raw, dict) else raw
        uid: int | None = raw.get("uid") if isinstance(raw, dict) else None

        if not raw_bytes:
            return None

        # 1. Parse MIME tree (pure, no I/O)
        parsed = _mime_parse(raw_bytes)
        if parsed is None:
            return None
        parsed.uid = uid

        # 2. Cache subject and references for reply thread continuity
        if parsed.message_id:
            if parsed.subject:
                self._subject_cache[parsed.message_id] = parsed.subject
            if parsed.references:
                self._references_cache[parsed.message_id] = parsed.references

        # 3. Trust classification using the bare sender address
        trust_level = classify(self.name, parsed.sender)

        # 4. Public-channel gate: silently drop untrusted senders
        if self.is_public_channel and trust_level == "untrusted":
            return None

        # 5. Store all attachment blobs → art:<sha> refs
        attachments: list[Attachment] = [self._store_attachment(att) for att in parsed.attachments]

        # 6. Mark UID as processed (live mode only — prevents reprocessing
        #    on reconnect without relying on server-side \Seen flag alone)
        if self._uid_tracker is not None and uid is not None:
            self._uid_tracker.mark_seen(self._mailbox, uid)

        return ChannelMessage(
            channel=self.name,
            channel_user_id=parsed.sender,
            user_handle=parsed.sender,
            text=parsed.text,
            trust_level=trust_level,
            arrived_at=datetime.now().astimezone(),
            attachments=attachments,
            thread_id=parsed.message_id,
        )

    async def send(self, reply: ChannelReply) -> Any:
        """Build an RFC 5322 message and dispatch via SMTP (or mock).

        Outbound wire shape:
            {"from": str, "to": str, "raw": bytes}

        `raw` contains valid From, To, Subject, Message-ID, Date,
        In-Reply-To, and References headers so SMTP relays and MUAs
        accept it and thread it correctly.

        SMTP 421 (service unavailable) is normalised to {"status": 429}.
        """
        out = self._format_reply(reply)
        bot_from = self.config.get("bot_from", _BOT_FROM)

        payload: dict[str, Any] = {
            "from": bot_from,
            "to": reply.channel_user_id,
            "raw": out.as_bytes(),
        }

        mock = self.config.get("mock")
        if mock is not None:
            try:
                result = await mock.send(payload)
            except smtplib.SMTPResponseException as exc:
                if exc.smtp_code == 421:
                    return {"status": 429, "error": str(exc)}
                raise

            # Normalise mock's numeric 421 → 429
            if isinstance(result, dict):
                status = result.get("status")
                if isinstance(status, str) and status.isdigit():
                    status = int(status)
                if status == 421:
                    return {**result, "status": 429}
            return result

        sender = SmtpSender(
            host=self.config.get("smtp_host", ""),
            port=int(self.config.get("smtp_port", 587)),
            user=self.config.get("smtp_user", ""),
            password=self.config.get("smtp_password", ""),
            bot_from=bot_from,
        )
        return sender.send(to=reply.channel_user_id, raw_bytes=out.as_bytes())
