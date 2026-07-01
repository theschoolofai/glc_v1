"""Tests for the live (non-mock) adapter paths.

These exercise the code that runs in production when there is no `mock`
in config: real media persistence and real HTTP send with graceful 429
handling. HTTP is stubbed by monkeypatching httpx.AsyncClient.post.
"""

from __future__ import annotations

import httpx
import pytest

from glc.channels.catalogue.twilio_sms import artifacts
from glc.channels.catalogue.twilio_sms.adapter import Adapter
from glc.channels.envelope import ChannelReply
from tests.channels.mocks.twilio_sms_mock import BOT_PHONE, OWNER_ID


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("GLC_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


async def test_inbound_mms_persists_bytes_live(monkeypatch):
    """No mock in config -> bytes are downloaded and actually persisted,
    and the emitted attachment ref resolves back to those exact bytes."""
    payload = b"\xff\xd8\xff real jpeg bytes"

    async def fake_download(self, url):
        return payload

    monkeypatch.setattr(Adapter, "_download_media", fake_download)

    adapter = Adapter(config={"phone_number": BOT_PHONE})
    raw = {
        "From": OWNER_ID,
        "To": BOT_PHONE,
        "Body": "photo",
        "MessageSid": "MM1",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/Media/real.jpg",
        "MediaContentType0": "image/jpeg",
    }
    msg = await adapter.on_message(raw)

    assert len(msg.attachments) == 1
    ref = msg.attachments[0].ref
    assert ref.startswith("art:")
    assert artifacts.get_bytes(ref) == payload  # persisted, not discarded


class _FakeClient:
    """Stand-in for httpx.AsyncClient that never opens a real connection
    (constructing a real client fails under the test sandbox's SSL setup)."""

    captured: dict = {}

    def __init__(self, response):
        self._response = response

    def __call__(self, *args, **kwargs):  # httpx.AsyncClient() -> instance
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeClient.captured = {"url": url, **kwargs}
        return self._response


def _patch_client(monkeypatch, status_code, json_body):
    resp = httpx.Response(status_code=status_code, json=json_body)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient(resp))


async def test_send_429_returns_dict_not_raise(monkeypatch):
    body = {"code": 20429, "message": "Too Many Requests", "status": 429}
    _patch_client(monkeypatch, 429, body)

    adapter = Adapter(config={"phone_number": BOT_PHONE})
    reply = ChannelReply(channel="twilio_sms", channel_user_id=OWNER_ID, text="x")
    result = await adapter.send(reply)  # must not raise

    assert isinstance(result, dict)
    assert result.get("status") == 429 or result.get("code") == 20429


async def test_send_success_uses_capitalised_fields(monkeypatch):
    _patch_client(monkeypatch, 201, {"sid": "SM1", "status": "queued"})

    adapter = Adapter(config={"phone_number": BOT_PHONE})
    reply = ChannelReply(channel="twilio_sms", channel_user_id=OWNER_ID, text="hi")
    result = await adapter.send(reply)

    assert result.get("sid") == "SM1"
    sent = _FakeClient.captured["data"]
    assert sent["From"] == BOT_PHONE
    assert sent["To"] == OWNER_ID
    assert sent["Body"] == "hi"
    # Lowercase Twilio keys must never appear.
    assert "from" not in sent and "to" not in sent and "body" not in sent


async def test_send_no_from_raises_in_live_mode():
    adapter = Adapter(config={})  # no phone, no mock
    reply = ChannelReply(channel="twilio_sms", channel_user_id=OWNER_ID, text="x")
    with pytest.raises(RuntimeError):
        await adapter.send(reply)
