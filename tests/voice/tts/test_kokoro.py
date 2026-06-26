"""Kokoro-82M TTS provider tests.

Six structural tests + one behavioural test (pipeline_reuse) + four
real-path tests covering the updated adapter's error-handling branches.
Wire-format source: https://github.com/hexgrad/kokoro.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from glc.voice.tts.base import SynthesizeResult, TTSError
from glc.voice.tts.providers.kokoro.adapter import DEFAULT_VOICE_ID, Provider
from tests.voice.tts.mocks.kokoro_mock import KokoroMock


@pytest.fixture
def mock():
    return KokoroMock()


@pytest.mark.asyncio
async def test_provider_name_matches(mock):
    adapter = Provider(config={"mock": mock})
    assert adapter.name == "kokoro"


@pytest.mark.asyncio
async def test_synthesize_returns_synthesize_result(mock):
    adapter = Provider(config={"mock": mock})
    r = await adapter.synthesize("hello", voice_id="default")
    assert isinstance(r, SynthesizeResult)
    assert r.provider == "kokoro"
    assert r.audio_b64
    assert r.sample_rate > 0


@pytest.mark.asyncio
async def test_synthesize_passes_text_to_upstream(mock):
    adapter = Provider(config={"mock": mock})
    await adapter.synthesize("hello world", voice_id="x")
    assert mock.received_calls
    assert mock.received_calls[-1]["text_len"] == len("hello world")


@pytest.mark.asyncio
async def test_synthesize_records_sample_rate(mock):
    mock.canned_sample_rate = 22050
    adapter = Provider(config={"mock": mock})
    r = await adapter.synthesize("hi")
    assert r.sample_rate == 22050


@pytest.mark.asyncio
async def test_synthesize_propagates_upstream_error(mock):
    mock.upstream_failure = (502, "upstream broken")
    adapter = Provider(config={"mock": mock})
    with pytest.raises(TTSError) as ei:
        await adapter.synthesize("hi")
    assert ei.value.status == 502


@pytest.mark.asyncio
async def test_synthesize_handles_empty_text(mock):
    adapter = Provider(config={"mock": mock})
    r = await adapter.synthesize("", voice_id=None)
    assert isinstance(r, SynthesizeResult)


@pytest.mark.asyncio
async def test_channel_specific_behaviour_pipeline_reuse(mock):
    """Loading the Kokoro pipeline downloads ~300 MB of weights into
    RAM. Adapters that load on every call burn that cost per
    synthesis. The pipeline must be lazy-loaded once and reused."""
    adapter = Provider(config={"mock": mock})
    await adapter.synthesize("first call", voice_id="af_bella")
    await adapter.synthesize("second call", voice_id="af_bella")
    await adapter.synthesize("third call", voice_id="af_bella")
    assert mock.pipeline_load_count == 1, (
        f"pipeline must load exactly once; loaded {mock.pipeline_load_count}x"
    )


# ---------------------------------------------------------------------------
# Real-path branch tests (adapter.py lines 48, 70-84)
# These patch runner.synthesize so no model download is needed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_voice_id_resolved_to_default_before_mock(mock):
    """voice_id=None must reach the mock as DEFAULT_VOICE_ID, not None.

    The adapter resolves the voice before delegating so both the mock
    and the real runner always receive an explicit voice string.
    """
    adapter = Provider(config={"mock": mock})
    await adapter.synthesize("hi", voice_id=None)
    assert mock.received_calls[-1]["voice_id"] == DEFAULT_VOICE_ID


@pytest.mark.asyncio
async def test_runner_generic_exception_wrapped_as_tts_error():
    """Non-TTSError from runner must surface as TTSError(status=502).

    Covers the `except Exception as e` branch added to keep the gateway's
    error contract consistent regardless of which exception the kokoro
    package or numpy raises internally.
    """
    adapter = Provider(config={})
    with patch(
        "glc.voice.tts.providers.kokoro.runner.synthesize",
        side_effect=RuntimeError("gpu oom"),
    ):
        with pytest.raises(TTSError) as ei:
            await adapter.synthesize("hi")
    assert ei.value.status == 502


@pytest.mark.asyncio
async def test_runner_empty_audio_raises_tts_error():
    """Empty bytes from runner must raise TTSError(status=502).

    runner.synthesize returns b'' when the KPipeline generator yields
    nothing. Emitting a SynthesizeResult with 0 bytes would claim a
    valid WAV envelope for empty audio; the adapter must refuse that.
    """
    adapter = Provider(config={})
    with patch(
        "glc.voice.tts.providers.kokoro.runner.synthesize",
        return_value=(b"", 24000),
    ):
        with pytest.raises(TTSError) as ei:
            await adapter.synthesize("hi")
    assert ei.value.status == 502


@pytest.mark.asyncio
async def test_runner_tts_error_passes_through_unchanged():
    """TTSError raised by runner must not be re-wrapped.

    Covers the `except TTSError: raise` branch — a structured error
    from the runner (e.g. model load failure reported as 503) must
    arrive at the caller with its original status intact.
    """
    adapter = Provider(config={})
    with patch(
        "glc.voice.tts.providers.kokoro.runner.synthesize",
        side_effect=TTSError("model load failed", status=503),
    ):
        with pytest.raises(TTSError) as ei:
            await adapter.synthesize("hi")
    assert ei.value.status == 503
