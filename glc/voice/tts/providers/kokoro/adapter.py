"""Kokoro-82M local TTS provider (GLC v1 `prefer="default"`).

Kokoro is the daily-driver text-to-speech path: open weights, 82M
parameters, runs faster than realtime on a laptop CPU, no API key, no
network egress, zero per-call cost. That is exactly the posture GLC v1
wants for the default voice — local-first and free (Session 11 §7).

Two execution paths share one code path:

* **Test / injected path** — when the gateway (or the test suite) passes
  a fake upstream as ``config["mock"]``, every call is delegated to it.
  This is how the seven CI tests drive the adapter against the recorded
  Kokoro wire behaviour without downloading ~300 MB of weights.

* **Real path** — with no mock, synthesis is delegated to
  :mod:`glc.voice.tts.providers.kokoro.runner`, which lazy-loads the
  ``KPipeline`` exactly once (module-level singleton) and reuses it for
  every subsequent call. Loading the pipeline pulls the model into RAM;
  re-loading per call would burn that cost on every utterance. Load
  once, reuse — that is the one behaviour the channel-specific test
  asserts.

The agent runtime never sees raw float32 frames — only the typed
``SynthesizeResult`` envelope from :mod:`glc.voice.tts.base`.
"""

from __future__ import annotations

import base64

from glc.voice.tts.base import SynthesizeResult, TTSProvider

# Kokoro's default open-weights voice. Short ids like af_bella, af_sky,
# am_adam select a voice from the bundled palette.
DEFAULT_VOICE_ID = "af_bella"


class Provider(TTSProvider):
    """TTS provider that turns text into a base64 WAV ``SynthesizeResult``."""

    name = "kokoro"

    async def synthesize(self, text: str, voice_id: str | None = None) -> SynthesizeResult:
        # Test / gateway-injected upstream. The mock owns pipeline-load
        # accounting, so delegating keeps the load count at exactly one
        # across calls and lets the structural tests assert on it.
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.synthesize(text, voice_id)

        # Real local synthesis. The runner caches the KPipeline in a
        # module global, so the model is loaded once and reused for the
        # life of the process — no re-load per call.
        from glc.voice.tts.providers.kokoro import runner

        voice = voice_id or DEFAULT_VOICE_ID
        wav_bytes, sample_rate = runner.synthesize(text, voice)
        return SynthesizeResult(
            audio_b64=base64.b64encode(wav_bytes).decode("ascii"),
            mime="audio/wav",
            sample_rate=sample_rate,
            provider=self.name,
            cost_usd=0.0,
        )
