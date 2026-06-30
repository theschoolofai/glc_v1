# twilio_voice — handoff

Handoff notes for anyone picking up the **twilio_voice** channel (teammate,
reviewer, or future-you). The [README](README.md) is the full reference; this
doc is the "what state is it in, why these choices, and what's left" summary.

---

## 1. Status

| Item | State |
|------|-------|
| Adapter (`on_message` / `send`) | ✅ complete |
| Official suite `tests/channels/test_twilio_voice.py` | ✅ 7/7 (6 structural + 1 behavioural) |
| Group suite `test.py` | ✅ 42/42 |
| `ruff check` · `ruff format --check` · `mypy` | ✅ clean on the slot |
| Boundary (only touches `glc/channels/catalogue/twilio_voice/**`) | ✅ |
| Production-hardened beyond the rubric | ✅ signature verify, mu-law→WAV, fail-closed parsing, opt-in buffering, observability hook |

Owned path: `glc/channels/catalogue/twilio_voice/**` only. Anything outside it
needs a separate, `@theschoolofai`-reviewed PR.

---

## 2. Files

| File | Purpose |
|------|---------|
| `adapter.py` | `class Adapter(ChannelAdapter)` — inbound `on_message()` + outbound `send()`. The entry point. |
| `schemas.py` | Pydantic models for the untrusted Twilio wire shapes (call webhook + Media Streams frames). |
| `audio.py` | `mulaw_to_wav()` — G.711 mu-law (8 kHz) → 16 kHz mono PCM WAV. Hand-rolled decode table; **no `audioop`** (removed in Py 3.13) and no third-party deps. |
| `signature.py` | `verify_signature()` / `expected_signature()` — `X-Twilio-Signature` HMAC-SHA1 check. |
| `test.py` | 42 group tests against the official contract mock. Run by **explicit path** (see §5). |
| `README.md` | Full reference (flows, config, schemas, limitations). |
| `HANDOFF.md` | This file. |

---

## 3. How it works (1-minute version)

**Inbound:** a call hits a webhook → adapter answers with **TwiML** that opens a
Media Streams WebSocket → caller audio arrives as base64 **mu-law** frames →
adapter converts to **WAV** (`audio.py`) and transcribes via the STT facade →
returns a typed `ChannelMessage` (with `trust_level`, transcript, `voice_audio_ref`).

**Outbound:** agent text → `send()` wraps it in TwiML `<Say>` (XML-escaped) +
re-opens the stream → returned as the webhook response.

**Caller identity** is tracked per `streamSid` (the media stream is otherwise
anonymous; we pass the caller as a `<Parameter>` and Twilio echoes it on the
`start` frame). Concurrent calls stay isolated.

See README §3–§5 for the full sequence diagrams.

---

## 4. Key design decisions (the "why")

- **mu-law → WAV in the adapter** (`audio.py`). Twilio sends headerless 8 kHz
  mu-law; Whisper-class STT wants a WAV/PCM container at 16 kHz. WAV is the
  universal STT input, so converting here keeps the adapter provider-agnostic.
  Hand-rolled (no `audioop`) so it survives Python 3.13+.
- **Fail-closed parsing.** Malformed webhooks/frames/payloads never raise — they
  collapse to an `untrusted`, caller-less envelope (flagged in `metadata`) so a
  bad packet can't tear down a live call. Mirrors the rubric's disconnect rule.
- **Signature verify built, enforcement deferred.** `signature.py` +
  `authenticate_webhook()` are done and tested against Twilio's published vector,
  but the HTTP layer that holds the `X-Twilio-Signature` header lives outside
  this repo, so end-to-end enforcement is a deployment step (see §6.1).
- **Per-frame by default; buffering opt-in.** The official behavioural test sends
  one media frame and expects an immediate transcript, so per-frame must stay the
  default. Buffering is a config flag (see §6.2).
- **Observability via a hook, not a bundled server.** A channel adapter is a
  library, not a web app — so monitoring is exposed as an optional `event_hook`
  callback rather than shipping a dashboard inside the slot.

---

