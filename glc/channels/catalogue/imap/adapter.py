"""Stub adapter for Generic IMAP/SMTP fallback.

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/imap_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

import email
import email.policy
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply

# Default bot sender address used in outbound SMTP messages.
_BOT_FROM = "bot@example.com"


class Adapter(ChannelAdapter):
    name = "imap"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # In tests, the config contains a "mock" key pointing to the ImapMock instance.
        self.mock = self.config.get("mock")
        self.is_public_channel = self.config.get("is_public_channel", False)

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        """Parse raw RFC 822 bytes into a ChannelMessage."""
        raw_bytes = raw.get("raw") if isinstance(raw, dict) else raw
        if not raw_bytes:
            return None

        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        sender = msg.get("From", "")

        # Text extraction
        text_content = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    text_content = part.get_content()
                    break
        else:
            text_content = msg.get_content()

        return ChannelMessage(
            channel=self.name,
            channel_user_id=sender,
            user_handle=sender,
            text=text_content,
            trust_level="owner_paired",  # Placeholder for Subtask 3
            arrived_at=datetime.now(timezone.utc)
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
        out["Subject"] = "Re: message"
        out.set_content(reply.text or "")

        payload: dict[str, Any] = {
            "from": bot_from,
            "to": reply.channel_user_id,
            "raw": out.as_bytes(),
        }

        # Dispatch — always return mock's result so rate-limit dicts propagate.
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        return payload
