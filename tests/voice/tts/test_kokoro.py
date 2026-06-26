"""Kokoro-82M TTS provider tests.

Six structural tests + one behavioural test (pipeline_reuse).
Wire-format source: https://github.com/hexgrad/kokoro.
"""

from __future__ import annotations

import pytest

from glc.voice.tts.base import SynthesizeResult, TTSError
from glc.voice.tts.providers.kokoro.adapter import Provider
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