## 5. Build / test / lint

```sh
# official rubric (must stay green)
uv run pytest tests/channels/test_twilio_voice.py -v

# group tests — MUST be given by explicit path (filename `test.py` is not
# auto-collected by pytest's default test_*.py pattern; pointing at the dir
# collects ZERO tests and exits green-but-empty)
uv run pytest glc/channels/catalogue/twilio_voice/test.py -v

# lint + types (slot only)
uv run ruff check glc/channels/catalogue/twilio_voice/
uv run ruff format --check glc/channels/catalogue/twilio_voice/
uv run mypy glc/channels/catalogue/twilio_voice/
```

Do **not** edit the official test file or the contract mock
(`tests/channels/mocks/twilio_voice_mock.py`) — they are fixed.

---

## 6. What's left / how to take it to production

### 6.1 Enforce webhook signatures (highest priority)
Today inbound trust rests on the `From` field, which is spoofable. The verifier
is ready; the deployment HTTP layer must call
`adapter.authenticate_webhook(form, url=<full request URL>, signature=<X-Twilio-Signature header>)`
and reject with HTTP 403 before passing the form to `on_message`. Set
`TWILIO_AUTH_TOKEN` (or `config["auth_token"]`). **Do this before exposing the
webhook publicly.**

### 6.2 Buffered transcription (opt-in, already implemented)
Set `config["buffer_audio"] = True` to accumulate a stream's frames and
transcribe the whole utterance once, flushing on the `stop` frame (or past
`max_buffer_bytes`, default ~30 s). Real-time silence/VAD flushing mid-call is
still future (S12) work.

### 6.3 Artifact store
On the non-mock path `voice_audio_ref` is an `art:<sha>` handle but the bytes
aren't persisted yet — that lands when the gateway artifact store ships (S12).

### 6.4 Outbound call initiation
`send()` is reply-only (answers the active call). Dialing a *new* number is a
separate path that must gate on pairing/trust first — not implemented.

### 6.5 Real STT/TTS providers
The STT providers (`groq_whisper`, `whisper_cpp`, …) are other groups' slots and
are still stubs; the adapter's production transcription path depends on them.

---

## 7. Config quick reference

| Key | Default | Meaning |
|-----|---------|---------|
| `mock` | — | Test fake; when set, used instead of the real wire. |
| `is_public_channel` | `False` | Enable allowlist gating for unknown callers. |
| `stream_url` | localhost wss | Media Streams WebSocket URL put in outbound TwiML. |
| `auth_token` | env `TWILIO_AUTH_TOKEN` | Token for `authenticate_webhook()`. |
| `buffer_audio` | `False` | Buffer frames; transcribe the utterance on `stop`. |
| `max_buffer_bytes` | ~30 s | Buffered-mode runaway-stream flush cap. |
| `event_hook` | `None` | Callable (sync/async) → structured event per step. |

---

## 8. Live demo (not part of the repo)

The end-to-end demo (real phone call → live AI conversation) runs through a
**separate throwaway host** that wraps this adapter — it is intentionally **not**
committed (it's deployment/demo glue, outside the slot). To reproduce it:

- A small FastAPI app exposes `POST /voice` (returns the adapter's TwiML) and a
  `WS /media` (feeds frames to `adapter.on_message`).
- It buffers frames, transcribes via real **Groq Whisper**, gets a reply from an
  LLM, and streams speech back (macOS `say` → mu-law) over the same socket.
- Exposed publicly with **ngrok**; the Twilio number's voice webhook points at it.
- A dashboard subscribes to the adapter's `event_hook` to show each step live.

**Security:** the demo uses real Twilio + Groq credentials in a local `.env`
(never committed). Rotate any keys that were shared during development.

---

## 9. Gotchas

- `test.py` is **not** auto-collected — always run it by full path (§5).
- Don't reintroduce changes outside `glc/channels/catalogue/twilio_voice/**` or
  the boundary check fails the PR.
- `DEFAULT_STREAM_URL` is `localhost` — override via `stream_url` in production
  (Twilio's cloud can't reach localhost).
