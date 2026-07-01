"""Group-authored tests for the twilio_voice adapter.

This file lives in the adapter's own folder, so it is OUTSIDE the
project's `testpaths = ["tests"]`. Run it explicitly:

    uv run pytest glc/channels/catalogue/twilio_voice/test.py -v

It reuses the contract mock from tests/channels/mocks/twilio_voice_mock.py
(the same fake the official suite runs against).
"""

from __future__ import annotations

import base64
import io
import logging
import wave
from datetime import datetime
from typing import Any

import pytest

from glc.channels.catalogue.twilio_voice import audio as tv_audio
from glc.channels.catalogue.twilio_voice import signature as tv_sig
from glc.channels.catalogue.twilio_voice.adapter import Adapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from glc.voice.stt.base import TranscribeResult
from tests.channels.mocks.twilio_voice_mock import (
    OWNER_ID,
    STRANGER_ID,
    STREAM_SID,
    TwilioVoiceMock,
)

ADAPTER_LOGGER = "glc.channels.catalogue.twilio_voice.adapter"


@pytest.fixture(autouse=True)
def _isolated_pairing(monkeypatch, tmp_path):
    """Replicate the isolation tests/conftest.py gives the official suite.

    Our file is outside tests/, so we don't inherit that autouse fixture.
    Point the pairing DB at a temp file and reset the cached singleton so
    each test starts from an empty pairing table and never touches ~/.glc.
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("GLC_PAIRING_DB", str(tmp_path / "pairings.sqlite"))

    import glc.config as _cfg

    _cfg.CONFIG_DIR = cfg
    import glc.security.pairing as _p

    _p._singleton = None
    yield
    _p._singleton = None


@pytest.fixture
def mock():
    return TwilioVoiceMock()


@pytest.fixture
def owner_paired():
    get_pairing_store().force_pair_owner("twilio_voice", OWNER_ID, user_handle="owner")
    return OWNER_ID


def _call_event(
    *, from_phone: str = OWNER_ID, status: str = "ringing", caller_name: str | None = None
) -> dict[str, Any]:
    """A minimal Twilio call webhook. Mirrors the mock's wire shape but lets
    us vary fields (status, missing From) the mock helpers keep fixed."""
    ev: dict[str, Any] = {
        "CallSid": "CAtest0000000000000000000000000001",
        "To": "+15555550100",
        "Direction": "inbound",
        "CallStatus": status,
    }
    if from_phone is not None:
        ev["From"] = from_phone
    if caller_name is not None:
        ev["CallerName"] = caller_name
    return ev


def _start_event(stream_sid: str, caller: str, handle: str = "caller") -> dict[str, Any]:
    """A Media Streams `start` frame carrying the caller in customParameters
    (what real Twilio echoes back from our <Stream><Parameter>)."""
    return {
        "event": "start",
        "start": {
            "streamSid": stream_sid,
            "callSid": "CA" + stream_sid,
            "customParameters": {"caller": caller, "handle": handle},
        },
    }


def _media_event(stream_sid: str, audio: bytes = b"\xff\x7f" * 50) -> dict[str, Any]:
    """A Media Streams `media` frame on a chosen stream (lets us simulate
    several concurrent streams, which the mock's single-stream helper can't)."""
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"track": "inbound", "payload": base64.b64encode(audio).decode()},
    }


def _stop_event(stream_sid: str) -> dict[str, Any]:
    return {"event": "stop", "streamSid": stream_sid}


# --------------------------------------------------------------------------
# Inbound translation
# --------------------------------------------------------------------------


async def test_inbound_owner_call_builds_full_envelope(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(mock.queue_owner_message("ringing"))

    assert isinstance(msg, ChannelMessage)
    assert msg.channel == "twilio_voice"
    assert msg.channel_user_id == OWNER_ID
    assert msg.user_handle == "owner"  # from CallerName, not the phone number
    assert msg.trust_level == "owner_paired"
    assert msg.text is None  # a call webhook carries no speech
    assert msg.metadata["call_stage"] == "ringing"
    assert isinstance(msg.arrived_at, datetime)


async def test_inbound_uses_callername_then_falls_back_to_number(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})

    named = await adapter.on_message(_call_event(caller_name="Ada"))
    assert named.user_handle == "Ada"

    anon = await adapter.on_message(_call_event(caller_name=None))
    assert anon.user_handle == OWNER_ID  # no display name -> phone number


async def test_inbound_missing_caller_id_collapses_to_untrusted(mock):
    adapter = Adapter(config={"mock": mock})
    # A malformed webhook with no `From` must not raise.
    msg = await adapter.on_message(_call_event(from_phone=None))
    assert msg.channel_user_id == ""
    assert msg.trust_level == "untrusted"


async def test_inbound_terminal_status_is_flagged_lifecycle(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(_call_event(status="completed"))
    assert msg.metadata["call_status"] == "completed"
    assert msg.metadata["lifecycle"] is True
    assert msg.text is None


# --------------------------------------------------------------------------
# Trust-level assignment
# --------------------------------------------------------------------------


async def test_trust_stranger_is_untrusted(mock):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(mock.queue_stranger_message("ringing"))
    assert msg.channel_user_id == STRANGER_ID
    assert msg.trust_level == "untrusted"


async def test_trust_paired_user_is_user_paired(mock):
    # Pair the stranger's number at user_paired (not owner) via the code flow.
    store = get_pairing_store()
    code, _exp = store.issue_code("twilio_voice", STRANGER_ID, "guest", requested_trust_level="user_paired")
    store.confirm_code(code)

    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(mock.queue_stranger_message("ringing"))
    assert msg.trust_level == "user_paired"


# --------------------------------------------------------------------------
# Inbound voice (media frame)
# --------------------------------------------------------------------------


async def test_media_frame_transcribes_and_persists(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    # The stream's `start` frame registers the caller; the mock's media frames
    # use STREAM_SID, so the start frame must use it too.
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))

    msg = await adapter.on_message(mock.queue_media_frame(audio_bytes=b"\xff\x7f" * 100))
    assert msg.channel_user_id == OWNER_ID  # resolved from the per-stream registry
    assert msg.trust_level == "owner_paired"
    assert msg.text == mock.transcription_text
    assert msg.voice_audio_ref is not None
    assert msg.voice_audio_ref.startswith("art:")
    assert msg.metadata["call_stage"] == "answered"
    assert mock.artifact_store, "decoded audio should be persisted to the artifact store"


async def test_media_frame_empty_transcript_is_flagged(mock, owner_paired):
    mock.transcription_text = ""  # STT heard only silence/noise
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))

    msg = await adapter.on_message(mock.queue_media_frame())
    assert msg.text == ""
    assert msg.metadata["empty_transcript"] is True
    assert msg.voice_audio_ref.startswith("art:")  # audio still kept


async def test_media_frame_transcription_failure_keeps_audio(mock, owner_paired, monkeypatch):
    def boom(_audio: bytes) -> str:
        raise RuntimeError("stt provider down")

    monkeypatch.setattr(mock, "transcribe", boom)
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))

    msg = await adapter.on_message(mock.queue_media_frame())
    assert msg.text is None
    assert "stt provider down" in msg.metadata["transcription_error"]
    assert msg.voice_audio_ref.startswith("art:")  # recording survives the failure


async def test_media_unknown_stream_falls_back_to_untrusted(mock, owner_paired):
    # A media frame for a stream we never saw a `start` for must not borrow
    # another call's caller — it stays unattributed and untrusted.
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(_media_event("never-started"))
    assert msg.channel_user_id == ""
    assert msg.trust_level == "untrusted"
    assert msg.voice_audio_ref.startswith("art:")  # audio still captured


# --------------------------------------------------------------------------
# Per-stream isolation (concurrency safety)
# --------------------------------------------------------------------------


async def test_stream_start_registers_caller(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    assert msg.channel_user_id == OWNER_ID
    assert msg.trust_level == "owner_paired"
    assert msg.metadata["call_stage"] == "answered"


async def test_concurrent_streams_do_not_clobber(mock, owner_paired):
    # Two calls in flight on one adapter instance: owner on stream A, stranger
    # on stream B. Interleaved media must resolve to the right caller each time.
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event("streamA", OWNER_ID, "owner"))
    await adapter.on_message(_start_event("streamB", STRANGER_ID, "stranger"))

    msg_b = await adapter.on_message(_media_event("streamB"))
    msg_a = await adapter.on_message(_media_event("streamA"))

    assert msg_a.channel_user_id == OWNER_ID
    assert msg_a.trust_level == "owner_paired"
    assert msg_b.channel_user_id == STRANGER_ID
    assert msg_b.trust_level == "untrusted"


async def test_stream_stop_evicts_caller(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event("streamX", OWNER_ID, "owner"))
    await adapter.on_message(_stop_event("streamX"))

    # After stop, the stream is forgotten — a stray frame is unattributed.
    msg = await adapter.on_message(_media_event("streamX"))
    assert msg.channel_user_id == ""
    assert msg.trust_level == "untrusted"


# --------------------------------------------------------------------------
# Disconnect handling
# --------------------------------------------------------------------------


async def test_disconnect_is_handled_cleanly(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    mock.force_disconnect()
    msg = await adapter.on_message(mock.queue_owner_message("ringing"))
    assert isinstance(msg, ChannelMessage)
    assert msg.metadata.get("reconnect") is True


# --------------------------------------------------------------------------
# Outbound translation
# --------------------------------------------------------------------------


async def test_outbound_twiml_is_wellformed(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    await adapter.send(ChannelReply(channel="twilio_voice", channel_user_id=OWNER_ID, text="hello there"))

    assert len(mock.send_log) == 1
    body = mock.send_log[0]
    twiml = body["twiml"]
    assert body["to"] == OWNER_ID
    assert "<Response>" in twiml
    assert "<Say>hello there</Say>" in twiml
    assert "<Connect><Stream" in twiml


async def test_outbound_escapes_xml_injection(mock, owner_paired):
    adapter = Adapter(config={"mock": mock})
    await adapter.send(ChannelReply(channel="twilio_voice", channel_user_id=OWNER_ID, text="tom & <jerry>"))
    twiml = mock.send_log[0]["twiml"]
    assert "&amp;" in twiml and "&lt;jerry&gt;" in twiml
    assert "<jerry>" not in twiml  # raw markup must not reach the wire


async def test_outbound_rate_limit_propagates_429(mock, owner_paired):
    mock.rate_limited = True
    adapter = Adapter(config={"mock": mock})
    result = await adapter.send(ChannelReply(channel="twilio_voice", channel_user_id=OWNER_ID, text="x"))
    assert isinstance(result, dict)
    assert result.get("status") == 429 or result.get("code") == 20429


async def test_outbound_soft_note_guard_logs_but_does_not_block(mock, caplog):
    # STRANGER_ID is not paired -> the guard should warn but still send.
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(channel="twilio_voice", channel_user_id=STRANGER_ID, text="hi")

    with caplog.at_level(logging.WARNING, logger=ADAPTER_LOGGER):
        result = await adapter.send(reply)

    rendered = " ".join(r.getMessage() for r in caplog.records)
    assert "non-paired recipient" in rendered
    assert STRANGER_ID not in rendered, "full phone number must never be logged (PII)"
    assert "***" in rendered  # redacted form
    assert len(mock.send_log) == 1  # not blocked
    assert result.get("status") == 200


# --------------------------------------------------------------------------
# Audio conversion (mu-law -> WAV) — audio.py
# --------------------------------------------------------------------------


def _wav_params(data: bytes) -> wave._wave_params:  # type: ignore[name-defined]
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getparams()


def test_mulaw_to_wav_is_valid_16k_mono_pcm():
    # 200 bytes of mu-law = 25 ms @ 8 kHz; upsampled to 16 kHz it doubles.
    wav = tv_audio.mulaw_to_wav(b"\x00\x7f\xff\x80" * 50)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    p = _wav_params(wav)
    assert p.nchannels == 1
    assert p.sampwidth == 2  # 16-bit PCM
    assert p.framerate == tv_audio.TARGET_SAMPLE_RATE == 16000
    assert p.nframes == 200 * 2  # 8 kHz -> 16 kHz doubles the sample count


def test_mulaw_silence_decodes_to_near_zero():
    # 0xFF and 0x7F are the mu-law zero codes; both must decode to ~0 PCM.
    samples = tv_audio.decode_mulaw(b"\xff\x7f")
    assert list(samples) == [0, 0]


def test_mulaw_to_wav_empty_payload_is_valid_zero_frame_wav():
    wav = tv_audio.mulaw_to_wav(b"")
    assert wav[:4] == b"RIFF"
    assert _wav_params(wav).nframes == 0


async def test_media_frame_sends_wav_not_mulaw_to_real_stt(owner_paired, monkeypatch):
    # With no mock, the adapter hits the real STT facade. Capture what it sends
    # and assert it is a WAV container, not the raw mu-law payload.
    captured: dict[str, Any] = {}

    async def fake_transcribe(audio: bytes, mime: str, prefer: str = "default") -> TranscribeResult:
        captured["audio"] = audio
        captured["mime"] = mime
        return TranscribeResult(text="ok", language="en", duration_ms=10, provider="fake")

    monkeypatch.setattr("glc.channels.catalogue.twilio_voice.adapter.stt_transcribe", fake_transcribe)

    adapter = Adapter(config={})  # no mock -> production STT path
    adapter._stream_callers[STREAM_SID] = {"id": OWNER_ID, "handle": "owner"}

    msg = await adapter.on_message(_media_event(STREAM_SID, audio=b"\x00\x7f\xff\x80" * 40))
    assert captured["mime"] == "audio/wav"
    assert captured["audio"][:4] == b"RIFF", "STT must receive a WAV container, not raw mu-law"
    assert msg.text == "ok"
    assert msg.voice_audio_ref.startswith("art:")


# --------------------------------------------------------------------------
# Webhook signature verification — signature.py
# --------------------------------------------------------------------------

# Twilio's published worked example (https://www.twilio.com/docs/usage/security).
# This is the gold-standard vector: matching it proves our HMAC matches Twilio's.
_TW_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
_TW_PARAMS = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675309",
    "Digits": "1234",
    "From": "+14158675309",
    "To": "+18005551212",
}
_TW_TOKEN = "12345"
_TW_SIGNATURE = "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_signature_matches_twilio_published_vector():
    assert tv_sig.expected_signature(_TW_TOKEN, _TW_URL, _TW_PARAMS) == _TW_SIGNATURE
    assert tv_sig.verify_signature(_TW_TOKEN, _TW_URL, _TW_PARAMS, _TW_SIGNATURE) is True


def test_signature_rejects_tampered_params():
    tampered = {**_TW_PARAMS, "From": "+19998887777"}  # attacker swaps the caller
    assert tv_sig.verify_signature(_TW_TOKEN, _TW_URL, tampered, _TW_SIGNATURE) is False


def test_signature_rejects_wrong_token():
    assert tv_sig.verify_signature("not-the-token", _TW_URL, _TW_PARAMS, _TW_SIGNATURE) is False


def test_signature_fails_closed_on_missing_inputs():
    # No signature, or no token -> not authentic. We never default to "trust".
    assert tv_sig.verify_signature(_TW_TOKEN, _TW_URL, _TW_PARAMS, None) is False
    assert tv_sig.verify_signature("", _TW_URL, _TW_PARAMS, _TW_SIGNATURE) is False


def test_authenticate_webhook_accepts_valid_signature():
    adapter = Adapter(config={"auth_token": _TW_TOKEN})
    ok = adapter.authenticate_webhook(dict(_TW_PARAMS), url=_TW_URL, signature=_TW_SIGNATURE)
    assert ok is True


def test_authenticate_webhook_ignores_synthetic_underscore_keys():
    # The mock tags events with `_synthetic_call_label`; such keys must not
    # enter the signature base string or every real webhook would fail.
    raw = {**_TW_PARAMS, "_synthetic_call_label": "ringing"}
    adapter = Adapter(config={"auth_token": _TW_TOKEN})
    assert adapter.authenticate_webhook(raw, url=_TW_URL, signature=_TW_SIGNATURE) is True


def test_authenticate_webhook_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    adapter = Adapter(config={})  # no token configured anywhere
    assert adapter.authenticate_webhook(dict(_TW_PARAMS), url=_TW_URL, signature=_TW_SIGNATURE) is False


def test_authenticate_webhook_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", _TW_TOKEN)
    adapter = Adapter(config={})  # token comes from the environment
    assert adapter.authenticate_webhook(dict(_TW_PARAMS), url=_TW_URL, signature=_TW_SIGNATURE) is True


# --------------------------------------------------------------------------
# Malformed frame handling — frames are untrusted input; never raise
# --------------------------------------------------------------------------


async def test_malformed_media_frame_does_not_raise(mock):
    # A frame claiming event=media but missing the `media` body must not raise;
    # it collapses to an untrusted, caller-less envelope flagged for audit.
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message({"event": "media", "streamSid": "sX"})
    assert isinstance(msg, ChannelMessage)
    assert msg.trust_level == "untrusted"
    assert msg.channel_user_id == ""
    assert msg.metadata["malformed_frame"] is True
    assert msg.metadata["frame_event"] == "media"


async def test_malformed_base64_payload_becomes_empty_audio(mock, owner_paired):
    # A valid frame shape but a corrupt base64 payload must not crash the call.
    # We still emit an envelope (audio empty, flagged) so one bad packet can't
    # tear down a live stream.
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))

    bad = {"event": "media", "streamSid": STREAM_SID, "media": {"payload": "not_valid_base64!!!"}}
    msg = await adapter.on_message(bad)
    assert isinstance(msg, ChannelMessage)
    assert msg.metadata["malformed_audio"] is True
    assert msg.voice_audio_ref.startswith("art:")  # still persisted (empty WAV)
    assert msg.channel_user_id == OWNER_ID  # frame itself was well-formed


async def test_malformed_start_frame_does_not_raise(mock):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message({"event": "start"})  # missing `start` body
    assert msg.trust_level == "untrusted"
    assert msg.metadata["malformed_frame"] is True
    assert msg.metadata["frame_event"] == "start"


async def test_malformed_stop_frame_does_not_raise(mock):
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message({"event": "stop"})  # missing `streamSid`
    assert msg.trust_level == "untrusted"
    assert msg.metadata["malformed_frame"] is True
    assert msg.metadata["frame_event"] == "stop"


# --------------------------------------------------------------------------
# Buffered transcription (opt-in via config["buffer_audio"]=True)
#
# Default is False, so everything above (and the official suite) keeps the
# per-frame behaviour. These tests validate the buffering logic against the
# contract mock — no real STT — so they stay deterministic and offline.
# --------------------------------------------------------------------------


def _count_transcribe(mock, monkeypatch) -> dict[str, int]:
    """Wrap mock.transcribe to count how many times it's actually called."""
    calls = {"n": 0}
    real = mock.transcribe

    def counting(audio: bytes) -> str:
        calls["n"] += 1
        return real(audio)

    monkeypatch.setattr(mock, "transcribe", counting)
    return calls


