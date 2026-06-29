"""Stub adapter for Generic IMAP/SMTP fallback.

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/imap_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

import email
import email.policy
import smtplib
import hashlib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply, Attachment

# Default bot sender address used in outbound SMTP messages.
_BOT_FROM = "bot@example.com"


class Adapter(ChannelAdapter):
    name = "imap"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # In tests, the config contains a "mock" key pointing to the ImapMock instance.
        self.mock = self.config.get("mock")
        self.is_public_channel = self.config.get("is_public_channel", False)
        # Maps thread_id (Message-ID header) -> original Subject so send()
        # can build "Re: <subject>" per-thread. Keyed by thread_id (not sender)
        # so users with multiple threads each get the correct reply subject.
        self._subject_cache: dict[str, str] = {}

    def _parse_pdf_attachments(self, msg) -> list[Attachment]:
        """Extract application/pdf parts, store them as artifacts, and return Attachment objects."""
        attachments: list[Attachment] = []
        for part in msg.iter_attachments():
            if part.get_content_type() == "application/pdf":
                payload = part.get_content()
                sha = hashlib.sha256(payload).hexdigest()
                # Use the mock's artifact store when running under tests
                mock = self.mock
                if mock is None:
                    raise RuntimeError("Artifact store not configured; provide a mock via Adapter(config={'mock': …})")
                ref = mock.store_artifact(sha, payload)
                attachments.append(
                    Attachment(
                        kind="file",
                        mime="application/pdf",
                        ref=ref,
                    )
                )
        return attachments

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        """Parse raw RFC 822 bytes into a ChannelMessage, including PDF attachments."""
        raw_bytes = raw.get("raw") if isinstance(raw, dict) else raw
        if not raw_bytes:
            return None

        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        sender = msg.get("From", "")

        # Cache subject keyed by Message-ID (thread_id) so multiple threads
        # from the same user each get the correct "Re: <subject>" on reply.
        thread_id = msg.get("Message-ID", "").strip() or None
        subject = msg.get("Subject", "")
        if thread_id and subject:
            self._subject_cache[thread_id] = subject

        # Text extraction
        text_content = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    text_content = part.get_content()
                    break
        else:
            text_content = msg.get_content()

        # PDF attachment extraction
        attachments = self._parse_pdf_attachments(msg)

        return ChannelMessage(
            channel=self.name,
            channel_user_id=sender,
            user_handle=sender,
            text=text_content,
            trust_level="owner_paired",  # Placeholder for Subtask 3
            arrived_at=datetime.now(timezone.utc),
            attachments=attachments,
            thread_id=thread_id,
        )

    async def send(self, reply: ChannelReply) -> Any:
        """Build an RFC 5322 message and dispatch it via the SMTP mock (or real relay).

        Outbound wire shape expected by ImapMock.send():
            {"from": <str>, "to": <str>, "raw": <bytes>}

        `raw` must contain valid From, To, and Subject headers so SMTP
        relays accept it.  The reply text is set as the plain-text body.
        """
        # Build the RFC 5322 message (EmailMessage uses policy.default = RFC 5322)
        out = EmailMessage()
        bot_from = self.config.get("bot_from", _BOT_FROM)
        out["From"] = bot_from
        out["To"] = reply.channel_user_id
        # For replies: look up the cached subject by thread_id.
        # For agent-initiated emails (no prior inbound): use config default_subject.
        if reply.thread_id and reply.thread_id in self._subject_cache:
            out["Subject"] = f"Re: {self._subject_cache[reply.thread_id]}"
        else:
            out["Subject"] = self.config.get("default_subject", "Message from bot")
        out.set_content(reply.text or "")

        payload: dict[str, Any] = {
            "from": bot_from,
            "to": reply.channel_user_id,
            "raw": out.as_bytes(),
        }

        # Dispatch — always return mock's result so rate-limit dicts propagate.
        mock = self.config.get("mock")
        if mock is not None:
            try:
                result = await mock.send(payload)
            except smtplib.SMTPResponseException as exc:
                if exc.smtp_code == 421:
                    return {"status": 429, "error": str(exc)}
                raise

            if isinstance(result, dict):
                status = result.get("status")
                if isinstance(status, str) and status.isdigit():
                    status = int(status)
                if status == 421:
                    return {**result, "status": 429}
            return result

        return payload
