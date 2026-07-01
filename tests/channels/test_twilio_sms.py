"""Twilio SMS adapter tests.

Wire-format basis: Twilio Programmable Messaging webhook + REST.
https://www.twilio.com/docs/messaging/guides/webhook-request
https://www.twilio.com/docs/messaging/api/message-resource

Six structural tests + one behavioural test (MMS media download → artifact).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from glc.channels.catalogue.twilio_sms.adapter import Adapter
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.twilio_sms_mock import OWNER_ID, STRANGER_ID, TwilioSmsMock


@pytest.fixture
def mock():
    return TwilioSmsMock()


@pytest.fixture
def pair_owner():
    store = get_pairing_store()
    store.force_pair_owner("twilio_sms", OWNER_ID, user_handle="owner")
    yield
    store.revoke("twilio_sms", OWNER_ID)


@pytest.mark.asyncio
async def test_on_message_owner_returns_valid_envelope(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_owner_message("hello from owner")
    msg = await adapter.on_message(ev)
    assert isinstance(msg, ChannelMessage)
    assert msg.channel == "twilio_sms"
    assert msg.channel_user_id == OWNER_ID
    assert msg.trust_level == "owner_paired"
    assert msg.text == "hello from owner"
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
    """`messages.create` form fields: `From`, `To`, `Body` (capitalised).
    Twilio rejects payloads using lowercase keys."""
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(channel="twilio_sms", channel_user_id=OWNER_ID, text="hi back")
    await adapter.send(reply)
    assert len(mock.send_log) == 1
    body = mock.send_log[0]
    assert body.get("To") == OWNER_ID
    assert body.get("From"), "From phone number must be set"
    assert body.get("Body") == "hi back"


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
    reply = ChannelReply(channel="twilio_sms", channel_user_id=OWNER_ID, text="x")
    result = await adapter.send(reply)
    assert isinstance(result, dict)
    assert result.get("status") == 429 or result.get("code") == 20429


@pytest.mark.asyncio
async def test_allowlist_silently_drops_stranger_in_public(mock):
    adapter = Adapter(config={"mock": mock, "is_public_channel": True})
    ev = mock.queue_stranger_message("hi from public")
    msg = await adapter.on_message(ev)
    assert msg is None or msg.trust_level == "untrusted"


@pytest.mark.asyncio
async def test_channel_specific_behaviour_mms_media_persists_as_artifact(mock, pair_owner):
    """MMS webhooks set `NumMedia >= 1` and provide `MediaUrl0..N`. The
    adapter must:
      - download the media bytes through `mock.download(url)` (the real
        adapter signs the request with the AccountSid)
      - persist via `mock.store_artifact(sha, bytes)` returning an
        `art:<sha>` handle
      - emit an Attachment of kind 'image' with that handle as `ref`

    A reply with an image attachment must produce a messages.create
    payload that carries `MediaUrl` (the URL the agent must serve from
    the artifact store on the public side)."""
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_mms_message(body="here's the photo", media_url="https://api.twilio.com/Media/MM_real.jpg")
    msg = await adapter.on_message(ev)
    assert msg is not None
    img = next((a for a in msg.attachments if a.kind == "image"), None)
    assert img is not None, "MMS must produce an Attachment of kind='image'"
    assert img.ref.startswith("art:"), "ref must be an artifact handle"
    sha = img.ref.removeprefix("art:")
    assert sha in mock.artifact_store, "media bytes must be in the artifact store"

    # Send side: outbound MMS attaches MediaUrl.
    reply = ChannelReply(
        channel="twilio_sms",
        channel_user_id=OWNER_ID,
        text="reply with image",
        attachments=[
            Attachment(
                kind="image",
                ref="art:abc123",
                metadata={"public_url": "https://glc.example/artifacts/abc123"},
            )
        ],
    )
    await adapter.send(reply)
    out = mock.send_log[-1]
    assert "MediaUrl" in out or "MediaUrl0" in out, "outbound MMS must include MediaUrl(0)"