async def test_default_mode_is_still_per_frame(mock, owner_paired):
    # Sanity: without the flag, one media frame transcribes immediately.
    adapter = Adapter(config={"mock": mock})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    msg = await adapter.on_message(_media_event(STREAM_SID))
    assert msg.text == mock.transcription_text
    assert "buffering" not in msg.metadata


async def test_buffered_frames_defer_transcription(mock, owner_paired, monkeypatch):
    calls = _count_transcribe(mock, monkeypatch)
    adapter = Adapter(config={"mock": mock, "buffer_audio": True})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))

    m1 = await adapter.on_message(_media_event(STREAM_SID))
    m2 = await adapter.on_message(_media_event(STREAM_SID))

    # Frames are buffered, not transcribed: no text yet, nothing persisted yet.
    assert m1.text is None and m2.text is None
    assert m1.metadata.get("buffering") is True
    assert m1.channel_user_id == OWNER_ID  # caller still resolved
    assert calls["n"] == 0
    assert mock.artifact_store == {}


async def test_buffered_flush_on_stop_transcribes_once(mock, owner_paired, monkeypatch):
    calls = _count_transcribe(mock, monkeypatch)
    adapter = Adapter(config={"mock": mock, "buffer_audio": True})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    await adapter.on_message(_media_event(STREAM_SID))
    await adapter.on_message(_media_event(STREAM_SID))

    msg = await adapter.on_message(_stop_event(STREAM_SID))

    # The whole utterance is transcribed exactly once on stop.
    assert calls["n"] == 1
    assert msg.text == mock.transcription_text
    assert msg.voice_audio_ref.startswith("art:")
    assert msg.metadata.get("buffered") is True
    assert len(mock.artifact_store) == 1  # one combined WAV persisted


