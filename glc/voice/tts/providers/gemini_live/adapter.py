"""Provider for Gemini Live realtime full-duplex TTS (BidiGenerateContent WebSocket)."""

from __future__ import annotations

import base64
import io
import json
import os
import wave
from typing import Any

import websockets

from glc.voice.tts.base import SynthesizeResult, TTSError, TTSProvider
from glc.voice.tts.providers.gemini_live.policy import TTSPolicy
from glc.voice.tts.providers.gemini_live.schemas import (
    DEFAULT_SAMPLE_RATE,
    TTSPolicyConfig,
    build_client_content_frame,
    build_setup_frame,
    cost_from_usage,
    ws_url,
)

# inout text size
input_text_max_length = int(os.getenv("GEMINI_LIVE_TTS_INPUT_TEXT_MAX_LENGTH", 1000))
input_text_min_length = int(os.getenv("GEMINI_LIVE_TTS_INPUT_TEXT_MIN_LENGTH", 0))

# output audio size
output_audio_max_size = int(os.getenv("GEMINI_LIVE_TTS_OUTPUT_AUDIO_MAX_SIZE", 5 * 1024 * 1024))


class Provider(TTSProvider):
    name = "gemini_live"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        policy_config = TTSPolicyConfig(input_text_max_length, input_text_min_length, output_audio_max_size)
        self.policy = TTSPolicy(policy_config)

    async def synthesize(self, text: str, voice_id: str | None = None) -> SynthesizeResult:
        # validate input text
        self.policy.validate_input(text)
        setup_frame = build_setup_frame(voice_id)

        mock = self.config.get("mock")
        if mock is not None:
            mock.record_frame(setup_frame)
            return await mock.synthesize(text, voice_id)

        return await self._synthesize_live(text, setup_frame)

    async def _synthesize_live(self, text: str, setup_frame: dict) -> SynthesizeResult:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise TTSError("GEMINI_API_KEY is not set", status=401)

        url = ws_url(api_key)
        pcm_chunks: list[bytes] = []
        sample_rate = DEFAULT_SAMPLE_RATE
        last_usage: dict[str, Any] | None = None

        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(setup_frame))
                await ws.recv()  # setupComplete

                await ws.send(json.dumps(build_client_content_frame(text)))

                async for raw in ws:
                    msg = json.loads(raw)
                    # usageMetadata arrives on frames without serverContent, so
                    # capture it before the guard below skips them. Gemini sends
                    # cumulative totals; keep the last one seen.
                    if (u := msg.get("usageMetadata")) is not None:
                        last_usage = u
                    server_content = msg.get("serverContent")
                    if not server_content:
                        continue

                    model_turn = server_content.get("modelTurn")
                    if model_turn:
                        for part in model_turn.get("parts", []):
                            inline = part.get("inlineData")
                            if inline and inline.get("data"):
                                pcm_chunks.append(base64.b64decode(inline["data"]))
                                mime_type = inline.get("mimeType", "")
                                if "rate=" in mime_type:
                                    sample_rate = int(mime_type.rsplit("rate=", 1)[-1])

                    if server_content.get("turnComplete"):
                        break
        except (OSError, websockets.exceptions.WebSocketException) as e:
            raise TTSError(f"gemini_live upstream error: {e}", status=502) from e

        wav_bytes = self._pcm_to_wav(b"".join(pcm_chunks), sample_rate)
        # validate output audio size
        self.policy.validate_output(wav_bytes)
        return SynthesizeResult(
            audio_b64=base64.b64encode(wav_bytes).decode("ascii"),
            mime="audio/wav",
            sample_rate=sample_rate,
            provider=self.name,
            cost_usd=cost_from_usage(last_usage),
        )

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()
