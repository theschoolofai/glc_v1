"""Stub adapter for Generic Webhook (HTTP in/out).

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/webhook_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply

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
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/webhook/README.md."
        )

    async def send(self, reply: ChannelReply) -> Any:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/webhook/README.md."
        )