async def test_buffered_max_bytes_forces_early_flush(mock, owner_paired):
    # A tiny cap makes the first frame trip the runaway-stream safety flush.
    adapter = Adapter(config={"mock": mock, "buffer_audio": True, "max_buffer_bytes": 1})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    msg = await adapter.on_message(_media_event(STREAM_SID))
    assert msg.text == mock.transcription_text  # flushed immediately
    assert msg.voice_audio_ref.startswith("art:")
    assert msg.metadata.get("buffered") is True


# --------------------------------------------------------------------------
# Observability hook (config["event_hook"]) — for monitoring + test assertions
# --------------------------------------------------------------------------


async def test_event_hook_observes_inbound_and_outbound(mock, owner_paired):
    events: list[dict] = []
    adapter = Adapter(config={"mock": mock, "event_hook": events.append})

    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    await adapter.on_message(_media_event(STREAM_SID))
    await adapter.send(ChannelReply(channel="twilio_voice", channel_user_id=OWNER_ID, text="hi"))

    kinds = [e["event"] for e in events]
    assert kinds.count("inbound") == 2  # start + media
    assert "outbound" in kinds
    # the inbound events carry the real envelope the adapter produced
    inbound = [e for e in events if e["event"] == "inbound"]
    assert all(e["envelope"]["channel"] == "twilio_voice" for e in inbound)
    assert any(e["envelope"]["channel_user_id"] == OWNER_ID for e in inbound)


async def test_event_hook_supports_async_callables(mock, owner_paired):
    events: list[dict] = []

    async def ahook(e: dict) -> None:
        events.append(e)

    adapter = Adapter(config={"mock": mock, "event_hook": ahook})
    await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    assert events and events[0]["event"] == "inbound"


async def test_event_hook_failure_never_breaks_the_call(mock, owner_paired):
    def boom(_e: dict) -> None:
        raise RuntimeError("monitoring backend down")

    adapter = Adapter(config={"mock": mock, "event_hook": boom})
    # A raising hook must be swallowed — the call still produces an envelope.
    msg = await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    assert isinstance(msg, ChannelMessage)
    assert msg.channel_user_id == OWNER_ID


async def test_no_event_hook_is_a_noop(mock, owner_paired):
    # Default: no hook configured -> behaves exactly as before, no error.
    adapter = Adapter(config={"mock": mock})
    msg = await adapter.on_message(_start_event(STREAM_SID, OWNER_ID, "owner"))
    assert isinstance(msg, ChannelMessage)
