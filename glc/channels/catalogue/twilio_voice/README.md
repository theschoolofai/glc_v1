# Twilio Voice channel adapter

Phone calls (PSTN) as a GLC channel, over **Twilio Programmable Voice**.
The adapter translates inbound calls and live caller audio into the typed
`ChannelMessage` envelope, and translates agent replies into TwiML that the
call plays back.

- Channel name: `twilio_voice`
- Slot owner: Group Twilio Voice (see `GROUPS.md`)
- Wire-format reference:
  [TwiML](https://www.twilio.com/docs/voice/twiml) ·
  [Media Streams](https://www.twilio.com/docs/voice/twiml/stream)

---

## 1. File layout

Everything for this channel lives in this directory:

```
glc/channels/catalogue/twilio_voice/
├── __init__.py     Package marker (one-line docstring).
├── adapter.py      The adapter. Inbound + outbound translation. THE entry point.
├── schemas.py      Pydantic models for the untrusted Twilio wire shapes.
├── audio.py        mu-law → PCM WAV conversion (no third-party deps).
├── signature.py    X-Twilio-Signature webhook verification (HMAC-SHA1).
├── test.py         Group-authored tests (run explicitly; outside `tests/`).
└── README.md       This file.
```

> **Optional, opt-in features** (default off, so the official tests are
> unaffected): **buffered transcription** (`buffer_audio`, §10.2) and an
> **observability hook** (`event_hook`, §6) for live monitoring/dashboards.

| File         | Holds                                                                                     |
|--------------|-------------------------------------------------------------------------------------------|
| `adapter.py` | `class Adapter(ChannelAdapter)` — `on_message()` (inbound) and `send()` (outbound).       |
| `schemas.py` | `TwilioInboundEvent`, `TwilioMediaStreamFrame`, `TwilioStreamStartFrame`, `…StopFrame`.    |
| `audio.py`   | `mulaw_to_wav()` — decodes Twilio's 8 kHz mu-law into 16 kHz mono PCM WAV for STT.         |
| `signature.py` | `verify_signature()` — HMAC-SHA1 check that a webhook genuinely came from Twilio.        |
| `test.py`    | 42 group tests reusing the official contract mock. **Must be run by explicit path** — see §9. |

It depends on these **shared** modules (owned by the project, not this slot):

| Import                                  | Used for                                              |
|-----------------------------------------|-------------------------------------------------------|
| `glc.channels.base.ChannelAdapter`      | The ABC this adapter subclasses.                      |
| `glc.channels.envelope`                 | `ChannelMessage` / `ChannelReply` — the typed contract. |
| `glc.security.trust_level.classify`     | Maps `(channel, caller)` → trust level.               |
| `glc.security.allowlists.allowed`       | Public-channel sender gating.                         |
| `glc.security.pairing.get_pairing_store`| Owner lookup for the allowlist.                       |
| `glc.voice.stt.transcribe`              | Speech-to-text facade (production path).              |

---

## 2. Where it sits in the app

The adapter is the **translation layer** between Twilio's wire format and the
gateway. It never talks to the agent directly — it only produces/consumes the
typed envelope. The gateway (`glc/routes/channels.py`) handles allowlist, rate
limiting, trust, audit, and dispatch.

```
   Twilio (PSTN)                 THIS ADAPTER                    GLC gateway
 ┌───────────────┐         ┌────────────────────────┐      ┌──────────────────┐
 │ Inbound call  │  POST   │ on_message(raw)        │      │ allowlist        │
 │ Media Streams ├────────►│   → ChannelMessage     ├─────►│ rate limit       │
 │ WebSocket     │  frames │                        │ env  │ trust / audit    │
 │               │         │                        │      │ → agent runtime  │
 │               │  TwiML  │ send(reply)            │      │                  │
 │               │◄────────┤   ← ChannelReply       │◄─────┤ ChannelReply     │
 └───────────────┘         └────────────────────────┘      └──────────────────┘
```

The adapter is auto-discovered at boot: `glc.channels.registry.discover()`
scans `glc/channels/catalogue/*/adapter.py` and registers any
`class Adapter(ChannelAdapter)`. No manual registration needed.

---

## 3. Inbound flow

A phone call is not one event — it is a sequence. `on_message()` routes by
shape: Media Streams frames carry an `event` key (`start`/`media`/`stop`);
the call webhook does not.

```
1. Caller dials in
   Twilio  ──POST call webhook (form: From, To, CallSid, CallStatus)──►  on_message()
                                                                          └─ _handle_call_webhook()
                                                                             → ChannelMessage(stage="ringing")

2. We answer with TwiML  (sent via send(), see §4)
   on_message/send  ──<Connect><Stream url=…><Parameter caller=…/>──►  Twilio
                       opens the Media Streams WebSocket

3. Stream opens
   Twilio  ──WS frame {event:"start", start:{streamSid, customParameters}}──►  on_message()
                                                                               └─ _handle_stream_start()
                                                                                  registers caller under streamSid

4. Caller speaks  (repeats every ~20 ms)
   Twilio  ──WS frame {event:"media", media:{payload=base64 mu-law}}──►  on_message()
                                                                         └─ _handle_media_frame()
                                                                            mu-law → WAV → persist → transcribe
                                                                            → ChannelMessage(voice_audio_ref, text)

5. Call ends
   Twilio  ──WS frame {event:"stop", streamSid}──►  on_message()
                                                    └─ _handle_stream_stop()
                                                       evicts the streamSid state
```

**Caller identity is tracked per `streamSid`** (`self._stream_callers`). The
gateway holds one adapter instance per channel, so concurrent calls share the
instance — a per-stream dict keeps each call's caller separate. The caller
identity reaches the (otherwise anonymous) media stream because we put it in a
`<Parameter>` on the `<Stream>`, and Twilio echoes it back in the `start` frame.

Each inbound `ChannelMessage` carries a `metadata["call_stage"]`
(`ringing` → `answered` → `completed`) so downstream can tell lifecycle
events apart from speech.

---

## 4. Outbound flow

`send(reply)` builds a TwiML document and dispatches it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>…reply text, XML-escaped…</Say>
  <Connect>
    <Stream url="wss://…/v1/channels/twilio_voice/media">
      <Parameter name="caller" value="…"/>
    </Stream>
  </Connect>
</Response>
```

- `<Say>` is included only when the reply has text; it is **XML-escaped** to
  prevent markup injection.
- `<Connect><Stream>` (re)opens the bidirectional Media Streams WebSocket so
  the conversation can continue.
- The stream URL defaults to `DEFAULT_STREAM_URL` and is overridable via
  `config["stream_url"]`.

`send()` is **reply-only** — it answers the active call. See Limitation 4.

---

## 5. The envelope it produces

`on_message()` always returns a `ChannelMessage` (canonical type in
`glc.channels.envelope`). Key fields this adapter sets:

| Field             | Source                                                              |
|-------------------|--------------------------------------------------------------------|
| `channel`         | `"twilio_voice"`                                                    |
| `channel_user_id` | Caller phone number (`From`, or the per-stream caller).            |
| `user_handle`     | `CallerName` if present, else the phone number.                    |
| `text`            | `None` for call/lifecycle events; transcript for media frames.     |
| `voice_audio_ref` | `art:<sha256>` handle for the captured audio (media frames only).  |
| `trust_level`     | From `classify()` — `owner_paired` / `user_paired` / `untrusted`. |
| `metadata`        | `call_sid`, `call_status`, `call_stage`, `stream_sid`, flags.      |

---

## 6. Trust & security model

- **Trust** is assigned by `classify(channel, caller)` against the pairing
  store. Unknown callers are `untrusted`.
- **Public channels** (`config["is_public_channel"]`) additionally run the
  caller through `allowed()`; anyone not allowlisted stays `untrusted`.
- **Malformed input never raises.** A bad call webhook collapses to a
  caller-less `untrusted` envelope; a bad Media Streams frame does the same
  (flagged `metadata["malformed_frame"]`), and a corrupt base64 audio payload
  becomes empty audio (flagged `metadata["malformed_audio"]`) rather than
  crashing the live call.
- **PII**: full phone numbers are never logged. Logs show `***1234`.
- **XML injection**: all reply text is escaped before reaching TwiML.

**Observability (`config["event_hook"]`).** Pass a callable (sync or async) and
the adapter calls it with a structured event dict at each step — `inbound`
(carrying the produced `ChannelMessage`) and `outbound` (the `ChannelReply` +
status). Use it for live monitoring, dashboards, metrics, or asserting the flow
in tests. Default `None` = no-op; a hook that raises is swallowed so monitoring
can never break a live call.

See **Limitations** for the gaps that remain on the production path
(signature enforcement wiring, artifact storage).

---

## 7. Schemas (`schemas.py`)

These model the **untrusted, external** Twilio shapes so the adapter validates
at the boundary instead of fishing through raw dicts. The canonical envelope
is **not** redefined here.

| Model                    | Wire shape it validates                                    |
|--------------------------|------------------------------------------------------------|
| `TwilioInboundEvent`     | Call webhook (`From` required; rest optional/ignored).     |
| `TwilioMediaStreamFrame` | `event:"media"` frame; nested `media.payload` is the audio.|
| `TwilioStreamStartFrame` | `event:"start"` frame; carries caller in `customParameters`.|
| `TwilioStreamStopFrame`  | `event:"stop"` frame; lets us evict per-stream state.      |

All use `extra="ignore"` — Twilio sends many more fields than we model.

---

## 8. Configuration

### Environment variables (production)

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN` — *used by `signature.py` to verify webhook authenticity (see Limitation 1)*
- `TWILIO_PHONE_NUMBER`

Twilio trial credit covers a handful of incoming/outgoing minutes.

### Adapter `config` dict

Passed by `registry.instantiate()` and by the test suite:

| Key                 | Meaning                                                                       |
|---------------------|-------------------------------------------------------------------------------|
| `mock`              | Test fake. When set, the adapter uses it instead of the wire.                 |
| `is_public_channel` | Enables allowlist gating for unknown callers.                                 |
| `stream_url`        | Overrides the Media Streams WebSocket URL in outbound TwiML.                  |
| `auth_token`        | Twilio auth token for `authenticate_webhook()` (falls back to env var).       |
| `buffer_audio`      | `True` = buffer a stream's frames and transcribe the whole utterance on `stop` (default `False` = per-frame). See Limitation 2. |
| `max_buffer_bytes`  | Buffered-mode runaway-stream cap; forces a flush past this many bytes (default ~30 s). |
| `event_hook`        | Optional callable (sync or async) called with a structured event dict at each inbound/outbound step — for live monitoring/dashboards and test assertions. Default `None` = no-op. |

---

## 9. Running the tests

```sh
# Official rubric: 6 structural + 1 behavioural
uv run pytest tests/channels/test_twilio_voice.py -v

# Group-authored tests (live in this dir, outside the default `tests/` path)
uv run pytest glc/channels/catalogue/twilio_voice/test.py -v
```

> ⚠️ **`test.py` must be named explicitly on the command line — it is *not*
> auto-collected.** pytest's default `python_files` pattern is `test_*.py` /
> `*_test.py`, and `test.py` matches neither. Pointing pytest at the directory
> (`pytest glc/channels/catalogue/twilio_voice/`) collects **zero** tests and
> exits "no tests collected" — a green-looking run that ran nothing. The
> filename is kept deliberately (the slot deliverable expects it); always invoke
> it by full path, in CI and locally, so these 42 tests actually execute.

Do **not** edit the contract mock
(`tests/channels/mocks/twilio_voice_mock.py`) or the official test file —
they are fixed.

---

## 10. Limitations

Known gaps. The test suite passes without them because the mock stands in for
the real Twilio + STT upstream — they only surface in production. **Read
before deploying.**

1. **Webhook signature is verifiable, but not yet enforced end-to-end.**
   The verifier is built and tested: `signature.py` validates the
   `X-Twilio-Signature` header (HMAC-SHA1 over the request URL + sorted POST
   params, using `TWILIO_AUTH_TOKEN`) against Twilio's published test vector,
   and `Adapter.authenticate_webhook(form, url=..., signature=...)` is the
   ready entry point. What is missing is the *caller*: the signature is an HTTP
   header that arrives in the deployment web layer (outside this repo), which
   must call `authenticate_webhook()` and reject (HTTP 403) before handing the
   form to `on_message`. Until that layer is wired, inbound trust still rests
   on the `From` field — anyone who learns the webhook URL can POST
   `From=<owner number>` and be classified `owner_paired`. **Wire the web
   layer to `authenticate_webhook()` before exposing the webhook publicly.**

2. **Per-frame transcription by default; buffered mode is opt-in.**
   A `media` frame is ~20 ms of audio — far too short to transcribe into words,
   and transcribing every frame would mean ~50 STT calls/second (cost + rate
   limits). The adapter supports a **buffered mode** that accumulates a stream's
   frames and transcribes the whole utterance once, flushing on the `stop` frame
   (or earlier if `max_buffer_bytes` is exceeded — a runaway-stream cap).

   Enable it via config: `{"buffer_audio": True}` (optional `max_buffer_bytes`,
   default ~30 s of 8 kHz mu-law). It is **off by default** on purpose: the
   official behavioural test (`test_channel_specific_behaviour_call_to_twiml_then_media`)
   sends a single `media` frame and asserts the returned `ChannelMessage`
   already carries the transcript, which only the per-frame path satisfies.
   Buffered mode is covered by group-authored tests in `test.py` (frames defer;
   `stop` flushes and transcribes once; the byte cap forces an early flush).
   Real-time silence/VAD-based flushing mid-call remains S12 work.

3. **The artifact handle is fabricated on the production path.**
   With no mock present, the adapter returns an `art:<sha>` handle but does not
   yet store the bytes — the real gateway artifact store lands in S12. Until
   then, `voice_audio_ref` on the production path does not resolve.

4. **`send()` is reply-only.**
   It answers the active call and only *warns* (does not block) when the
   recipient is unpaired, because the caller dialed in and the channel is
   already open. It must **not** be reused to *initiate* a new outbound call:
   dialing a number is a separate path that must gate on pairing/trust first.
