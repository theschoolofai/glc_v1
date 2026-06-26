"""LINE Messaging API adapter for the Session 11 channel slot."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.trust_level import classify


class Adapter(ChannelAdapter):
    name = "line"

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")
        pop_disconnect = getattr(mock, "pop_disconnect", None)
        if callable(pop_disconnect):
            pop_disconnect()

        event = raw["events"][0]
        source = event["source"]
        message = event["message"]
        user_id = source["userId"]
        reply_token = event.get("replyToken")
        set_reply_token = getattr(mock, "set_reply_token", None)
        if reply_token and callable(set_reply_token):
            set_reply_token(user_id, reply_token)

        trust_level = classify(self.name, user_id)
        if self.config.get("is_public_channel") and trust_level == "untrusted":
            allowed(self.name, user_id, is_public_channel=True)

        return ChannelMessage(
            channel=self.name,
            channel_user_id=user_id,
            user_handle=user_id,
            text=message.get("text"),
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
        )

    async def send(self, reply: ChannelReply) -> Any:
        mock = self.config["mock"]
        message = {"type": "text", "text": reply.text or ""}
        reply_token = mock.consume_reply_token(reply.channel_user_id)

        if reply_token:
            payload = {"replyToken": reply_token, "messages": [message]}
        else:
            payload = {"to": reply.channel_user_id, "messages": [message]}

        return await mock.send(payload)
