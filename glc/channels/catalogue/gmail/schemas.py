"""Channel-specific Pydantic types for the Gmail adapter.

These model the Gmail API wire format — used for validation
and type safety when parsing Pub/Sub notifications and API responses.
The canonical ChannelMessage / ChannelReply envelope lives in
glc.channels.envelope.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PubSubMessageData(BaseModel):
    """Decoded content of Pub/Sub message.data (base64 → JSON)."""

    emailAddress: str
    historyId: int

    model_config = ConfigDict(extra="forbid")


class PubSubMessage(BaseModel):
    """The message field inside a Pub/Sub push notification."""

    data: str
    messageId: str | None = None
    publishTime: str | None = None

    model_config = ConfigDict(extra="allow")


class PubSubPushNotification(BaseModel):
    """Top-level Pub/Sub push notification body (what Gmail sends)."""

    message: PubSubMessage
    subscription: str | None = None

    model_config = ConfigDict(extra="allow")


class GmailMessageRef(BaseModel):
    """A message reference as returned by history.list."""

    id: str
    threadId: str | None = None

    model_config = ConfigDict(extra="allow")


class GmailHistoryRecord(BaseModel):
    """A single history record from users.history.list."""

    id: str
    messagesAdded: list[dict] | None = None

    model_config = ConfigDict(extra="allow")


class GmailSendPayload(BaseModel):
    """Payload for users.messages.send — what we POST to Gmail."""

    raw: str
    threadId: str | None = None

    model_config = ConfigDict(extra="forbid")


class GmailSendResponse(BaseModel):
    """Response from users.messages.send."""

    id: str
    threadId: str | None = None
    labelIds: list[str] | None = None

    model_config = ConfigDict(extra="allow")
