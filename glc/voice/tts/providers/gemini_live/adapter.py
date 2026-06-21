"""Provider for Gemini Live realtime full-duplex TTS (BidiGenerateContent WebSocket)."""

from __future__ import annotations

# SynthesizeResult: the return type every TTS provider must produce.
# TTSError: the exception every TTS provider must raise on failure (carries an HTTP status).
# TTSProvider: the abstract base class this Provider implements.
from glc.voice.tts.base import SynthesizeResult, TTSProvider, TTSError

#code_start
import base64  # decode the base64 audio chunks the server sends back
import io      # in-memory buffer, used to build the WAV file without touching disk
import json    # encode/decode the JSON frames sent over the websocket
import os      # read GEMINI_API_KEY from the environment
import wave    # stdlib helper to wrap raw PCM bytes into a valid .wav container

import websockets  # the websocket client library used to talk to Gemini Live

# Which Gemini model to use. Must be one of the "Live API: Supported" models
# (verified against the real API) — TTS-only models like gemini-3.1-flash-tts-preview
# do NOT work here because they don't support the websocket protocol at all.
GEMINI_LIVE_MODEL = "models/gemini-3.1-flash-live-preview"

# The fixed websocket endpoint for Gemini's BidiGenerateContent API.
# The API key gets appended as a query param when we actually connect.
GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
#code_end

class Provider(TTSProvider):
    name = "gemini_live"  # used by the router to identify this provider in PREFER_TO_PROVIDER
    #code_start
    def _setup_frame(self) -> dict:
        # The very first message any Gemini Live session must send.
        # responseModalities=["AUDIO"] is the critical flag — without it the
        # server defaults to TEXT and you get zero audio back.
        return {
            "setup": {
                "model": GEMINI_LIVE_MODEL,
                "generationConfig": {"responseModalities": ["AUDIO"]},
            }
        }
    #code_end
    async def synthesize(self, text: str, voice_id: str | None = None) -> SynthesizeResult:
        # Build the setup frame once; both the mock path and the real path need it.
        setup_frame = self._setup_frame()

        # Tests inject a fake "mock" object into self.config so they never touch
        # the real network. Production code never sets this, so mock is None there.
        mock = self.config.get("mock")

        if mock is not None:
            # Let the mock record what setup frame we would have sent — this is
            # what the behavioural test checks (responseModalities == ["AUDIO"]).
            mock.record_frame(setup_frame)
            # Mock returns a canned SynthesizeResult (or raises TTSError if the
            # test configured rate_limited / upstream_failure). No network call happens.
            return await mock.synthesize(text, voice_id)

        # No mock configured -> this is a real call, go talk to the actual API.
        return await self._synthesize_live(text, setup_frame)

    async def _synthesize_live(self, text: str, setup_frame: dict) -> SynthesizeResult:
        # Read the API key from the environment. Never hardcode it.
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Fail fast and loud with a 401 if the key isn't configured.
            raise TTSError("GEMINI_API_KEY is not set", status=401)

        # Build the full connection URL with the key as a query param.
        url = f"{GEMINI_LIVE_WS_URL}?key={api_key}"

        # Audio arrives in many small chunks over the course of the session;
        # collect them here and concatenate once the turn is done.
        pcm_chunks: list[bytes] = []
        # Default sample rate; gets overwritten if the server's mimeType says otherwise.
        sample_rate = 24000

        try:
            # Open the websocket connection. `async with` guarantees it closes
            # automatically even if an exception is raised inside the block.
            async with websockets.connect(url) as ws:
                # Step 1: send the setup frame — must happen before anything else.
                await ws.send(json.dumps(setup_frame))
                # Step 2: wait for the server's setupComplete acknowledgement
                # before sending any content (we don't inspect its contents here).
                await ws.recv()  # setupComplete

                # Step 3: send the actual text we want spoken, as a single
                # user turn, and mark the turn complete so the server starts replying.
                content_frame = {
                    "clientContent": {
                        "turns": [{"role": "user", "parts": [{"text": text}]}],
                        "turnComplete": True,
                    }
                }
                await ws.send(json.dumps(content_frame))

                # Step 4: read server messages in a loop until the server tells
                # us the turn is complete (it streams audio in small pieces).
                async for raw in ws:
                    msg = json.loads(raw)
                    server_content = msg.get("serverContent")
                    if not server_content:
                        # Frames without serverContent (e.g. empty acks) are skipped.
                        continue

                    model_turn = server_content.get("modelTurn")
                    if model_turn:
                        # Each part may contain a base64-encoded chunk of raw PCM audio.
                        for part in model_turn.get("parts", []):
                            inline = part.get("inlineData")
                            if inline and inline.get("data"):
                                # Decode this chunk from base64 back to raw bytes and store it.
                                pcm_chunks.append(base64.b64decode(inline["data"]))
                                # mimeType looks like "audio/pcm;rate=24000" — pull the
                                # real sample rate out of it in case it ever differs.
                                mime_type = inline.get("mimeType", "")
                                if "rate=" in mime_type:
                                    sample_rate = int(mime_type.rsplit("rate=", 1)[-1])

                    if server_content.get("turnComplete"):
                        # Server signals it's done speaking — stop reading and exit the loop.
                        break
        except (OSError, websockets.exceptions.WebSocketException) as e:
            # Any network-level or websocket-protocol failure becomes a 502
            # TTSError so the caller (the router/route) can report it cleanly.
            raise TTSError(f"gemini_live upstream error: {e}", status=502) from e

        # Join all the streamed PCM chunks into one continuous byte blob,
        # then wrap it in a proper WAV header so it's playable by normal tools.
        wav_bytes = self._pcm_to_wav(b"".join(pcm_chunks), sample_rate)

        # Return the standard SynthesizeResult shape every provider must produce.
        return SynthesizeResult(
            audio_b64=base64.b64encode(wav_bytes).decode("ascii"),  # re-encode final WAV as base64 for transport
            mime="audio/wav",
            sample_rate=sample_rate,
            provider=self.name,
            cost_usd=0.0,  # Gemini Live has no per-call cost tracked here
        )

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        # Raw PCM has no header/metadata — wrapping it in a WAV container
        # lets any standard audio player (afplay, browsers, etc.) read it.
        buf = io.BytesIO()  # write the WAV bytes into memory, not a temp file
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)        # Gemini Live audio is mono
            wf.setsampwidth(2)        # 16-bit samples = 2 bytes per sample
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)       # the actual audio data
        return buf.getvalue()
