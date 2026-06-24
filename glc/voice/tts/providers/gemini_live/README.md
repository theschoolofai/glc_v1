# Gemini Live TTS (realtime full-duplex)

Slot: `gemini_live_tts` — owned by Group Gemini Live TTS.

Implements the realtime full-duplex TTS bridge using Google's
`BidiGenerateContent` WebSocket. The same wire format will eventually
carry the matching STT leg in one session; for S11 the `synthesize()`
surface is non-streaming and the WebUI voice-mode integration opens
its own session through this provider in S12.

## Architecture

One WebSocket, one turn per `synthesize()` call:

1. Open `wss://generativelanguage.googleapis.com/.../BidiGenerateContent?key=...`.
2. Send the **setup frame** with `responseModalities: ["AUDIO"]`. This
   is the single most load-bearing line in the adapter — defaulting to
   `TEXT` produces zero audio and zero error, just an empty result.
3. Drain the server's `setupComplete` ack before sending content.
4. Send one `clientContent` frame with the user text and
   `turnComplete: true` so the server starts replying immediately.
5. Stream-read `serverContent.modelTurn.parts[].inlineData.data`
   (base64 PCM) until the server flips `turnComplete`.
6. Concatenate PCM chunks, wrap once in a WAV header, return a
   `SynthesizeResult` with `audio_b64`, `mime=audio/wav`, and the
   sample rate the server actually used.

The adapter is testable without the network: tests inject a mock via
`config={"mock": ...}` that records the setup frame and returns canned
audio, so the seven structural + behavioural tests run offline.

## Required environment

- `GEMINI_API_KEY` — appended as a `?key=` query param. The adapter
  raises `TTSError(status=401)` if it's missing.

## Cost accounting

The server interleaves `usageMetadata` frames carrying token counts. The
read loop keeps the last one and `schemas.cost_from_usage()` turns it into an
estimate: text prompt tokens at the input rate, the audio response at the
audio-output rate. This populates `SynthesizeResult.cost_usd`, which the
dispatcher returns as `SpeakResponse.cost_usd` from `POST /v1/speak`.

`cost_usd` is a **list-price estimate** from the reported token counts, not
what you are actually billed (the free tier bills $0). If no `usageMetadata`
frame arrives, it stays `0.0`.

Rates are USD per 1M tokens, overridable via env:

- `GEMINI_LIVE_INPUT_USD_PER_MTOK` — text input (default `1.00`).
- `GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK` — audio output (default `20.00`).

Source: <https://ai.google.dev/gemini-api/docs/pricing> (verified 2026-06-23).

## Channel quirks we hit

- **`responseModalities` defaults to TEXT.** No error, no warning,
  just no audio. This is *the* gotcha for Gemini Live — and the one
  thing the behavioural test exists to catch.
- **Audio is raw PCM, not WAV.** Each `inlineData.data` is base64
  PCM with a `mimeType` like `audio/pcm;rate=24000`. We parse the
  rate out of the mimeType (it may not always be 24 kHz), concatenate
  the chunks, then synthesize a WAV header ourselves with the stdlib
  `wave` module. No temp files — everything stays in memory.
- **`setupComplete` must be drained.** Sending the content frame
  before reading the ack works on some runs and stalls on others.
  One blocking `await ws.recv()` between setup and content frames
  is the cheapest fix.
- **Live-API model names are not TTS-preview model names.** Only
  models listed under "Live API: Supported" accept the
  `BidiGenerateContent` protocol. `gemini-3.1-flash-tts-preview`
  (and friends) silently fail to upgrade the WebSocket; we pin
  `models/gemini-3.1-flash-live-preview`.
- **The session is full-duplex by design.** The server interleaves
  partial audio responses with empty-`serverContent` keepalive
  frames and usage-metadata frames. The read loop skips anything
  without `serverContent.modelTurn` and stops on the first
  `turnComplete: true`.

## How our tests exercise the behavioural boundary

Seven tests live at `tests/voice/tts/test_gemini_live.py`. Six are
structural (provider name, return shape, text propagation, sample
rate, error propagation, empty text). The seventh —
`test_channel_specific_behaviour_response_modalities_audio` — is
the load-bearing one: it asserts the setup frame the adapter sends
declares `responseModalities=["AUDIO"]`.

This is the voice-provider analogue of the trust-level boundary the
channel adapters guard. If the next person edits the setup frame and
omits `responseModalities`, the structural tests still pass — the
mock happily returns canned audio — but every real call would come
back silent. The behavioural test is the only thing standing
between us and that regression.

## Running it for real (demo)

```sh
export GEMINI_API_KEY=...                  # PowerShell: $env:GEMINI_API_KEY="..."
uv run python -m glc.voice.tts.providers.gemini_live.smoke "hello from glc"
```

`smoke.py` calls the real adapter (no mock), writes the resulting WAV to
`gemini_live_out.wav` in the OS temp dir (`%TEMP%` on Windows, `/tmp` or
`$TMPDIR` on macOS/Linux), and prints provider metadata, the estimated
`cost_usd`, and three latency numbers (`total_ms`, `audio_ms`,
`realtime_factor`). Play back the path shown on the `wrote:` line:

```sh
afplay "$TMPDIR/gemini_live_out.wav"        # macOS
aplay  /tmp/gemini_live_out.wav             # Linux
start  "%TEMP%\gemini_live_out.wav"         # Windows (or: ffplay <path>)
```

Measured against the real Gemini Live free tier with the input
*"hello from glc"* (Windows):

```
provider:        gemini_live
mime:            audio/wav
sample_rate:     24000 Hz
cost_usd:        0.002323
wav_bytes:       195,406
total_ms:         5407.6
audio_ms:         4070.0
realtime_factor:    0.75x
wrote:           <os-temp-dir>\gemini_live_out.wav
```

`cost_usd` is the list-price estimate from the turn's `usageMetadata` (see
[Cost accounting](#cost-accounting)). `realtime_factor < 1` means
`synthesize()` returned slower than the audio plays — because it waits for
the *full* turn before returning; short clips are dominated by fixed
round-trip overhead. The sub-second voice budget in §9 needs a streaming
surface that yields chunks as they arrive; that surface is a future PR on
top of this provider.
