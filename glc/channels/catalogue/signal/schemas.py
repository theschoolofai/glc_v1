"""Channel-specific Pydantic types for the signal adapter. Add types
here as needed; the canonical ChannelMessage / ChannelReply envelope
lives in glc.channels.envelope."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class GroupInfo(BaseModel):
    """Parses the group details from an incoming message."""
    model_config = ConfigDict(extra="ignore")
    group_id: str = Field(alias="groupId")

class DataMessage(BaseModel):
    """Parses the inner message data payload."""
    model_config = ConfigDict(extra="ignore")
    timestamp: int | None = None
    message: str | None = None
    group_info: GroupInfo | None = Field(default=None, alias="groupInfo")

class SignalEnvelope(BaseModel):
    """Parses the sender envelope."""
    model_config = ConfigDict(extra="ignore")
    source: str | None = None
    source_name: str | None = Field(default=None, alias="sourceName")
    timestamp: int | None = None
    data_message: DataMessage | None = Field(default=None, alias="dataMessage")

class ReceiveParams(BaseModel):
    """Parses the JSON-RPC params for a receive notification."""
    model_config = ConfigDict(extra="ignore")
    envelope: SignalEnvelope | None = None

class SignalReceiveNotification(BaseModel):
    """Root level payload for incoming JSON-RPC."""
    model_config = ConfigDict(extra="ignore")
    method: str | None = None
    params: ReceiveParams | None = None
