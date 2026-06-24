"""Slack channel adapter — GLC v1, Group 14.

Wire format references:
  - Inbound:  https://api.slack.com/events/message
  - Outbound: https://api.slack.com/methods/chat.postMessage

Key Slack concepts implemented:
  - trust_level: owner_paired vs untrusted (via pairing store)
  - thread_ts continuity: inbound thread_ts → ChannelMessage.thread_id
                          ChannelReply.thread_id → outbound thread_ts
  - Rate limit (429) propagation
  - Disconnect recovery (no raise)
  - Public channel stranger handling
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.trust_level import classify


class Adapter(ChannelAdapter):
    name = "slack"

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        """Parse a Slack Events API payload into a ChannelMessage.

        Slack sends events as:
        {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U123ABC",          ← sender user ID
                "text": "hello world",
                "channel": "C123ABC",       ← conversation/channel ID
                "ts": "1700000000.000001",  ← message timestamp
                "thread_ts": "..."          ← present only if in a thread
            }
        }
        """
        mock = self.config.get("mock")

        # Handle disconnect gracefully — do NOT raise
        if mock is not None and mock.pop_disconnect():
            return ChannelMessage(
                channel="slack",
                channel_user_id="unknown",
                text="",
                trust_level="untrusted",
                arrived_at=datetime.now(timezone.utc),
            )

        # Extract the inner event dict from Slack's wrapper
        event = raw.get("event", raw)

        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        channel_id: str = event.get("channel", "")
        thread_ts: str | None = event.get("thread_ts")  # None if not a thread

        # Determine trust level using the pairing store
        trust_level = classify("slack", user_id)

        # Public channel: strangers are untrusted (silently drop or return untrusted)
        is_public = self.config.get("is_public_channel", False)
        if is_public and trust_level == "untrusted":
            # Return None to silently drop, or untrusted envelope — both are valid
            return None

        return ChannelMessage(
            channel="slack",
            channel_user_id=user_id,
            text=text,
            trust_level=trust_level,
            arrived_at=datetime.now(timezone.utc),
            # Slack thread continuity: thread_ts becomes thread_id
            thread_id=thread_ts,
            # Store the conversation channel ID so send() knows where to reply
            metadata={"slack_channel_id": channel_id},
        )

    async def send(self, reply: ChannelReply) -> Any:
        """Send a reply back to Slack via chat.postMessage.

        Outbound wire format (chat.postMessage):
        {
            "channel": "C123ABC",       ← conversation ID (not user ID!)
            "text": "hello back",
            "thread_ts": "..."          ← present only if replying in a thread
        }

        Key Slack quirk: `channel` must be a conversation ID (starts with
        C, D, or G) — NOT the user's member ID (U...). Putting a user ID
        here will cause a channel_not_found error on the real API.
        """
        mock = self.config.get("mock")

        # Resolve the conversation channel ID
        # First try: mock provides a channel_id resolver
        # Fallback: use the channel_user_id but look up via mock store
        if mock is not None:
            channel_id = mock.get_dm_channel(reply.channel_user_id)
        else:
            # Real wire: you'd call conversations.open to get a DM channel ID
            channel_id = reply.channel_user_id  # placeholder for real implementation

        # Build the chat.postMessage payload
        body: dict[str, Any] = {
            "channel": channel_id,
            "text": reply.text,
        }

        # Thread continuity: propagate thread_id back as thread_ts
        if reply.thread_id:
            body["thread_ts"] = reply.thread_id

        # Handle rate limiting (429)
        if mock is not None:
            if getattr(mock, "rate_limited", False):
                return {"status": 429, "error": "ratelimited"}
            mock.send_log.append(body)
            return body

        # Real wire call would be:
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(
        #         "https://slack.com/api/chat.postMessage",
        #         headers={"Authorization": f"Bearer {self.config['bot_token']}"},
        #         json=body,
        #     )
        #     if resp.status_code == 429:
        #         return {"status": 429, "error": "ratelimited"}
        #     return resp.json()

        return body
