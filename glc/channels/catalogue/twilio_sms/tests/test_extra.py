from __future__ import annotations

import pytest

from glc.channels.catalogue.twilio_sms.adapter import Adapter
from glc.channels.envelope import Attachment, ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.twilio_sms_mock import OWNER_ID, TwilioSmsMock


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
async def test_send_multi_mms_emits_multiple_media_urls(mock, pair_owner):
    adapter = Adapter(config={"mock": mock})
    reply = ChannelReply(
        channel="twilio_sms",
        channel_user_id=OWNER_ID,
        text="reply with multiple images",
        attachments=[
            Attachment(
                kind="image",
                ref="art:img1",
                metadata={"public_url": "https://glc.example/artifacts/img1"},
            ),
            Attachment(
                kind="image",
                ref="art:img2",
                metadata={"public_url": "https://glc.example/artifacts/img2"},
            ),
        ],
    )
    await adapter.send(reply)
    out = mock.send_log[-1]
    assert out.get("MediaUrl") == [
        "https://glc.example/artifacts/img1",
        "https://glc.example/artifacts/img2",
    ]
