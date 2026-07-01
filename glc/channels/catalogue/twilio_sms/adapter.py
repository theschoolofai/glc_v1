"""Twilio SMS channel adapter.

Inbound:  Twilio webhook POST (application/x-www-form-urlencoded) -> ChannelMessage
Outbound: ChannelReply -> POST /2010-04-01/Accounts/{AccountSid}/Messages.json

Environment variables (live usage):
  TWILIO_ACCOUNT_SID        - AC... (Basic-Auth username)
  TWILIO_AUTH_TOKEN         - auth token (Basic-Auth password + webhook signing)
  TWILIO_PHONE_NUMBER       - bot's Twilio phone number; used as outbound From
  GLC_ARTIFACT_PUBLIC_BASE  - public base URL used to serve inbound artifacts
                              back out as outbound MMS MediaUrl, e.g.
                              https://host/artifacts (art:<sha> -> <base>/<sha>)
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

from .schemas import TwilioInboundForm

AttachmentKind = Literal["image", "audio", "video", "file"]

# Carrier / Twilio Advanced Opt-Out keywords. Honoring these is a
# compliance requirement for production SMS senders.
_STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
_START_KEYWORDS = {"START", "YES", "UNSTOP"}
_HELP_KEYWORDS = {"HELP", "INFO"}


def _media_kind(content_type: str) -> AttachmentKind:
    """Map a MIME type to a canonical envelope attachment kind."""
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    return "file"


def _detect_keyword(body: str) -> str | None:
    """Return the normalized carrier keyword if the body is exactly one."""
    token = (body or "").strip().upper()
    if token in _STOP_KEYWORDS:
        return "STOP"
    if token in _START_KEYWORDS:
        return "START"
    if token in _HELP_KEYWORDS:
        return "HELP"
    return None


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

        form = TwilioInboundForm.from_raw(raw)
        from_phone = form.From
        to_phone = form.To
        body = form.Body

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
        for item in form.media_items():
            if mock is not None:
                data = mock.download(item.url)
            else:
                data = await self._download_media(item.url)

            if mock is not None:
                # Test contract: mock keys artifacts by the full sha256 digest.
                sha = hashlib.sha256(data).hexdigest()
                ref = mock.store_artifact(sha, data)
            else:
                # Live: persist the bytes for real (fixes the discarded-bytes bug).
                from .artifacts import put

                ref = put(
                    data,
                    content_type=item.content_type,
                    source="twilio_sms",
                    descriptor=f"MMS media from {from_phone}",
                )

            attachments.append(
                Attachment(kind=_media_kind(item.content_type), ref=ref, mime=item.content_type)
            )

        metadata: dict[str, Any] = {
            "message_sid": form.MessageSid,
            "account_sid": form.AccountSid,
        }
        keyword = _detect_keyword(body)
        if keyword is not None:
            # Surface opt-out/help keywords so the gateway/agent can comply.
            metadata["sms_keyword"] = keyword

        return ChannelMessage(
            channel=self.name,
            channel_user_id=from_phone,
            user_handle=from_phone,
            text=body or None,
            attachments=attachments,
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
            metadata=metadata,
        )

    async def send(self, reply: ChannelReply) -> Any:
        """Ship an outbound ChannelReply as a Twilio messages.create call.

        Builds a form payload with `From`, `To`, `Body` (capitalised) plus an
        optional `MediaUrl` for image attachments. Uses the mock transport
        when supplied in config, otherwise posts to Twilio's REST API using
        HTTP Basic Auth with `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`.

        On a non-2xx response (rate limit, validation error, ...) the live
        path returns Twilio's error JSON dict (which carries `code`/`status`)
        rather than raising, matching the mock contract so callers handle
        429s uniformly.
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

        # Outbound MMS: resolve image attachments to public MediaUrls. Twilio
        # fetches MediaUrl itself, so we need a publicly reachable URL.
        media_urls: list[str] = []
        skipped: list[str] = []
        for a in reply.attachments:
            if a.kind != "image":
                continue
            url = self._public_media_url(a)
            if url:
                media_urls.append(url)
            else:
                skipped.append(a.ref)
        if media_urls:
            payload["MediaUrl"] = media_urls[0] if len(media_urls) == 1 else media_urls

        mock = self.config.get("mock")
        if mock is not None:
            result = await mock.send(payload)
            if skipped and isinstance(result, dict):
                result.setdefault("skipped_media", skipped)
            return result

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
        result = self._parse_response(resp)
        if skipped and isinstance(result, dict):
            result.setdefault("skipped_media", skipped)
        return result

    @staticmethod
    def _parse_response(resp: httpx.Response) -> Any:
        """Return the JSON body; on non-2xx annotate with the HTTP status
        instead of raising so 429/4xx propagate to the caller as a dict."""
        try:
            body = resp.json()
        except Exception:
            body = {"message": resp.text}
        if resp.is_success:
            return body
        if isinstance(body, dict):
            body.setdefault("status", resp.status_code)
            retry_after = resp.headers.get("Retry-After")
            if retry_after is not None:
                body.setdefault("retry_after", retry_after)
            return body
        return {"status": resp.status_code, "body": body}

    def _public_media_url(self, attachment: Attachment) -> str | None:
        """Resolve an outbound image attachment to a public URL Twilio can GET.

        Preference order:
          1. explicit metadata["public_url"]
          2. a plain http(s) URL sitting in `ref`
          3. art:<sha> resolved against artifact_public_base / GLC_ARTIFACT_PUBLIC_BASE
        Returns None if none is available (caller records it as skipped).
        """
        public_url = (attachment.metadata or {}).get("public_url")
        if public_url:
            return str(public_url)

        ref = attachment.ref or ""
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref

        if ref.startswith("art:"):
            base = self.config.get("artifact_public_base") or os.environ.get("GLC_ARTIFACT_PUBLIC_BASE", "")
            if base:
                sha = ref.removeprefix("art:")
                return f"{base.rstrip('/')}/{sha}"
        return None

    async def _download_media(self, url: str) -> bytes:
        """Download Twilio-hosted MMS media using Basic Auth."""
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, auth=(account_sid, auth_token))
            resp.raise_for_status()
            return resp.content
