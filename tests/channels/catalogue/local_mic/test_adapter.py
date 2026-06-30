"""Local microphone adapter tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from glc.channels.catalogue.local_mic.adapter import Adapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from glc.voice.stt.base import STTProvider, TranscribeResult
from glc.voice.stt.router import register_test_provider as register_stt
from glc.voice.tts.base import SynthesizeResult, TTSProvider
from glc.voice.tts.router import register_test_provider as register_tts
from tests.channels.mocks.local_mic_mock import OWNER_ID, STRANGER_ID, LocalMicMock


def _fake_stt(transcribe_text: str = "hello"):
    class _F(STTProvider):
        name = "groq_whisper"

        async def transcribe(self, audio, mime):
            # Silent inputs (zero amplitude) return empty transcript
            if all(b == 0 for b in audio[:200]):
                return TranscribeResult(
                    text="", language="en", duration_ms=0, provider="groq_whisper", cost_usd=0.0
                )
            return TranscribeResult(
                text=transcribe_text, language="en", duration_ms=200, provider="groq_whisper", cost_usd=0.0
            )

    return _F()


def _fake_tts():
    class _F(TTSProvider):
        name = "kokoro"

        async def synthesize(self, text, voice_id=None):
            return SynthesizeResult(
                audio_b64="AAAA", mime="audio/wav", sample_rate=24000, provider="kokoro", cost_usd=0.0
            )

    return _F()


@pytest.fixture
def mock():
    return LocalMicMock()


@pytest.fixture(autouse=True)
def _voice_providers():
    # Register mock providers
    register_stt("groq_whisper", _fake_stt())
    register_tts("kokoro", _fake_tts())
    yield
    # Clean up
    register_stt("groq_whisper", None)
    register_tts("kokoro", None)


@pytest.fixture
def pair_owner():
    store = get_pairing_store()
    store.force_pair_owner("local_mic", OWNER_ID, user_handle="owner")
    yield
    store.revoke("local_mic", OWNER_ID)


@pytest.mark.asyncio
async def test_on_message_owner_returns_valid_envelope(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_owner_message("hello")
    msg = await adapter.on_message(ev)
    assert msg is not None
    assert msg.channel == "local_mic"
    assert msg.channel_user_id == OWNER_ID
    assert msg.trust_level == "owner_paired"
    assert isinstance(msg.arrived_at, datetime)


@pytest.mark.asyncio
async def test_on_message_stranger_is_untrusted(mock):
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_stranger_message("hi")
    msg = await adapter.on_message(ev)
    assert msg is not None
    assert msg.channel_user_id == STRANGER_ID
    assert msg.trust_level == "untrusted"


@pytest.mark.asyncio
async def test_send_emits_valid_wire_payload(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(channel="local_mic", channel_user_id=OWNER_ID, text="hi back")
    await adapter.send(reply)
    assert len(mock.play_log) >= 1, "Local-mic replies must route audio through play()"
    assert isinstance(mock.play_log[0], bytes)


@pytest.mark.asyncio
async def test_disconnect_is_handled(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    mock.force_disconnect()
    try:
        await adapter.on_message(mock.queue_owner_message("after disconnect"))
    except Exception as e:
        pytest.fail(f"adapter did not handle disconnect cleanly: {e!r}")


@pytest.mark.asyncio
async def test_rate_limit_propagates_429(mock, pair_owner):
    mock.rate_limited = True
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(channel="local_mic", channel_user_id=OWNER_ID, text="x")
    result = await adapter.send(reply)
    assert isinstance(result, dict)
    assert result.get("status") == 429


@pytest.mark.asyncio
async def test_allowlist_silently_drops_stranger_in_public(mock):
    adapter = Adapter(config={"mock": mock, "is_public_channel": True})
    ev = mock.queue_stranger_message("hi from public")
    msg = await adapter.on_message(ev)
    assert msg is None or msg.trust_level == "untrusted"


@pytest.mark.asyncio
async def test_channel_specific_behaviour_silence_vs_speech(mock, pair_owner):
    """Voice activity detection test."""
    adapter = Adapter(config={"mock": mock})

    # Silence -> no envelope.
    silent = mock.queue_silence()
    out_silent = await adapter.on_message(silent)
    assert out_silent is None, "silence must not produce an envelope"

    # Speech -> envelope with transcript + voice_audio_ref.
    hello = mock.queue_owner_message("hello")
    out_hello = await adapter.on_message(hello)
    assert out_hello is not None
    assert out_hello.text == "hello"
    assert out_hello.voice_audio_ref and out_hello.voice_audio_ref.startswith("art:")

    # Reply -> play() called with audio bytes.
    reply = ChannelReply(channel="local_mic", channel_user_id=OWNER_ID, text="hi back")
    await adapter.send(reply)
    assert len(mock.play_log) >= 1
