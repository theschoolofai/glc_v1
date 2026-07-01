"""Channel-specific Pydantic types for the discord adapter.

These mirror the slices of the Discord gateway / REST wire format the
adapter actually reads. The canonical cross-channel envelope
(ChannelMessage / ChannelReply) lives in glc.channels.envelope; these
types only model Discord's own shapes so on_message() can parse a
MESSAGE_CREATE dispatch frame with validation instead of raw dict
indexing.

Wire-format source:
  https://discord.com/developers/docs/resources/user#user-object
  https://discord.com/developers/docs/topics/gateway-events#message-create
  https://discord.com/developers/docs/resources/channel#create-message
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DiscordUser(BaseModel):
    """A Discord User object (subset). `global_name` is the modern display
    name; `username` is the legacy unique handle. Either may address a user."""

    id: str
    username: str
    global_name: str | None = None
    discriminator: str | None = None
    bot: bool = False

    model_config = ConfigDict(extra="ignore")

    @property
    def handle(self) -> str:
        return self.global_name or self.username


class DiscordMessage(BaseModel):
    """The `d` payload of a MESSAGE_CREATE dispatch frame (subset)."""

    id: str
    channel_id: str
    content: str = ""
    author: DiscordUser
    mentions: list[DiscordUser] = Field(default_factory=list)
    guild_id: str | None = None
    timestamp: str | None = None

    model_config = ConfigDict(extra="ignore")


class DiscordCreateMessage(BaseModel):
    """Body shape for POST /channels/{channel.id}/messages. `content` is the
    canonical text field; `tts` is opt-in and must default to absent/false."""

    content: str
    tts: bool = False

    model_config = ConfigDict(extra="forbid")
