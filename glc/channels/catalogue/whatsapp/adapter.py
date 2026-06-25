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
