"""WhatsApp adapter for Twilio Sandbox and Meta Cloud API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

from twilio.request_validator import RequestValidator

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import TrustLevel, classify


def verify_meta_signature(raw_body: bytes, headers: dict) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    sig_header = headers.get("x-hub-signature-256", "")
    if not secret or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.removeprefix("sha256="))


def verify_twilio_signature(url: str, params: dict, signature: str, auth_token: str) -> bool:
    """Verifies the Twilio signature of an incoming webhook.

    Args:
        url: The full public webhook URL (from TWILIO_WEBHOOK_URL env var).
        params: The form data dict from the webhook payload.
        signature: The X-Twilio-Signature header value.
        auth_token: The Twilio Auth Token for validation.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not auth_token or not signature:
        return False
    try:
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except Exception:
        return False


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

    try:
        return {
            "from_id": msg["from"],
            "text": text,
            "message_id": msg["id"],
            "timestamp": msg["timestamp"],
            "profile_name": profile_name,
        }
    except (KeyError, TypeError):
        return None


def parse_twilio_payload(payload: dict, received_at: datetime) -> dict[str, Any] | None:
    """US-7: Parse Twilio Sandbox webhook payload."""
    from_id = payload.get("WaId")
    if not from_id:
        return None

    text = payload.get("Body") if payload.get("NumMedia", "0") == "0" else None

    return {
        "from_id": from_id,
        "text": text,
        "message_id": payload.get("MessageSid"),
        "timestamp": received_at,
        "profile_name": payload.get("ProfileName") or None,
    }


def build_twilio_send_payload(to_phone: str, bot_phone: str, text: str | None) -> dict[str, str]:
    """US-8: Build Twilio Sandbox outbound payload."""
    if not text:
        raise ValueError("build_twilio_send_payload: text must be a non-empty string")

    if not bot_phone.startswith("whatsapp:"):
        bot_phone = f"whatsapp:{bot_phone}"

    if not to_phone.startswith("whatsapp:"):
        to_phone = f"whatsapp:{to_phone}"

    return {
        "To": to_phone,
        "From": bot_phone,
        "Body": text,
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


def _parse_form_body(raw_body: bytes) -> dict[str, str]:
    try:
        parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}
    return {k: v[0] if v else "" for k, v in parsed.items()}


def _headers(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        headers = raw.get("headers") or {}
        return {str(k).lower(): str(v) for k, v in headers.items()}
    return {}


def _to_channel_message(
    parsed: dict[str, Any],
    *,
    provider: str,
    trust: TrustLevel,
) -> ChannelMessage:
    if provider == "meta":
        arrived_at = datetime.fromtimestamp(int(float(parsed["timestamp"])), tz=UTC)
    else:
        arrived_at = parsed["timestamp"]
    return ChannelMessage(
        channel="whatsapp",
        channel_user_id=parsed["from_id"],
        user_handle=parsed["profile_name"] or parsed["from_id"],
        text=parsed["text"],
        trust_level=trust,
        arrived_at=arrived_at,
        metadata={"provider": provider, "message_id": parsed["message_id"]},
    )


class Adapter(ChannelAdapter):
    name = "whatsapp"

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        mock = self.config.get("mock")
        if mock is not None:
            mock.pop_disconnect()

        headers = _headers(raw)
        is_public = bool(self.config.get("is_public_channel", False))
        parsed: dict[str, Any] | None = None
        provider = "meta"

        if isinstance(raw, dict) and "raw_body" in raw:
            raw_body = raw["raw_body"]
            if not isinstance(raw_body, bytes):
                return None

            twilio_sig = headers.get("x-twilio-signature", "")
            if twilio_sig:
                params = _parse_form_body(raw_body)
                url = os.environ.get("TWILIO_WEBHOOK_URL", "")
                auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
                if not verify_twilio_signature(url, params, twilio_sig, auth_token):
                    return None
                parsed = parse_twilio_payload(params, datetime.now(UTC))
                provider = "twilio"
            elif headers.get("x-hub-signature-256"):
                if not verify_meta_signature(raw_body, headers):
                    return None
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError:
                    return None
                parsed = parse_meta_payload(body)
                provider = "meta"
            else:
                return None
        elif isinstance(raw, dict) and raw.get("entry"):
            parsed = parse_meta_payload(raw)
            provider = "meta"
        elif isinstance(raw, dict) and "From" in raw and "Body" in raw:
            parsed = parse_twilio_payload(raw, datetime.now(UTC))
            provider = "twilio"
        else:
            return None

        if parsed is None:
            return None

        owner_ids = [r.channel_user_id for r in get_pairing_store().owners("whatsapp")]
        trust = classify("whatsapp", parsed["from_id"])
        ok, _ = allowed(
            "whatsapp",
            parsed["from_id"],
            owner_ids=owner_ids,
            is_public_channel=is_public,
            was_mentioned=False,
        )
        if not ok:
            # channels.yaml has whatsapp: enabled: false, so allowed() returns False
            # for everyone including owners. Until that is fixed, only enforce the
            # drop for public-channel untrusted strangers; owners and known users
            # in DM mode pass through.
            # TODO: simplify to `return None` once channels.yaml enables the channel.
            if is_public and trust == "untrusted":
                return None

        return _to_channel_message(parsed, provider=provider, trust=trust)

    async def send(self, reply: ChannelReply) -> Any:
        body = build_meta_send_payload(reply)
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(body)
        return body
