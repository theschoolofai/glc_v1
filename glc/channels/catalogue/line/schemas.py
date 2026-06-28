"""Channel-specific Pydantic types for the line adapter. Add types
here as needed; the canonical ChannelMessage / ChannelReply envelope
lives in glc.channels.envelope."""

from __future__ import annotations

from pydantic import BaseModel


class LineEvent(BaseModel):
    """Projection of the LINE webhook event fields the adapter consumes."""

    user_id: str
    text: str | None = None
    reply_token: str | None = None
    message_type: str = "text"
