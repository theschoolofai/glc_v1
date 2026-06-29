"""Internal regression tests for the kokoro adapter's real-path branches.

These tests live inside the owned path so they don't touch
`tests/voice/tts/test_kokoro.py` (which is the maintainer-seeded contract
checked by `scripts/check_pr_boundaries.py`).

They are not auto-discovered by the project's default pytest invocation
(`pyproject.toml` pins `testpaths = ["tests"]`). Run them explicitly:

    uv run pytest glc/voice/tts/providers/kokoro/tests_internal/ -v

They cover the three branches in `adapter.synthesize`'s real path that
aren't exercised by the seeded mock-delegate tests:

- `voice_id=None` resolves to `DEFAULT_VOICE_ID` before delegation.
- A non-`TTSError` raised by `runner.synthesize` is wrapped as
  `TTSError(status=502)`.
- Empty audio bytes from `runner.synthesize` become `TTSError(status=502)`.
- A `TTSError` raised by `runner.synthesize` passes through unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from glc.voice.tts.base import TTSError
from glc.voice.tts.providers.kokoro.adapter import DEFAULT_VOICE_ID, Provider
from tests.voice.tts.mocks.kokoro_mock import KokoroMock


@pytest.mark.asyncio
async def test_none_voice_id_resolved_to_default_before_mock() -> None:
    """voice_id=None must reach the mock as DEFAULT_VOICE_ID, not None.

    The adapter resolves the voice before delegating so both the mock
    and the real runner always receive an explicit voice string.
    """
    mock = KokoroMock()
    adapter = Provider(config={"mock": mock})
    await adapter.synthesize("hi", voice_id=None)
    assert mock.received_calls[-1]["voice_id"] == DEFAULT_VOICE_ID


@pytest.mark.asyncio
async def test_runner_generic_exception_wrapped_as_tts_error() -> None:
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
async def test_runner_empty_audio_raises_tts_error() -> None:
    """Empty bytes from runner must raise TTSError(status=502).

    `runner.synthesize` returns `b""` when the KPipeline generator yields
    nothing. Emitting a `SynthesizeResult` with 0 bytes would claim a
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
async def test_runner_tts_error_passes_through_unchanged() -> None:
    """TTSError raised by runner must not be re-wrapped.

    Covers the `except TTSError: raise` branch — a structured error from
    the runner (e.g. model-load failure reported as 503) must arrive at
    the caller with its original status intact.
    """
    adapter = Provider(config={})
    with patch(
        "glc.voice.tts.providers.kokoro.runner.synthesize",
        side_effect=TTSError("model load failed", status=503),
    ):
        with pytest.raises(TTSError) as ei:
            await adapter.synthesize("hi")
    assert ei.value.status == 503
