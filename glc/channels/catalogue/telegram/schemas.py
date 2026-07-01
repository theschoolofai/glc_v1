"""Channel-specific Pydantic types for the Telegram adapter.

These models represent the subset of the Telegram Bot API required by
the adapter. The canonical ChannelMessage / ChannelReply envelope lives
in glc.channels.envelope.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TelegramUser(BaseModel):
    """Telegram user."""

    id: int
    is_bot: bool = False
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    model_config = ConfigDict(extra="ignore")


class TelegramChat(BaseModel):
    """Telegram chat."""

    id: int
    type: str
    username: str | None = None
    title: str | None = None

    model_config = ConfigDict(extra="ignore")


class TelegramPhotoSize(BaseModel):
    """Telegram PhotoSize object."""

    file_id: str
    file_unique_id: str | None = None
    width: int
    height: int
    file_size: int | None = None

    model_config = ConfigDict(extra="ignore")


class TelegramMessage(BaseModel):
    """Telegram Message object."""

    message_id: int
    date: int | None = None

    chat: TelegramChat

    from_: TelegramUser | None = Field(
        default=None,
        alias="from",
    )

    text: str | None = None
    caption: str | None = None

    photo: list[TelegramPhotoSize] = Field(
        default_factory=list,
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )


class TelegramUpdate(BaseModel):
    """Telegram Update object."""

    update_id: int
    message: TelegramMessage | None = None

    model_config = ConfigDict(extra="ignore")
