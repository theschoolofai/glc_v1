"""Stub adapter for WhatsApp (Meta Cloud API or Twilio Sandbox).

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/whatsapp_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply


def verify_meta_signature(raw_body: bytes, headers: dict) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    sig_header = headers.get("X-Hub-Signature-256", "")
    if not secret or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.removeprefix("sha256="))


def parse_meta_payload(body: dict) -> dict[str, Any] | None:
    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        return None

    messages = value.get("messages")
    if not messages:
        return None

    msg = messages[0]
    contacts = value.get("contacts") or []
    profile_name = contacts[0].get("profile", {}).get("name") if contacts else None

    text: str | None = None
    if msg.get("type") == "text":
        text = msg.get("text", {}).get("body")

    return {
        "from_id": msg["from"],
        "text": text,
        "message_id": msg["id"],
        "timestamp": msg["timestamp"],
        "profile_name": profile_name,
    }


class Adapter(ChannelAdapter):
    name = "whatsapp"

    async def on_message(self, raw: Any) -> ChannelMessage:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/whatsapp/README.md."
        )

    async def send(self, reply: ChannelReply) -> Any:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/whatsapp/README.md."
        )
