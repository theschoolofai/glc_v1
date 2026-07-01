"""Telegram Bot API channel adapter.

Group G16: Implement on_message and send against the mock-API fake and real Telegram Bot API.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

from .schemas import TelegramUpdate


class Adapter(ChannelAdapter):
    name = "telegram"

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        mock = self.config.get("mock")
        if mock is not None:
            if hasattr(mock, "pop_disconnect") and mock.pop_disconnect():
                return ChannelMessage(
                    channel=self.name,
                    channel_user_id="",
                    user_handle="",
                    text="disconnected",
                    trust_level="untrusted",
                    arrived_at=datetime.now(UTC),
                )

        update = TelegramUpdate.model_validate(raw)

        if update.message is None:
            return None

        message = update.message

        # Extract user information from "from" block, falling back to "chat" block
        sender = message.from_

        if sender is None:
            channel_user_id = str(message.chat.id)
            user_handle = message.chat.username or channel_user_id
        else:
            channel_user_id = str(sender.id)
            user_handle = sender.username or channel_user_id

        # Get handle/username
        if not user_handle:
            store = get_pairing_store()
            rec = store.lookup(self.name, channel_user_id)
            user_handle = rec.user_handle if rec else channel_user_id

        # Classify trust level
        trust_level = classify(self.name, channel_user_id)

        # Allowlist check for stranger in public channel
        if self.config.get("is_public_channel"):
            owners = [o.channel_user_id for o in get_pairing_store().owners(self.name)]
            is_allowed, _ = allowed(
                channel=self.name,
                channel_user_id=channel_user_id,
                owner_ids=owners,
                is_public_channel=True,
                was_mentioned=bool(self.config.get("was_mentioned", False)),
            )
            if not is_allowed:
                return None

        # Parse text and photo attachments
        text = message.text or message.caption

        attachments: list[Attachment] = []
        photo = message.photo
        if photo:
            # Find the largest photo size
            largest = max(
                photo,
                key=lambda p: p.file_size or (p.width * p.height),
            )

            file_id = largest.file_id
            if file_id:
                ref = ""
                if mock is not None:
                    try:
                        file_info = mock.get_file(file_id)
                        ref = file_info.get("file_path", "")
                    except Exception:
                        pass
                else:
                    token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if token:
                        try:
                            async with httpx.AsyncClient() as client:
                                resp = await client.get(
                                    f"https://api.telegram.org/bot{token}/getFile",
                                    params={"file_id": file_id},
                                    timeout=10.0,
                                )
                                if resp.status_code == 200:
                                    res_json = resp.json()
                                    if res_json.get("ok"):
                                        file_path = res_json["result"].get("file_path", "")
                                        ref = f"https://api.telegram.org/file/bot{token}/{file_path}"
                        except Exception:
                            pass

                if ref:
                    attachments.append(
                        Attachment(
                            kind="image",
                            ref=ref,
                            mime="image/jpeg",
                        )
                    )

        # Arrived at
        try:
            arrived_at = datetime.fromtimestamp(float(message.date or 0), UTC)
        except (ValueError, TypeError):
            arrived_at = datetime.now(UTC)

        metadata = {
            "is_public_channel": self.config.get("is_public_channel", False),
            "was_mentioned": bool(self.config.get("was_mentioned", False)),
        }

        return ChannelMessage(
            channel=self.name,
            channel_user_id=channel_user_id,
            user_handle=user_handle,
            text=text,
            attachments=attachments,
            trust_level=trust_level,
            arrived_at=arrived_at,
            metadata=metadata,
        )

    async def send(self, reply: ChannelReply) -> Any:
        # Build sendMessage payload
        payload = {
            "chat_id": int(reply.channel_user_id)
            if reply.channel_user_id.isdigit()
            else reply.channel_user_id,
            "text": reply.text or "",
        }

        if reply.thread_id:
            payload["message_thread_id"] = (
                int(reply.thread_id) if reply.thread_id.isdigit() else reply.thread_id
            )

        # In mock mode, call mock.send
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        # Real Telegram send logic
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            return payload

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
                timeout=10.0,
            )
            # Propagate 429
            if resp.status_code == 429:
                return {
                    "ok": False,
                    "error_code": 429,
                    "status": 429,
                    "description": "Too Many Requests",
                    "parameters": resp.json().get("parameters", {}),
                }
            return resp.json()
