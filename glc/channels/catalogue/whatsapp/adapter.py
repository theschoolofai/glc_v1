"""WhatsApp adapter for Twilio Sandbox and Meta Cloud API."""

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


def parse_twilio_payload(payload: dict) -> dict[str, Any] | None:
    """US-7: Parse Twilio Sandbox webhook payload."""
    from_id = payload.get("WaId")
    if not from_id:
        return None

    text = payload.get("Body") if payload.get("NumMedia") == "0" else None

    return {
        "from_id": from_id,
        "text": text,
        "message_id": payload.get("MessageSid"),
        "timestamp": None,
        "profile_name": payload.get("ProfileName"),
    }


def build_twilio_send_payload(to_phone: str, bot_phone: str, text: str | None) -> dict[str, str]:
    """US-8: Build Twilio Sandbox outbound payload."""
    if not bot_phone.startswith("whatsapp:"):
        bot_phone = f"whatsapp:{bot_phone}"

    if not to_phone.startswith("whatsapp:"):
        to_phone = f"whatsapp:{to_phone}"

    return {
        "To": to_phone,
        "From": bot_phone,
        "Body": text or "",
    }


def build_meta_send_payload(reply: ChannelReply) -> dict[str, Any]:
    if not reply.text:
        raise ValueError("build_meta_send_payload: reply.text must be a non-empty string")
    return {
        "messaging_product": "whatsapp",
        "to": reply.channel_user_id,
        "type": "text",
        "text": {"body": reply.text},
    }


class Adapter(ChannelAdapter):
    name = "whatsapp"

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/whatsapp/README.md."
        )

    async def send(self, reply: ChannelReply) -> Any:
        body = build_meta_send_payload(reply)
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(body)
        return body
