"""Twilio Voice (PSTN in/out) adapter.

Wire format: Twilio Programmable Voice TwiML + Media Streams.
  - Inbound call  -> form-urlencoded webhook (CallSid/From/To/...), we
    answer with TwiML that opens a <Connect><Stream> back to the GLC
    voice WebSocket.
  - Inbound audio -> Media Streams WS frame {event:"media", media:{payload}}
    where payload is base64 mu-law @ 8 kHz. We decode it, transcribe it,
    persist the bytes to the artifact store, and surface a ChannelMessage.
  - Outbound       -> TwiML XML returned from the webhook response.

See docs/ADAPTER_GUIDE.md and the README in this directory.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from pydantic import ValidationError

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.twilio_voice.audio import WAV_MIME, mulaw_to_wav
from glc.channels.catalogue.twilio_voice.schemas import (
    TwilioInboundEvent,
    TwilioMediaStreamFrame,
    TwilioStreamStartFrame,
    TwilioStreamStopFrame,
)
from glc.channels.catalogue.twilio_voice.signature import verify_signature
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify
from glc.voice.stt import transcribe as stt_transcribe

logger = logging.getLogger(__name__)

# Default WebSocket the Media Stream is pointed at. Overridable via config.
DEFAULT_STREAM_URL = "wss://localhost:8111/v1/channels/twilio_voice/media"

# Twilio Media Streams audio is base64 mu-law @ 8 kHz mono. We decode it to a
# 16 kHz mono PCM WAV (see audio.py) before handing it to the STT facade — raw
# mu-law has no container and the STT providers reject it.

# Call statuses that mean the call is over — no audio will follow.
_TERMINAL_CALL_STATUSES = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})


def _redact(phone: str) -> str:
    """Redact a phone number for logs — keep only the last 4 digits. Never
    log a full caller number (PII / GDPR-CCPA)."""
    if len(phone) <= 4:
        return "***"
    return f"***{phone[-4:]}"


class Adapter(ChannelAdapter):
    name = "twilio_voice"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Per-stream caller registry, keyed by Media Streams streamSid. The
        # gateway holds ONE adapter instance per channel, so a single scalar
        # would let concurrent calls clobber each other. Each stream's caller
        # is registered on its `start` frame and evicted on `stop`.
        self._stream_callers: dict[str, dict[str, str]] = {}

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")

        # A forced disconnect must be handled gracefully — never raise.
        reconnect = False
        if mock is not None and mock.pop_disconnect():
            reconnect = True

        # Inbound shapes: a Media Streams frame (start/media/stop) or a call
        # webhook. Route by the frame's `event`; a webhook has no `event`.
        if isinstance(raw, dict):
            event = raw.get("event")
            if event == "media":
                return await self._handle_media_frame(raw, mock)
            if event == "start":
                return self._handle_stream_start(raw)
            if event == "stop":
                return self._handle_stream_stop(raw)
        return self._handle_call_webhook(raw, reconnect=reconnect)

    def authenticate_webhook(self, raw: dict[str, Any], *, url: str, signature: str | None) -> bool:
        """Verify an inbound call webhook actually came from Twilio.

        This is the entry point for the deployment HTTP layer: it should call
        `authenticate_webhook(form, url=<full request URL>, signature=<the
        X-Twilio-Signature header>)` and reject the request (HTTP 403) before
        passing the form to `on_message` if this returns False.

        It is *not* called from `on_message` itself because the signature is an
        HTTP header that lives in the (out-of-repo) web layer, not in the wire
        payload the adapter receives. Until that layer is wired, inbound trust
        still rests on `From` — see README Limitation 1. The verifier is built,
        tested against Twilio's published vector, and ready for that caller.

        The auth token is read from `config["auth_token"]`, falling back to the
        `TWILIO_AUTH_TOKEN` environment variable. With no token we fail closed.
        Synthetic keys (leading underscore) are excluded so they never corrupt
        the signature base string.
        """
        token = self.config.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN")
        params = {k: v for k, v in raw.items() if isinstance(v, str) and not k.startswith("_")}
        return verify_signature(token or "", url, params, signature)

    async def send(self, reply: ChannelReply) -> Any:
        # Soft-note outbound guard: we only ever reply on the active call, so a
        # non-paired recipient is not blocked (that would break the reply and
        # Test 3). We log it so the security posture is visible. Initiating a
        # *new* outbound call to an unpaired number is a separate path that
        # must gate on pairing — see README limitations.
        if classify(self.name, reply.channel_user_id) == "untrusted":
            logger.warning(
                "twilio_voice: replying on active call to non-paired recipient %s",
                _redact(reply.channel_user_id),
            )

        body = {"twiml": self._build_twiml(reply), "to": reply.channel_user_id}
        mock = self.config.get("mock")
        if mock is not None:
            # The mock returns a 429 dict when rate-limited; pass it through.
            return await mock.send(body)
        return body

    # -- inbound helpers ----------------------------------------------------

    def _handle_call_webhook(self, raw: Any, *, reconnect: bool) -> ChannelMessage:
        # Validate the untrusted webhook at the boundary. A malformed event
        # (no caller, wrong shape) collapses to an untrusted, caller-less
        # envelope rather than letting bad data into the agent runtime.
        try:
            event = TwilioInboundEvent.model_validate(raw)
        except ValidationError:
            event = None

        from_phone = event.From if event else ""
        handle = (event.CallerName if event else None) or from_phone

        trust = classify(self.name, from_phone)

        # In a public-channel context, consult the allowlist. Strangers stay
        # untrusted (the agent runtime drops untrusted senders downstream).
        if self.config.get("is_public_channel"):
            owners = [r.channel_user_id for r in get_pairing_store().owners(self.name)]
            ok, _reason = allowed(self.name, from_phone, owner_ids=owners, is_public_channel=True)
            if not ok:
                trust = "untrusted"

        status = event.CallStatus if event else None
        metadata: dict[str, Any] = {
            "call_sid": event.CallSid if event else None,
            "call_status": status,
            "direction": event.Direction if event else None,
            "call_stage": "ringing",
        }
        # A terminal-status webhook is call lifecycle, not speech — flag it
        # so downstream skips it instead of waiting for audio that won't come.
        if status in _TERMINAL_CALL_STATUSES:
            metadata["lifecycle"] = True
        if reconnect:
            metadata["reconnect"] = True

        return ChannelMessage(
            channel=self.name,
            channel_user_id=from_phone,
            user_handle=handle,
            text=None,
            trust_level=trust,
            arrived_at=datetime.now(UTC),
            metadata=metadata,
        )

    def _malformed_frame_message(self, frame_event: str) -> ChannelMessage:
        # A frame we could not parse. Mirror the webhook path: never raise on
        # bad input — collapse to an untrusted, caller-less envelope flagged for
        # audit, rather than letting an exception tear down the live call.
        return ChannelMessage(
            channel=self.name,
            channel_user_id="",
            user_handle="",
            text=None,
            trust_level="untrusted",
            arrived_at=datetime.now(UTC),
            metadata={"malformed_frame": True, "frame_event": frame_event},
        )

    def _handle_stream_start(self, raw: dict[str, Any]) -> ChannelMessage:
        # The stream's caller arrives in customParameters (echoing the values
        # we put on the <Stream> in our TwiML). Register it under streamSid so
        # this call's media frames resolve to the right person.
        try:
            frame = TwilioStreamStartFrame.model_validate(raw)
        except ValidationError:
            return self._malformed_frame_message("start")
        params = frame.start.customParameters
        caller = params.get("caller", "")
        handle = params.get("handle") or caller
        self._stream_callers[frame.start.streamSid] = {"id": caller, "handle": handle}
        return ChannelMessage(
            channel=self.name,
            channel_user_id=caller,
            user_handle=handle or caller,
            text=None,
            trust_level=classify(self.name, caller),
            arrived_at=datetime.now(UTC),
            metadata={"stream_sid": frame.start.streamSid, "call_stage": "answered"},
        )

    def _handle_stream_stop(self, raw: dict[str, Any]) -> ChannelMessage:
        # Evict the stream's caller so a long-lived process doesn't leak one
        # dict entry per call forever.
        try:
            frame = TwilioStreamStopFrame.model_validate(raw)
        except ValidationError:
            return self._malformed_frame_message("stop")
        caller = self._stream_callers.pop(frame.streamSid, {})
        caller_id = caller.get("id", "")
        return ChannelMessage(
            channel=self.name,
            channel_user_id=caller_id,
            user_handle=caller.get("handle") or caller_id,
            text=None,
            trust_level=classify(self.name, caller_id),
            arrived_at=datetime.now(UTC),
            metadata={"stream_sid": frame.streamSid, "call_stage": "completed", "lifecycle": True},
        )

    async def _handle_media_frame(self, raw: dict[str, Any], mock: Any) -> ChannelMessage:
        # Validate the frame before touching its bytes. A malformed frame
        # collapses to an untrusted, caller-less envelope instead of raising.
        try:
            frame = TwilioMediaStreamFrame.model_validate(raw)
        except ValidationError:
            return self._malformed_frame_message("media")

        # Decode the base64 mu-law payload. A corrupt payload (bad padding,
        # non-alphabet bytes) becomes empty audio rather than crashing the
        # call — we still emit an envelope, flagged so downstream can see it.
        decode_failed = False
        try:
            mulaw = base64.b64decode(frame.media.payload, validate=True) if frame.media.payload else b""
        except (binascii.Error, ValueError):
            mulaw = b""
            decode_failed = True
        # Normalise Twilio's headerless 8 kHz mu-law into a self-describing
        # 16 kHz mono PCM WAV. This is the format the STT facade and the
        # artifact store both expect; raw mu-law would fail against the real
        # providers (it passes in tests only because the mock ignores bytes).
        wav = mulaw_to_wav(mulaw)

        # Resolve the caller from the per-stream registry (set on `start`).
        # An unknown stream falls back to an unattributed, untrusted message
        # rather than borrowing another concurrent call's caller.
        caller = self._stream_callers.get(frame.streamSid or "", {})
        caller_id = caller.get("id", "")
        handle = caller.get("handle") or caller_id

        # Persist the recording first, so we keep the audio even if the
        # transcription step fails. We store the decoded WAV (self-contained,
        # playable) rather than the raw mu-law. The mock backs the artifact
        # store in tests; in production this handle points at the gateway store.
        sha = hashlib.sha256(wav).hexdigest()
        ref = mock.store_artifact(sha, wav) if mock is not None else f"art:{sha}"

        metadata: dict[str, Any] = {"stream_sid": frame.streamSid, "call_stage": "answered"}
        if decode_failed:
            metadata["malformed_audio"] = True
        text: str | None
        try:
            if mock is not None:
                text = mock.transcribe(wav)
            else:
                result = await stt_transcribe(wav, WAV_MIME)
                text = result.text
        except Exception as exc:  # transcription failed — keep audio, report it
            text = None
            metadata["transcription_error"] = str(exc)
        else:
            if text == "":
                # We heard the caller but got no words (silence/noise).
                metadata["empty_transcript"] = True

        return ChannelMessage(
            channel=self.name,
            channel_user_id=caller_id,
            user_handle=handle or caller_id,
            text=text,
            voice_audio_ref=ref,
            trust_level=classify(self.name, caller_id),
            arrived_at=datetime.now(UTC),
            metadata=metadata,
        )

    # -- outbound helper ----------------------------------------------------

    def _build_twiml(self, reply: ChannelReply) -> str:
        stream_url = self.config.get("stream_url", DEFAULT_STREAM_URL)
        say = f"<Say>{escape(reply.text)}</Say>" if reply.text else ""
        # Pass the caller as a <Parameter> so Twilio echoes it back in the
        # stream's `start` frame — that's how the caller-less media stream
        # learns whose audio it is. <Connect> must be immediately followed by
        # <Stream> so Twilio opens the bidirectional Media Streams WebSocket.
        caller = escape(reply.channel_user_id)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"{say}"
            f'<Connect><Stream url="{escape(stream_url)}">'
            f'<Parameter name="caller" value="{caller}"/>'
            "</Stream></Connect>"
            "</Response>"
        )
