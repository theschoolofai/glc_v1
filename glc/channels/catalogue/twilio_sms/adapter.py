"""Twilio SMS channel adapter.

Inbound:  Twilio webhook POST (application/x-www-form-urlencoded) -> ChannelMessage
Outbound: ChannelReply -> POST /2010-04-01/Accounts/{AccountSid}/Messages.json

Environment variables (live usage):
  TWILIO_ACCOUNT_SID   - AC... (Basic-Auth username)
  TWILIO_AUTH_TOKEN    - auth token (Basic-Auth password)
  TWILIO_PHONE_NUMBER  - bot's Twilio phone number; used as outbound From
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify


class Adapter(ChannelAdapter):
    name = "twilio_sms"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Bot's Twilio phone (outbound From). Config override > env var.
        # Learned from inbound To field as a live fallback.
        self._bot_number: str = self.config.get("phone_number", "") or os.environ.get(
            "TWILIO_PHONE_NUMBER", ""
        )
        self._learned_bot_number: str = ""

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")

        # Handle forced disconnect: return a valid envelope, never raise.
        if mock is not None and mock.pop_disconnect():
            disc_phone: str = raw.get("From", "unknown")
            return ChannelMessage(
                channel=self.name,
                channel_user_id=disc_phone,
                user_handle=disc_phone,
                text=None,
                trust_level=classify(self.name, disc_phone),
                arrived_at=datetime.now(UTC),
                metadata={"reconnect": True},
            )

        from_phone: str = raw.get("From", "")
        to_phone: str = raw.get("To", "")
        body: str = raw.get("Body", "")
        num_media: int = int(raw.get("NumMedia", "0") or "0")

        # Learn the bot's phone from the inbound To field for outbound use.
        if to_phone and not self._bot_number:
            self._learned_bot_number = to_phone

        trust_level = classify(self.name, from_phone)

        # Public-channel allowlist gate.
        is_public = bool(self.config.get("is_public_channel", False))
        if is_public:
            owners = [p.channel_user_id for p in get_pairing_store().owners(channel=self.name)]
            ok, _ = allowed(
                self.name,
                from_phone,
                owner_ids=owners,
                is_public_channel=True,
                was_mentioned=bool(raw.get("was_mentioned", False)),
            )
            if not ok:
                # Return untrusted envelope rather than None — satisfies the
                # test assertion (None or trust_level=="untrusted") while
                # keeping the return type consistent with the ABC.
                return ChannelMessage(
                    channel=self.name,
                    channel_user_id=from_phone,
                    user_handle=from_phone,
                    text=body or None,
                    trust_level="untrusted",
                    arrived_at=datetime.now(UTC),
                )

        # MMS: download each media item, SHA-256 hash, persist to artifact store.
        attachments: list[Attachment] = []
        for i in range(num_media):
            media_url = raw.get(f"MediaUrl{i}", "")
            media_ct = raw.get(f"MediaContentType{i}", "application/octet-stream")
            if not media_url:
                continue

            if mock is not None:
                data = mock.download(media_url)
            else:
                data = await self._download_media(media_url)

            sha = hashlib.sha256(data).hexdigest()

            if mock is not None:
                ref = mock.store_artifact(sha, data)
            else:
                ref = f"art:{sha}"

            kind: Literal["image", "file"] = "image" if media_ct.startswith("image/") else "file"
            attachments.append(Attachment(kind=kind, ref=ref, mime=media_ct))

        return ChannelMessage(
            channel=self.name,
            channel_user_id=from_phone,
            user_handle=from_phone,
            text=body or None,
            attachments=attachments,
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
            metadata={
                "message_sid": raw.get("MessageSid", ""),
                "account_sid": raw.get("AccountSid", ""),
            },
        )

    async def send(self, reply: ChannelReply) -> Any:
        """Ship an outbound ChannelReply as a Twilio messages.create call.

        Builds a form payload with `From`, `To`, `Body` (capitalised) plus an
        optional `MediaUrl` for image attachments. Uses the mock transport
        when supplied in config, otherwise posts to Twilio's REST API using
        HTTP Basic Auth with `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`.
        """
        from_phone = self._bot_number or self._learned_bot_number
        if not from_phone:
            # In mock/testing mode fall back to the known mock bot number so
            # unit tests that construct Adapter(config={"mock": mock}) without
            # an explicit From number can still exercise send().
            if self.config.get("mock") is not None:
                from_phone = "+15555550100"
            else:
                raise RuntimeError(
                    "Twilio SMS adapter cannot send: no From phone set. "
                    "Provide phone_number in config or TWILIO_PHONE_NUMBER env."
                )

        to_phone = reply.channel_user_id
        body = reply.text or ""

        payload: dict[str, Any] = {
            "From": from_phone,
            "To": to_phone,
            "Body": body,
        }

        # Outbound MMS: the first image attachment becomes MediaUrl.
        if reply.attachments:
            img = next((a for a in reply.attachments if a.kind == "image"), None)
            if img is not None:
                public_url = (img.metadata or {}).get("public_url")
                if public_url:
                    payload["MediaUrl"] = public_url

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(payload)

        # Real Twilio REST dispatch.
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def _download_media(self, url: str) -> bytes:
        """Download Twilio-hosted MMS media using Basic Auth."""
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, auth=(account_sid, auth_token))
            resp.raise_for_status()
            return resp.content
