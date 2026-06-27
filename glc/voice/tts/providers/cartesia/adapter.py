"""Cartesia Sonic TTS provider (non-streaming bytes endpoint).

Endpoint: POST https://api.cartesia.ai/tts/bytes
Returns raw WAV audio. We base64-encode it into a SynthesizeResult.

Two modes:
  - config["mock"] present  → delegate to mock (offline tests)
  - no mock                 → hit the real Cartesia API via httpx

Design decisions:
  - Connection reuse: a module-level httpx.AsyncClient avoids the cost
    of a fresh TCP+TLS handshake per call. This matters for real-time
    voice where the TTS budget is 50ms — even a 20ms TLS setup is
    40% of the budget. The client is created lazily on first call and
    reused across all subsequent calls.
  - Streaming read: we use client.stream() instead of client.post()
    so bytes start flowing into our buffer as soon as Cartesia sends
    the first chunk, rather than waiting for the entire response.
    Today we still accumulate the full buffer before returning
    (SynthesizeResult needs complete audio), but this foundation
    supports a future streaming variant where we yield chunks to the
    caller as they arrive.
  - Empty-text short-circuit: an empty transcript is legal but
    pointless — return immediately without wasting an API call.
  - Separate error paths for timeout vs request failure vs upstream
    HTTP error, so the caller (and the audit log) can distinguish
    "Cartesia is slow" from "Cartesia rejected our request" from
    "network is down".
"""

from __future__ import annotations

import base64
import os

import httpx

from glc.voice.tts.base import SynthesizeResult, TTSError, TTSProvider
from glc.voice.tts.providers.cartesia.schemas import (
    CARTESIA_ENDPOINT,
    DEFAULT_MIME,
    DEFAULT_SAMPLE_RATE,
    CartesiaTTSRequest,
    CartesiaVoiceConfig,
    build_headers,
    resolve_voice_id,
)

# Module-level client reused across calls. Created lazily on first
# synthesize(). Avoids per-call TCP+TLS handshake overhead.
_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it if needed."""
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(timeout=30.0)
    return _CLIENT


class Provider(TTSProvider):
    name = "cartesia"

    async def synthesize(self, text: str, voice_id: str | None = None) -> SynthesizeResult:
        # ---- Test path: delegate to injected mock ----
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.synthesize(text, voice_id)

        # ---- Empty-text short-circuit ----
        if not text:
            return SynthesizeResult(
                audio_b64="",
                mime=DEFAULT_MIME,
                sample_rate=DEFAULT_SAMPLE_RATE,
                provider=self.name,
                cost_usd=0.0,
            )

        # ---- Live path: call the real Cartesia API ----
        api_key = os.getenv("CARTESIA_API_KEY")
        if not api_key:
            raise TTSError("CARTESIA_API_KEY is not set", status=500)

        resolved_voice = resolve_voice_id(voice_id, os.getenv("CARTESIA_VOICE_ID"))
        headers = build_headers(api_key)
        body = CartesiaTTSRequest(
            transcript=text,
            voice=CartesiaVoiceConfig(id=resolved_voice),
        ).to_dict()

        # Stream the response so first bytes arrive as early as possible.
        # Even though we accumulate the full buffer here (SynthesizeResult
        # needs complete audio), this avoids httpx waiting for content-length
        # before handing us any data.
        audio = bytearray()
        client = _get_client()
        try:
            async with client.stream("POST", CARTESIA_ENDPOINT, headers=headers, json=body) as resp:
                if resp.is_error:
                    error_bytes = await resp.aread()
                    error_msg = error_bytes.decode("utf-8", errors="replace").strip()
                    raise TTSError(
                        f"Cartesia returned {resp.status_code}: {error_msg[:300]}",
                        status=resp.status_code,
                    )
                async for chunk in resp.aiter_bytes():
                    audio.extend(chunk)
        except TTSError:
            raise
        except httpx.TimeoutException as exc:
            raise TTSError("Cartesia request timed out", status=504) from exc
        except httpx.RequestError as exc:
            raise TTSError(f"Cartesia request failed: {exc}", status=502) from exc

        if not audio:
            raise TTSError("Cartesia returned empty audio", status=502)

        return SynthesizeResult(
            audio_b64=base64.b64encode(audio).decode("ascii"),
            mime=DEFAULT_MIME,
            sample_rate=DEFAULT_SAMPLE_RATE,
            provider=self.name,
            cost_usd=0.0,
        )
