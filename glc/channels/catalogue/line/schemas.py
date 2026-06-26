"""Channel-specific Pydantic types for the line adapter. Add types
here as needed; the canonical ChannelMessage / ChannelReply envelope
lives in glc.channels.envelope."""

from __future__ import annotations

from pydantic import BaseModel


class LineEvent(BaseModel):
    """Parsed fields from a single LINE webhook event.

    This is a lightweight projection of the nested webhook dict —
    just the fields the adapter needs for envelope construction.
    """

    user_id: str
    text: str | None = None
    reply_token: str
    message_type: str = "text"
