"""Twilio SMS (and MMS) channel adapter.

US-7: parse_twilio_payload  — decode inbound form-encoded webhook into ChannelMessage.
US-8: build_twilio_send_payload — build outbound messages.create body (To/From/Body/MediaUrl).

Wire-format source:
  https://www.twilio.com/docs/messaging/guides/webhook-request
  https://www.twilio.com/docs/messaging/api/message-resource
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

# The phone number this bot sends FROM — set via env var in production.
_BOT_PHONE = os.environ.get("TWILIO_PHONE_NUMBER", "+15555550100")


class Adapter(ChannelAdapter):
    name = "twilio_sms"

    # ------------------------------------------------------------------
    # US-7: parse_twilio_payload
    # ------------------------------------------------------------------
    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        """Parse an inbound Twilio SMS/MMS webhook dict into a ChannelMessage.

        Twilio sends application/x-www-form-urlencoded data. The mock
        already delivers it as a plain dict with capitalised keys:
        From, To, Body, NumMedia, MediaUrl0, …
        """
        mock = self.config.get("mock")

        # Handle disconnect scenario cleanly — do not raise.
        if mock is not None and mock.pop_disconnect():
            return ChannelMessage(
                channel="twilio_sms",
                channel_user_id="unknown",
                user_handle="unknown",
                text=None,
                trust_level="untrusted",
                arrived_at=datetime.now(timezone.utc),
            )

        # raw is the parsed form dict (dict[str, str]).
        payload: dict[str, Any] = raw if isinstance(raw, dict) else {}

        # --- Extract sender ---
        from_phone: str = payload.get("From", "")
        if not from_phone:
            return None

        # Use the phone number as the stable channel_user_id.
        channel_user_id = from_phone

        # --- Extract text body ---
        text: str | None = payload.get("Body") or None

        # --- Handle MMS attachments (US-7 behavioural requirement) ---
        attachments: list[Attachment] = []
        num_media = int(payload.get("NumMedia", "0") or "0")

        if num_media > 0 and mock is not None:
            for i in range(num_media):
                media_url = payload.get(f"MediaUrl{i}")
                if not media_url:
                    continue
                # Download the media bytes via the mock (real adapter
                # would sign request with AccountSid credentials).
                media_bytes: bytes = mock.download(media_url)

                # Persist to artifact store keyed by SHA-256 of bytes.
                sha = hashlib.sha256(media_bytes).hexdigest()
                art_handle: str = mock.store_artifact(sha, media_bytes)

                content_type: str = payload.get(f"MediaContentType{i}", "image/jpeg")
                kind = "image" if content_type.startswith("image/") else "file"
                attachments.append(
                    Attachment(
                        kind=kind,
                        ref=art_handle,
                        mime=content_type,
                    )
                )

        # --- Trust level ---
        trust_level = classify("twilio_sms", channel_user_id)

        # --- Allowlist check for public channels ---
        if self.config.get("is_public_channel", False):
            owners = [p.channel_user_id for p in get_pairing_store().owners("twilio_sms")]
            ok, _ = allowed(
                "twilio_sms",
                channel_user_id,
                owner_ids=owners,
                is_public_channel=True,
                was_mentioned=False,
            )
            if not ok:
                return None

        return ChannelMessage(
            channel="twilio_sms",
            channel_user_id=channel_user_id,
            user_handle=channel_user_id,  # Twilio has no display name in the webhook
            text=text,
            attachments=attachments,
            trust_level=trust_level,
            arrived_at=datetime.now(timezone.utc),
            metadata={
                "message_sid": payload.get("MessageSid", ""),
                "account_sid": payload.get("AccountSid", ""),
            },
        )

    # ------------------------------------------------------------------
    # US-8: build_twilio_send_payload
    # ------------------------------------------------------------------
    async def send(self, reply: ChannelReply) -> Any:
        """Build and dispatch a Twilio messages.create payload.

        Twilio requires capitalised field names: From, To, Body.
        Outbound MMS adds MediaUrl (or MediaUrl0) from attachment metadata.
        Rate-limited sends return the raw 429 / code-20429 dict from the mock.
        """
        bot_phone = self.config.get("from_phone") or _BOT_PHONE

        # --- Core fields (US-8) ---
        body: dict[str, Any] = {
            "To": reply.channel_user_id,
            "From": bot_phone,
            "Body": reply.text or "",
        }

        # --- Optional MMS: attach public URL from first image attachment ---
        for att in reply.attachments or []:
            if att.kind == "image":
                public_url = att.metadata.get("public_url") or att.ref
                body["MediaUrl"] = public_url
                break  # Twilio supports multiple but one is enough for now

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(body)

        # --- Real Twilio REST call (production path) ---
        import httpx  # lazy import — not needed in test runs

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                data=body,
                auth=(account_sid, auth_token),
            )
            try:
                result = response.json()
            except Exception:
                result = {}
            if "status" not in result:
                result["status"] = response.status_code
            return result
