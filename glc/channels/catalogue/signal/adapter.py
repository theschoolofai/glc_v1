"""Stub adapter for Signal via signal-cli.

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/signal_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify
from glc.channels.catalogue.signal.schemas import SendParams, SignalSendRequest


class Adapter(ChannelAdapter):
    name = "signal"

    async def on_message(self, raw: Any) -> ChannelMessage:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/signal/README.md."
        )
    async def send(self, reply: ChannelReply) -> Any:
        params = SendParams(
            message=reply.text or "",
            recipient=reply.channel_user_id if not reply.thread_id else None,
            group_id=reply.thread_id if reply.thread_id else None
        )

        request = SignalSendRequest(
            id=uuid.uuid4().hex,
            params=params
        )

        payload = request.model_dump(by_alias=True, exclude_none=True)

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        return payload
