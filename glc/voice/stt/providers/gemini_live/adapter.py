"""Gemini Live (streaming voice in via WebSocket) STT provider.

Google's BidiGenerateContent endpoint is full-duplex: the client opens a
WebSocket, sends a `BidiGenerateContentSetup` frame *first*, then streams
audio, and reads transcript chunks back until the server emits
`turnComplete`.

This module has two paths:

* ``_transcribe_via_mock`` — used by the CI test-suite. When
  ``config["mock"]`` is present the adapter talks to the in-repo fake in
  ``tests/voice/stt/mocks/gemini_live_mock.py`` instead of the network.
  This is the path the 7 tests exercise.

* ``_transcribe_via_websocket`` — the real upstream call used outside the
  tests (e.g. for the demo video). CI never runs it.

Both paths obey the same wire rule: the ``setup`` frame is always sent
before the audio frame.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from glc.voice.stt.base import STTError, STTProvider, TranscribeResult

# Default Gemini Live model + endpoint. Overridable via ``config``.
_DEFAULT_MODEL = "models/gemini-2.0-flash-live-001"
_WS_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)


class Provider(STTProvider):
    name = "gemini_live"

    # ── public entry point ─────────────────────────────────────────
    async def transcribe(self, audio: bytes, mime: str) -> TranscribeResult:
        """Turn an audio clip into text.

        Picks the fake transport when a mock is injected (tests), and the
        real WebSocket transport otherwise.
        """
        mock = self.config.get("mock")
        if mock is not None:
            return await self._transcribe_via_mock(mock, audio, mime)
        return await self._transcribe_via_websocket(audio, mime)

    # ── frame builders (shared by both paths) ──────────────────────
    def _build_setup_frame(self) -> dict[str, Any]:
        """The BidiGenerateContentSetup frame. Must be sent first."""
        model = self.config.get("model", _DEFAULT_MODEL)
        modalities = self.config.get("response_modalities", ["TEXT"])
        return {"setup": {"model": model, "responseModalities": modalities}}

    def _build_audio_frame(self, audio: bytes, mime: str) -> dict[str, Any]:
        """The realtimeInput frame carrying the (base64) audio payload."""
        encoded = base64.b64encode(audio).decode("ascii")
        return {
            "realtimeInput": {
                "mediaChunks": [{"mimeType": mime, "data": encoded}],
            }
        }

    # ── mock path (what CI exercises) ──────────────────────────────
    async def _transcribe_via_mock(
        self, mock: Any, audio: bytes, mime: str
    ) -> TranscribeResult:
        """Drive the in-repo fake upstream.

        Order matters: the setup frame is recorded before the audio frame
        so ``frames_sent[0]`` is always the setup frame (the Live API
        rejects sessions where audio arrives first).
        """
        mock.record_frame(self._build_setup_frame())
        mock.record_frame(self._build_audio_frame(audio, mime))
        # The fake returns a canned TranscribeResult or raises STTError;
        # let the error propagate untouched.
        return await mock.transcribe(audio, mime)

    # ── real path (for the demo; not run by CI) ────────────────────
    async def _transcribe_via_websocket(
        self, audio: bytes, mime: str
    ) -> TranscribeResult:
        """Real Gemini Live call over the BidiGenerateContent WebSocket.

        TODO(Pod 2 — real WebSocket): implement using the ``websockets``
        dependency already in pyproject.toml. Flow:

          1. Open ``{_WS_ENDPOINT}?key=$GEMINI_API_KEY``.
          2. Send ``_build_setup_frame()`` as the FIRST frame (json).
          3. Send ``_build_audio_frame(audio, mime)``.
          4. Read messages, accumulating text from
             ``serverContent.modelTurn.parts[].text``; ignore
             ``usageMetadata`` frames. Stop on ``turnComplete``.
          5. Close the socket; wrap any failure in ``STTError(msg, status)``.
          6. Return ``TranscribeResult(text=..., language="en",
             duration_ms=elapsed, provider=self.name)``.

        The ``_start`` timing below is the skeleton to fill in.
        """
        _start = time.monotonic()
        del audio, mime, _start  # placeholders until Pod 2 implements
        raise STTError(
            "Real Gemini Live WebSocket path not implemented yet "
            "(Pod 2). Tests use the mock path; see README.md.",
            status=None,
        )
