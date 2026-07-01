"""Laptop microphone adapter.

The wire format is course-defined: inbound events carry WAV bytes from the
recording loop, and outbound replies become synthesized audio sent to the
speaker/playback surface.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import struct
import wave
from datetime import UTC, datetime
from typing import Any, cast

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify
from glc.voice.stt import transcribe as transcribe_audio
from glc.voice.tts import synthesize as synthesize_speech

DEFAULT_VAD_RMS_THRESHOLD = 200.0


class Adapter(ChannelAdapter):
    name = "local_mic"

    async def on_message(self, raw: Any) -> ChannelMessage:
        mock = self.config.get("mock")
        if mock is not None and mock.pop_disconnect():
            return _drop()

        if not isinstance(raw, dict):
            return _drop()

        wav_bytes = _as_bytes(raw.get("wav_bytes") or raw.get("audio_bytes") or b"")
        if not wav_bytes:
            return _drop()

        speaker_id = str(raw.get("speaker_id") or raw.get("channel_user_id") or "local")
        speaker_handle = str(raw.get("speaker_handle") or raw.get("user_handle") or speaker_id)
        trust_level = classify(self.name, speaker_id)

        is_public_channel = bool(self.config.get("is_public_channel", raw.get("is_public_channel", False)))
        was_mentioned = bool(raw.get("was_mentioned", False))
        if is_public_channel:
            owners = [p.channel_user_id for p in get_pairing_store().owners(channel=self.name)]
            ok, _why = allowed(
                self.name,
                speaker_id,
                owner_ids=owners,
                is_public_channel=True,
                was_mentioned=was_mentioned,
            )
            if not ok:
                return _drop()

        if _is_silent(wav_bytes, threshold=_vad_threshold(self.config)):
            return _drop()

        mime = str(raw.get("mime") or "audio/wav")
        stt_prefer = str(
            self.config.get("stt_prefer")
            or self.config.get("transcribe_prefer")
            or self.config.get("prefer")
            or "default"
        )
        transcript = await transcribe_audio(wav_bytes, mime, prefer=stt_prefer)
        text = transcript.text.strip()
        if not text:
            return _drop()

        voice_audio_ref = _artifact_ref(wav_bytes, mock=mock)
        return ChannelMessage(
            channel=self.name,
            channel_user_id=speaker_id,
            user_handle=speaker_handle,
            text=text,
            voice_audio_ref=voice_audio_ref,
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
            metadata={
                "source": raw.get("source", "mic"),
                "sample_rate": raw.get("sample_rate"),
                "mime": mime,
                "stt_provider": transcript.provider,
                "stt_duration_ms": transcript.duration_ms,
                "is_public_channel": is_public_channel,
                "was_mentioned": was_mentioned,
            },
        )

    async def send(self, reply: ChannelReply) -> Any:
        mock = self.config.get("mock")
        text = reply.text or ""

        if mock is not None and getattr(mock, "rate_limited", False):
            return await mock.send({"channel_user_id": reply.channel_user_id, "text": text})

        voice_id = self.config.get("voice_id")
        tts_prefer = str(self.config.get("tts_prefer") or self.config.get("speak_prefer") or "default")
        speech = await synthesize_speech(text, voice_id=voice_id, prefer=tts_prefer)
        audio_bytes = base64.b64decode(speech.audio_b64)
        payload = {
            "channel_user_id": reply.channel_user_id,
            "text": text,
            "audio_bytes": audio_bytes,
            "mime": speech.mime,
            "sample_rate": speech.sample_rate,
            "provider": speech.provider,
            "voice_id": voice_id,
        }
        if mock is not None:
            return await mock.send(payload)
        return payload


def _as_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return b""


def _drop() -> ChannelMessage:
    return cast(ChannelMessage, None)


def _vad_threshold(config: dict[str, Any]) -> float:
    raw = config.get("vad_rms_threshold", DEFAULT_VAD_RMS_THRESHOLD)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_VAD_RMS_THRESHOLD


def _is_silent(audio: bytes, *, threshold: float) -> bool:
    frames = _wav_pcm_frames(audio)
    if frames is None:
        return not any(audio)
    if not frames:
        return True
    return _rms_16bit_pcm(frames) < threshold


def _wav_pcm_frames(audio: bytes) -> bytes | None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getsampwidth() != 2:
                return None
            return wav.readframes(wav.getnframes())
    except (EOFError, wave.Error):
        return None


def _rms_16bit_pcm(frames: bytes) -> float:
    usable = len(frames) - (len(frames) % 2)
    if usable <= 0:
        return 0.0
    total = 0
    count = 0
    for (sample,) in struct.iter_unpack("<h", frames[:usable]):
        total += sample * sample
        count += 1
    if count == 0:
        return 0.0
    return math.sqrt(total / count)


def _artifact_ref(audio: bytes, *, mock: Any) -> str:
    sha = hashlib.sha256(audio).hexdigest()
    store_artifact = getattr(mock, "store_artifact", None)
    if callable(store_artifact):
        return store_artifact(sha, audio)
    return f"art:{sha}"
