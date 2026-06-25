"""Adapter for laptop microphone (local voice-first channel)."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.trust_level import classify
from glc.voice.stt import router as stt_router
from glc.voice.tts import router as tts_router

_WAV_HEADER_BYTES = 44


class Adapter(ChannelAdapter):
    name = "local_mic"

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        mock = self.config.get("mock")

        if mock is not None and mock.pop_disconnect():
            return None

        wav_bytes: bytes = raw["wav_bytes"]
        speaker_id: str = raw["speaker_id"]
        speaker_handle: str = raw["speaker_handle"]

        # VAD: skip 44-byte WAV header, check audio payload for silence
        audio_payload = wav_bytes[_WAV_HEADER_BYTES:]
        if audio_payload and all(b == 0 for b in audio_payload[:200]):
            return None

        trust_level = classify("local_mic", speaker_id)

        if self.config.get("is_public_channel") and trust_level == "untrusted":
            return None

        result = await stt_router.transcribe(wav_bytes, "audio/wav")

        if not result.text:
            return None

        art_ref = "art:" + hashlib.sha256(wav_bytes).hexdigest()[:16]

        return ChannelMessage(
            channel="local_mic",
            channel_user_id=speaker_id,
            user_handle=speaker_handle,
            text=result.text,
            voice_audio_ref=art_ref,
            trust_level=trust_level,
            arrived_at=datetime.now(timezone.utc),
        )

    async def send(self, reply: ChannelReply) -> Any:
        raise NotImplementedError("send not yet implemented")
