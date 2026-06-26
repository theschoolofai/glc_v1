"""Adapter for Slack Events API.

This module implements the inbound message parsing (`on_message`) and outbound
dispatch (`send`) logic for the Slack channel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify


class Adapter(ChannelAdapter):
    name = "slack"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config=config)
        self._user_to_channel: dict[str, str] = {}

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")
        if mock is not None:
            if hasattr(mock, "pop_disconnect") and mock.pop_disconnect():
                return ChannelMessage(
                    channel="slack",
                    channel_user_id="",
                    user_handle="",
                    text="disconnected",
                    trust_level="untrusted",
                    arrived_at=datetime.now(UTC),
                )

        event = raw.get("event") or {}
        user_id = event.get("user") or ""
        text = event.get("text")
        ts = event.get("ts") or ""
        thread_ts = event.get("thread_ts")
        channel_id = event.get("channel")

        if user_id and channel_id:
            self._user_to_channel[user_id] = channel_id

        # Determine trust level and handle
        trust_level = classify("slack", user_id)

        store = get_pairing_store()
        rec = store.lookup("slack", user_id)
        user_handle = rec.user_handle if rec else ""

        try:
            arrived_at = datetime.fromtimestamp(float(ts), UTC)
        except (ValueError, TypeError):
            arrived_at = datetime.now(UTC)

        metadata = {
            "is_public_channel": self.config.get("is_public_channel", False),
            "was_mentioned": True,  # Default to True or parse from event if required
        }

        return ChannelMessage(
            channel="slack",
            channel_user_id=user_id,
            user_handle=user_handle,
            text=text,
            attachments=[],
            voice_audio_ref=None,
            thread_id=thread_ts,
            trust_level=trust_level,
            arrived_at=arrived_at,
            metadata=metadata,
        )

    async def send(self, reply: ChannelReply) -> Any:
        channel_id = self._user_to_channel.get(reply.channel_user_id)
        if not channel_id:
            if reply.channel_user_id.startswith("U"):
                channel_id = reply.channel_user_id.replace("U", "D", 1)
            elif reply.channel_user_id.startswith("D") or reply.channel_user_id.startswith("C"):
                channel_id = reply.channel_user_id
            else:
                channel_id = f"D{reply.channel_user_id}"

        payload = {
            "channel": channel_id,
            "text": reply.text,
        }
        if reply.thread_id:
            payload["thread_ts"] = reply.thread_id

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        # Real client dispatch using httpx to post back to Slack
        import os

        import httpx

        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            return payload

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={
                    "Authorization": f"Bearer {slack_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            return resp.json()
