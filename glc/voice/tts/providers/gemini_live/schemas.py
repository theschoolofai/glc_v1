"""Gemini Live TTS wire-format types and frame builders.

Canonical result types live in glc.voice.tts.base — do not redefine them here.
Wire-format reference: https://ai.google.dev/api/live
"""

from __future__ import annotations

import os
from typing import Any
from dataclasses import dataclass

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

@dataclass
class TTSPolicyConfig:
    input_max_len: int
    input_min_len: int
    output_max_size: int