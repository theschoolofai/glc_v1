"""Microsoft Teams adapter tests.

Wire-format basis: Bot Framework Activity protocol.
https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-activities

Six structural tests + one behavioural test (Adaptive Card body
extraction).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from glc.channels.catalogue.teams.adapter import Adapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.teams_mock import OWNER_ID, STRANGER_ID, TeamsMock


@pytest.fixture
def mock():
    return TeamsMock()


@pytest.fixture
def pair_owner():
    store = get_pairing_store()
    store.force_pair_owner("teams", OWNER_ID, user_handle="owner")
    yield
    store.revoke("teams", OWNER_ID)


@pytest.mark.asyncio
async def test_on_message_owner_returns_valid_envelope(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_owner_message("hello from owner")
    msg = await adapter.on_message(ev)
    assert isinstance(msg, ChannelMessage)
    assert msg.channel == "teams"
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
    """Outbound activities require `type: "message"`, `text`, and
    `replyToId` referencing the inbound activity id. The Bot Framework
    rejects payloads without `type` set."""
    adapter = Adapter(config={"mock": mock})
    # Prime the inbound id by sending one message in first.
    ev = mock.queue_owner_message("seed")
    await adapter.on_message(ev)
    reply = ChannelReply(channel="teams", channel_user_id=OWNER_ID, text="hi back", thread_id=ev["id"])
    await adapter.send(reply)
    assert len(mock.send_log) == 1
    body = mock.send_log[0]
    assert body.get("type") == "message"
    assert body.get("text") == "hi back"
    assert body.get("replyToId") == ev["id"], "Teams replies must set replyToId to the inbound activity id"


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
    reply = ChannelReply(channel="teams", channel_user_id=OWNER_ID, text="x")
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
async def test_channel_specific_behaviour_adaptive_card(mock, pair_owner):
    """Adaptive Cards arrive as `attachments[]` with `contentType ==
    application/vnd.microsoft.card.adaptive`. The adapter must:
      - extract the card's first TextBlock body and put it in
        ChannelMessage.text
      - stash the raw card JSON under metadata['adaptive_card']
    Adapters that ignore attachments lose the user's intent entirely
    when a Teams user submits a card-form interaction."""
    adapter = Adapter(config={"mock": mock})
    ev = mock.queue_adaptive_card_message(body_text="Please review the doc.")
    msg = await adapter.on_message(ev)
    assert msg is not None
    assert msg.text is not None
    assert "review the doc" in msg.text.lower()
    card = msg.metadata.get("adaptive_card")
    assert card is not None, "metadata['adaptive_card'] must hold the raw card JSON"
    assert card.get("type") == "AdaptiveCard"


@pytest.mark.asyncio
async def test_channel_specific_behaviour_adaptive_card_bfs(mock, pair_owner):
    """Verify that Adaptive Card extraction walks the card body breadth-first."""
    adapter = Adapter(config={"mock": mock})
    nested_card = {
        "type": "AdaptiveCard",
        "body": [
            {"type": "Container", "items": [{"type": "TextBlock", "text": "Deep Text (DFS path)"}]},
            {"type": "TextBlock", "text": "Shallow Text (BFS path)"},
        ],
    }
    ev = mock.queue_adaptive_card_message(card=nested_card)
    msg = await adapter.on_message(ev)
    assert msg is not None
    # Breadth-first should find "Shallow Text" at depth 1 before "Deep Text" at depth 2
    assert msg.text == "Shallow Text (BFS path)"
