"""Channel-specific Pydantic types for the twilio_sms adapter.

The canonical ChannelMessage / ChannelReply envelope lives in
glc.channels.envelope and must NOT be redefined here. These models only
describe the Twilio *wire* format (inbound webhook form + outbound
messages.create payload) and the local artifact-store metadata sidecar.

Wire-format basis:
  https://www.twilio.com/docs/messaging/guides/webhook-request
  https://www.twilio.com/docs/messaging/api/message-resource
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TwilioMediaItem(BaseModel):
    """One MMS media item pulled from MediaUrl{i} / MediaContentType{i}."""

    url: str
    content_type: str = "application/octet-stream"

    model_config = ConfigDict(extra="forbid")


class TwilioInboundForm(BaseModel):
    """Parsed Twilio inbound webhook (application/x-www-form-urlencoded).

    Twilio sends many extra geolocation fields (FromCity, FromZip, ...),
    so `extra="allow"` keeps them accessible without listing each one.
    NumMedia arrives as a string on the wire and is coerced to int.
    """

    From: str = ""
    To: str = ""
    Body: str = ""
    MessageSid: str = ""
    AccountSid: str = ""
    NumMedia: int = 0

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> TwilioInboundForm:
        """Build tolerantly from a raw form dict; never raises on bad input."""
        try:
            return cls.model_validate(dict(raw))
        except Exception:
            # Fall back to best-effort field extraction so on_message never
            # raises on malformed input (disconnect/robustness requirement).
            def _int(v: Any) -> int:
                try:
                    return int(v or 0)
                except (TypeError, ValueError):
                    return 0

            return cls.model_construct(
                From=str(raw.get("From", "")),
                To=str(raw.get("To", "")),
                Body=str(raw.get("Body", "")),
                MessageSid=str(raw.get("MessageSid", "")),
                AccountSid=str(raw.get("AccountSid", "")),
                NumMedia=_int(raw.get("NumMedia", 0)),
            )

    def media_items(self) -> list[TwilioMediaItem]:
        """Return MediaUrl0..N as typed items, skipping blank URLs."""
        extra = self.__pydantic_extra__ or {}
        items: list[TwilioMediaItem] = []
        for i in range(self.NumMedia):
            url = extra.get(f"MediaUrl{i}", "")
            if not url:
                continue
            ct = extra.get(f"MediaContentType{i}", "application/octet-stream")
            items.append(TwilioMediaItem(url=str(url), content_type=str(ct)))
        return items


class TwilioSendPayload(BaseModel):
    """Outbound messages.create form fields (capitalised — Twilio rejects
    lowercase keys). MediaUrl may be a single URL or a list for multi-MMS."""

    From: str
    To: str
    Body: str = ""
    MediaUrl: str | list[str] | None = None

    model_config = ConfigDict(extra="forbid")

    def to_form(self) -> dict[str, Any]:
        """Wire dict with None fields dropped."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class StoredArtifact(BaseModel):
    """Metadata sidecar for the local artifact store (mirrors the agent
    layer's Artifact model, which is not importable from glc_v1)."""

    id: str  # art:<sha16>
    content_type: str
    size_bytes: int
    source: str
    descriptor: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(extra="forbid")
