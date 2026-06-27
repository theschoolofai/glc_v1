# Cartesia Sonic — streaming TTS provider

Slot: `cartesia` · Route: `POST /v1/speak?prefer=streaming`

## What this does

Converts text to speech using [Cartesia's Sonic](https://docs.cartesia.ai/api-reference/tts/bytes) model. Designed for the real-time voice path — phone calls via Twilio Voice, WebUI voice mode — where the TTS budget is ≤50ms time-to-first-audio.

## Setup

```sh
# 1. Get a free API key at https://play.cartesia.ai/keys
# 2. Add to your .env:
CARTESIA_API_KEY=sk_car_...

# Optional — defaults to "Barbershop Man" neutral voice
CARTESIA_VOICE_ID=694f9389-aac1-45b6-b726-9d9369183238
```

No API keys are needed to run the test suite. Tests use an injected mock and never hit the network.

## Quick test

```sh
# Run the 7 provider tests
uv run pytest tests/voice/tts/test_cartesia.py -v

# Live test (gateway must be running)
uv run glc serve
curl -X POST http://localhost:8111/v1/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from Cartesia Sonic", "prefer": "streaming"}'
```

## Architecture

```
POST /v1/speak?prefer=streaming
    → routes/speak.py
    → tts/router.py (resolves "streaming" → "cartesia")
    → Provider.synthesize(text, voice_id)
        ├── mock present?  → delegate to mock (tests)
        ├── empty text?    → short-circuit, return silent result
        └── live path      → httpx.stream() to Cartesia /tts/bytes
                           → accumulate audio chunks
                           → base64-encode → SynthesizeResult
```

### File layout

| File          | Responsibility                                                |
|---------------|---------------------------------------------------------------|
| `schemas.py`  | Cartesia API contract — endpoint, headers, Pydantic request model, defaults |
| `adapter.py`  | Orchestration — mock routing, HTTP client, error handling     |

Changing the API version or endpoint URL only touches `schemas.py`.

## Wire-format details

| Item             | Value                                          |
|------------------|------------------------------------------------|
| Endpoint         | `POST https://api.cartesia.ai/tts/bytes`       |
| Version header   | `Cartesia-Version: 2025-04-16` (required)      |
| Auth header      | `X-API-Key: <key>` (not `Authorization: Bearer`) |
| Model            | `sonic-2`                                      |
| Output           | PCM float32, WAV container, 24 kHz mono        |
| Response         | Raw audio bytes (not JSON)                     |

**Note:** The auth header format differs from most providers — it's `X-API-Key`, not a Bearer token.

## Design decisions

**Connection reuse.** A module-level `httpx.AsyncClient` persists across calls, avoiding per-call TLS handshake overhead. Created lazily on first use, recreated if closed.

**Streaming reads.** Uses `client.stream()` instead of `client.post()` so audio bytes start flowing as soon as Cartesia sends the first chunk. The full buffer is still accumulated before returning (the `SynthesizeResult` contract requires complete audio), but this avoids blocking until content-length is satisfied.

**Empty-text short-circuit.** Returns immediately with an empty result instead of making a pointless API call.

**Granular error handling.** Three distinct failure paths so callers and the audit log can tell them apart:

| Error type       | Status | Meaning                              |
|------------------|--------|--------------------------------------|
| `TTSError(429)`  | 429    | Rate limited — caller can fall back  |
| `TTSError(504)`  | 504    | Timeout — Cartesia is slow, may retry |
| `TTSError(502)`  | 502    | Connection failure or empty response |
| `TTSError(4xx)`  | 4xx    | Bad request (invalid voice ID, etc.) |

**Voice resolution.** Priority: caller argument → `CARTESIA_VOICE_ID` env var → hardcoded default.

## Tests

Seven tests in `tests/voice/tts/test_cartesia.py`:

| # | Test | Verifies |
|---|------|----------|
| 1 | `test_provider_name_matches` | `name == "cartesia"` |
| 2 | `test_synthesize_returns_synthesize_result` | Return type, provider, non-empty audio, sample rate |
| 3 | `test_synthesize_passes_text_to_upstream` | Input text reaches upstream unchanged |
| 4 | `test_synthesize_records_sample_rate` | Sample rate passed through, not hardcoded |
| 5 | `test_synthesize_propagates_upstream_error` | HTTP 502 surfaces as `TTSError(status=502)` |
| 6 | `test_synthesize_handles_empty_text` | Empty string produces valid result |
| 7 | `test_time_to_first_audio` | TTFA under 200ms (mock threshold) |

## Integration context

This provider does not participate in trust-level classification — that happens at Stage 2 of the trust cascade, in the channel adapter. By the time `synthesize()` is called, the policy engine (Stage 3) has already authorized the agent's action. The audit log (Stage 5) records the TTS call under `agent: channel:<name>` for cost tracking.

## Limitations

- **Non-streaming output only.** The WebSocket endpoint (`wss://api.cartesia.ai/tts/websocket`) supports true chunk-by-chunk streaming but is out of scope for S11.
- **No cost tracking yet.** `cost_usd` returns `0.0`. Cartesia's credit-based pricing would need a character-count estimator to populate this accurately.
- **Free-tier concurrency.** Limited to 1 parallel request. Production deployments should upgrade or add retry logic with fallback to `system_fallback`.
