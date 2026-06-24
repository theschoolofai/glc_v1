"""Gemini Live TTS wire-format types and frame builders.

Canonical result types live in glc.voice.tts.base — do not redefine them here.
Wire-format reference: https://ai.google.dev/api/live
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

# Live API model — TTS-only models do not support BidiGenerateContent WebSocket.
DEFAULT_MODEL = os.getenv(
    "GEMINI_LIVE_MODEL",
    "models/gemini-3.1-flash-live-preview",
)

DEFAULT_SAMPLE_RATE = 24000

# Gemini Live API native-audio pricing, USD per 1M tokens.
# Source: https://ai.google.dev/gemini-api/docs/pricing — verified 2026-06-23.
# Overridable per deployment via env so the rate table never goes stale.
GEMINI_LIVE_INPUT_USD_PER_MTOK = float(os.getenv("GEMINI_LIVE_INPUT_USD_PER_MTOK", "1.00"))
GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK = float(os.getenv("GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK", "20.00"))


def build_setup_frame(voice_id: str | None = None) -> dict[str, Any]:
    """First WebSocket frame: BidiGenerateContentSetup."""
    generation_config: dict[str, Any] = {
        "responseModalities": ["AUDIO"],
    }
    if voice_id and voice_id != "default":
        generation_config["speechConfig"] = {
            "voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": voice_id},
            }
        }
    return {
        "setup": {
            "model": DEFAULT_MODEL,
            "generationConfig": generation_config,
        }
    }


def build_client_content_frame(text: str) -> dict[str, Any]:
    """Send user text and signal the server to start generation."""
    return {
        "clientContent": {
            "turns": [{"role": "user", "parts": [{"text": text}]}],
            "turnComplete": True,
        }
    }


def ws_url(api_key: str) -> str:
    """Authenticated WebSocket endpoint."""
    return f"{WS_URL}?key={api_key}"


def _usage_token_count(usage: dict[str, Any], *keys: str) -> int:
    """First present numeric token-count field among `keys` (0 if none)."""
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def cost_from_usage(usage: dict[str, Any] | None) -> float:
    """Estimate USD list-price cost from a BidiGenerateContent ``usageMetadata`` frame.

    Text prompt tokens bill at the input rate and the model's audio response
    tokens at the audio-output rate. Returns 0.0 when no usage metadata is
    present (e.g. no frame arrived) so a missing frame never invents a cost,
    and clamps to a non-negative floor against malformed counts.
    """
    if not usage:
        return 0.0
    prompt_tokens = _usage_token_count(usage, "promptTokenCount", "prompt_token_count")
    response_tokens = _usage_token_count(
        usage,
        "responseTokenCount",
        "response_token_count",
        "candidatesTokenCount",
        "candidates_token_count",
    )
    cost = (
        prompt_tokens * GEMINI_LIVE_INPUT_USD_PER_MTOK
        + response_tokens * GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK
    ) / 1_000_000
    return round(max(0.0, cost), 6)


@dataclass
class TTSPolicyConfig:
    input_max_len: int
    input_min_len: int
    output_max_size: int
