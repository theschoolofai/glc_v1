"""Adapter for Generic Webhook (HTTP in/out).

Implemented on_message and send against the mock-API
fake in tests/channels/mocks/webhook_mock.py.
"""

from __future__ import annotations

import hmac
import os
import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

import httpx

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.webhook.schemas import WebhookInbound
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

# Stripe-style webhooks reject bodies older than five minutes (replay window).
REPLAY_WINDOW_SECONDS = 300


class Adapter(ChannelAdapter):
    name = "webhook"

    def _verify(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """True only if the signature is valid AND the timestamp is fresh."""
        secret = os.getenv("WEBHOOK_SHARED_SECRET")
        if not secret:
            return False
        sig = next(
            (v for k, v in headers.items() if k.lower() == "x-webhook-signature"),
            None,
        )
        if not sig:
            return False
        fields = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
        ts, received = fields.get("t"), fields.get("v1")
        if not ts or not received or not ts.isdigit():
            return False
        if abs(time.time() - int(ts)) > REPLAY_WINDOW_SECONDS:
            return False
        signed = f"{ts}.{raw_body.decode('utf-8', 'replace')}".encode()
        expected = hmac.new(secret.encode(), signed, sha256).hexdigest()
        return hmac.compare_digest(expected, received)

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")
        if mock is not None and hasattr(mock, "pop_disconnect") and mock.pop_disconnect():
            return cast(ChannelMessage, None)

        if not isinstance(raw, dict):
            return cast(ChannelMessage, None)

        raw_body = raw.get("raw_body")
        headers = raw.get("headers")
        if not isinstance(raw_body, bytes) or not isinstance(headers, dict):
            return cast(ChannelMessage, None)

        normalized_headers = {str(k): str(v) for k, v in headers.items()}
        if not self._verify(raw_body, normalized_headers):
            return cast(ChannelMessage, None)

        try:
            inbound = WebhookInbound.model_validate_json(raw_body)
        except Exception:
            return cast(ChannelMessage, None)

        channel = self.name
        trust_level = classify(channel, inbound.sender_id)
        is_public_channel = bool(self.config.get("is_public_channel", False))
        was_mentioned = bool(self.config.get("was_mentioned", False))

        owners = [rec.channel_user_id for rec in get_pairing_store().owners(channel=channel)]
        ok, _ = allowed(
            channel,
            inbound.sender_id,
            owner_ids=owners,
            is_public_channel=is_public_channel,
            was_mentioned=was_mentioned,
        )
        if is_public_channel and not ok:
            return cast(ChannelMessage, None)

        metadata = dict(inbound.metadata)
        metadata["is_public_channel"] = is_public_channel
        metadata["was_mentioned"] = was_mentioned

        return ChannelMessage(
            channel=channel,
            channel_user_id=inbound.sender_id,
            user_handle=inbound.sender_handle,
            text=inbound.text,
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
            metadata=metadata,
        )

    async def send(self, reply: ChannelReply) -> Any:
        payload = {
            "recipient_id": reply.channel_user_id,
            "text": reply.text,
        }

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        # Real outbound HTTPS client dispatch
        target_url = os.getenv("WEBHOOK_DEFAULT_TARGET_URL")

        if not target_url:
            return payload

        async with httpx.AsyncClient() as client:
            resp = await client.post(target_url, json=payload)
            try:
                return resp.json()
            except Exception:
                return {"status": resp.status_code, "text": resp.text}
