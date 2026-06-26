"""WhatsApp adapter tests.

Wire-format basis: Meta Cloud API webhook + Graph send endpoint.
https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages

Six structural tests + one behavioural test (X-Hub-Signature-256
verification). The signature test is the load-bearing one for this
channel: a missing or tampered signature means the adapter cannot
trust the payload, so the envelope must not be constructed at all.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from glc.channels.catalogue.whatsapp.adapter import Adapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.whatsapp_mock import (
    DEFAULT_APP_SECRET,
    OWNER_ID,
    STRANGER_ID,
    WhatsappMock,
)


@pytest.fixture
def mock():
    return WhatsappMock()


@pytest.fixture
def pair_owner():
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")
    yield
    store.revoke("whatsapp", OWNER_ID)


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", DEFAULT_APP_SECRET)


@pytest.mark.asyncio
async def test_on_message_owner_returns_valid_envelope(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_owner_message("hello from owner")
    msg = await adapter.on_message(ev)
    assert isinstance(msg, ChannelMessage)
    assert msg.channel == "whatsapp"
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
    """Cloud API send body shape:
    `{"messaging_product":"whatsapp","to":"<E164>","type":"text",
      "text":{"body":"..."}}`. Adapters that flatten `text` to a top-level
    string fail this test."""
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="hi back")
    await adapter.send(reply)
    assert len(mock.send_log) == 1
    body = mock.send_log[0]
    assert body.get("messaging_product") == "whatsapp"
    assert body.get("to") == OWNER_ID
    assert body.get("type") == "text"
    assert body.get("text", {}).get("body") == "hi back"


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
    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="x")
    result = await adapter.send(reply)
    assert isinstance(result, dict)
    assert result.get("status") == 429 or (result.get("error", {}) or {}).get("code") == 80007


@pytest.mark.asyncio
async def test_allowlist_silently_drops_stranger_in_public(mock):
    adapter = Adapter(config={"mock": mock, "is_public_channel": True})
    ev = mock.queue_stranger_message("hi from public")
    msg = await adapter.on_message(ev)
    assert msg is None or msg.trust_level == "untrusted"


@pytest.mark.asyncio
async def test_channel_specific_behaviour_signature_verification(mock, pair_owner):
    """The X-Hub-Signature-256 header is HMAC-SHA256 over the raw body
    using the Meta app secret. The adapter must verify it before
    constructing an envelope. Three sub-cases:

      1. unsigned   → reject (None or raise), no envelope built
      2. tampered   → reject (None or raise), no envelope built
      3. valid      → accept, envelope built

    Adapters that skip the signature check accept tampered payloads
    from anyone who can reach the webhook URL — including attackers
    who scraped the URL from a server log."""
    adapter = Adapter(config={"mock": mock})

    # 1. Unsigned
    raw, headers = mock.queue_unsigned_webhook(text="unsigned probe")
    out = await adapter.on_message({"raw_body": raw, "headers": headers})
    assert out is None, "adapter must reject unsigned webhooks"

    # 2. Tampered
    raw, headers = mock.queue_tampered_webhook(text="tampered probe")
    out = await adapter.on_message({"raw_body": raw, "headers": headers})
    assert out is None, "adapter must reject tampered signatures"

    # 3. Valid
    raw, headers = mock.queue_signed_webhook(text="valid probe")
    out = await adapter.on_message({"raw_body": raw, "headers": headers})
    assert isinstance(out, ChannelMessage)
    assert out.text == "valid probe"
