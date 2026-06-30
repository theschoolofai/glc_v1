"""Channel-specific Pydantic types for the webhook adapter. Add types
here as needed; the canonical ChannelMessage / ChannelReply envelope
lives in glc.channels.envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebhookInbound(BaseModel):
    """Parsed JSON body of an inbound Stripe-style signed webhook POST.

    This mirrors the wire payload produced by the webhook mock: a sender
    identity, the message text, and an open metadata bag. ``on_message``
    validates the raw request bytes into this model *after* the signature
    and replay-window check pass, then maps it onto the canonical
    ``ChannelMessage`` envelope (see glc.channels.envelope).

    ``sender_id`` is the per-integration external identity used to
    classify trust; ``sender_handle`` is the human-facing label. Both are
    required because the gateway cannot route or pair an anonymous sender.
    ``text`` mirrors the envelope's nullable text field. ``extra`` is
    ignored rather than forbidden: this is a trust boundary fed by
    third-party callers, so unknown fields are dropped instead of
    rejecting an otherwise valid, correctly-signed message.
    """

    sender_id: str
    sender_handle: str
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")
