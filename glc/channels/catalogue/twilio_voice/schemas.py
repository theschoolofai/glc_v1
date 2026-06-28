"""Channel-specific Pydantic types for the twilio_voice adapter.

These model the *untrusted, external* Twilio wire shapes the adapter
ingests, so the adapter validates at the boundary instead of fishing
through raw dicts:

  - TwilioInboundEvent      — the call webhook Twilio POSTs (form-urlencoded).
  - TwilioMediaStreamFrame  — a Media Streams WebSocket audio frame.
  - TwilioStreamStartFrame  — the WS `start` frame (carries the caller, keyed
                              per streamSid so concurrent calls stay separate).
  - TwilioStreamStopFrame   — the WS `stop` frame (lets us evict stream state).

The canonical ChannelMessage / ChannelReply envelope lives in
glc.channels.envelope and must not be redefined here.

Wire-format source:
  https://www.twilio.com/docs/voice/twiml
  https://www.twilio.com/docs/voice/twiml/stream
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TwilioInboundEvent(BaseModel):
    """A Programmable Voice call webhook. Twilio sends many more fields
    (FromCountry, CalledCity, ...); we model the ones we use and ignore
    the rest. `From` is required — an event without a caller is invalid."""

    model_config = ConfigDict(extra="ignore")

    From: str
    To: str | None = None
    CallSid: str | None = None
    AccountSid: str | None = None
    CallStatus: str | None = None  # ringing, in-progress, completed, ...
    Direction: str | None = None  # inbound / outbound-api / ...
    CallerName: str | None = None


class TwilioMediaPayload(BaseModel):
    """The inner `media` object of a Media Streams frame. `payload` is
    base64-encoded mu-law audio at 8 kHz mono."""

    model_config = ConfigDict(extra="ignore")

    payload: str
    track: str | None = None
    chunk: str | None = None
    timestamp: str | None = None


class TwilioMediaStreamFrame(BaseModel):
    """A Media Streams WebSocket frame. We only act on `event == "media"`;
    the nested `media.payload` carries the audio bytes."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["media"]
    media: TwilioMediaPayload
    streamSid: str | None = None
    sequenceNumber: str | None = None


class TwilioStreamStart(BaseModel):
    """The inner `start` object. `customParameters` echoes the values we set
    on the <Stream> in our TwiML — that's how the caller's identity reaches
    the (otherwise caller-less) media stream."""

    model_config = ConfigDict(extra="ignore")

    streamSid: str
    callSid: str | None = None
    customParameters: dict[str, str] = Field(default_factory=dict)


class TwilioStreamStartFrame(BaseModel):
    """The first Media Streams frame for a call. We register its caller under
    `start.streamSid` so each concurrent stream is tracked independently."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["start"]
    start: TwilioStreamStart


class TwilioStreamStopFrame(BaseModel):
    """The final Media Streams frame. We evict the stream's caller state so
    long-running processes don't leak memory across calls."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["stop"]
    streamSid: str
