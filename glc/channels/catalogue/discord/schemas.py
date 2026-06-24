"""Channel-specific Pydantic types for the discord adapter.

These model the Discord Gateway dispatch frame and the REST send body.
The canonical ChannelMessage / ChannelReply envelope lives in
glc.channels.envelope and is NOT redefined here.

Wire-format source:
  https://discord.com/developers/docs/topics/gateway-events#message-create
  https://discord.com/developers/docs/resources/channel#create-message
  https://discord.com/developers/docs/resources/user#user-object

Design notes
------------
* Inbound types use ``extra="ignore"``: Discord adds fields over time and
  multiplexes many event shapes over one socket, so permissive parsing
  avoids brittle crashes on frames we do not care about.
* The outbound ``DiscordCreateMessageBody`` uses ``extra="forbid"``: that
  body is *our* contract with Discord's REST API, so a stray field there
  is a bug we want surfaced.
* Snowflakes (ids) are strings, never ints — matches the API and the mock.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiscordUser(BaseModel):
    """A Discord User object (subset we consume)."""

    id: str
    username: str
    discriminator: str = "0"
    global_name: str | None = None
    bot: bool = False

    model_config = ConfigDict(extra="ignore")


class DiscordMessage(BaseModel):
    """The ``d`` payload of a MESSAGE_CREATE dispatch frame."""

    id: str
    channel_id: str
    guild_id: str | None = None  # None => DM; set => guild (public server)
    author: DiscordUser
    content: str = ""
    timestamp: str = ""
    mentions: list[DiscordUser] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    type: int = 0

    model_config = ConfigDict(extra="ignore")


class DiscordGatewayEvent(BaseModel):
    """A Gateway dispatch frame: ``{op, t, s, d}``.

    ``d`` is held as a raw dict and only parsed into a ``DiscordMessage``
    once the adapter has confirmed ``op == 0 and t == "MESSAGE_CREATE"``.
    """

    op: int
    t: str | None = None
    s: int | None = None
    d: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class DiscordCreateMessageBody(BaseModel):
    """Body for ``POST /channels/{channel.id}/messages``.

    ``content`` is the canonical text field. ``tts`` is opt-in per channel
    and must default to False so the gateway never speaks unprompted.
    """

    content: str
    tts: bool = False

    model_config = ConfigDict(extra="forbid")
