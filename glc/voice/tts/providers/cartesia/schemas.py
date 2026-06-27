"""Cartesia Sonic API contract — endpoint, headers, request shape, defaults.

This file encodes the wire format documented at
https://docs.cartesia.ai/api-reference/tts/bytes so the adapter only
handles orchestration (mock check, HTTP call, error handling) and never
embeds API-shape knowledge directly.

Why separate from adapter.py?
  - If Cartesia bumps their API version or changes a field name, we can update this file and
    the adapter will continue to work.
  - The request model validates itself via Pydantic before we send it,
    catching typos at build time rather than at runtime as a 400 from
    Cartesia.
  - Tests can import these constants to assert the adapter sends the
    right shape without hardcoding strings in both places.
"""

from __future__ import annotations

from pydantic import BaseModel

# ── API constants ────────────────────────────────────────────────────

CARTESIA_ENDPOINT = "https://api.cartesia.ai/tts/bytes"
CARTESIA_API_VERSION = "2025-04-16"
CARTESIA_MODEL = "sonic-2"

# "Barbershop Man" — a neutral male voice from Cartesia's public library.
# Used as the fallback when neither the caller nor the env var provides one.
DEFAULT_VOICE_ID = "694f9389-aac1-45b6-b726-9d9369183238"

DEFAULT_SAMPLE_RATE = 24000
DEFAULT_MIME = "audio/wav"


# ── Request model ────────────────────────────────────────────────────


class CartesiaVoiceConfig(BaseModel):
    """Voice selection — Cartesia requires mode + id."""

    mode: str = "id"
    id: str = DEFAULT_VOICE_ID


class CartesiaOutputFormat(BaseModel):
    """Output audio format. PCM float32 in a WAV container at 24 kHz
    is the documented default for the bytes endpoint."""

    container: str = "wav"
    encoding: str = "pcm_f32le"
    sample_rate: int = DEFAULT_SAMPLE_RATE


class CartesiaTTSRequest(BaseModel):
    """Maps 1:1 to the JSON body Cartesia expects at POST /tts/bytes."""

    transcript: str
    model_id: str = CARTESIA_MODEL
    voice: CartesiaVoiceConfig = CartesiaVoiceConfig()
    output_format: CartesiaOutputFormat = CartesiaOutputFormat()

    def to_dict(self) -> dict:
        """Serialize for httpx json= parameter."""
        return self.model_dump()


# ── Header + voice helpers ───────────────────────────────────────────


def build_headers(api_key: str) -> dict[str, str]:
    """Construct the required Cartesia request headers."""
    return {
        "Cartesia-Version": CARTESIA_API_VERSION,
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }


def resolve_voice_id(
    caller_voice_id: str | None,
    env_voice_id: str | None = None,
) -> str:
    """Priority: caller argument > CARTESIA_VOICE_ID env var > hardcoded default."""
    return caller_voice_id or env_voice_id or DEFAULT_VOICE_ID
