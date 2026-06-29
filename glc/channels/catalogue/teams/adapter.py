"""Stub adapter for Microsoft Teams Bot Framework.

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/teams_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

from __future__ import annotations

from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply


class Adapter(ChannelAdapter):
    name = "teams"

    async def on_message(self, raw: Any) -> ChannelMessage:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/teams/README.md."
        )

    async def send(self, reply: ChannelReply) -> Any:
        raise NotImplementedError(
            "Group assignment: implement on_message and send. "
            "See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/teams/README.md."
        )
