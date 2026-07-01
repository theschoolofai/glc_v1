"""Tests for wire/envelope refinements: media-kind mapping, STOP/HELP
keyword surfacing, outbound art: ref resolution, and schema coercion."""

from __future__ import annotations

import pytest

from glc.channels.catalogue.twilio_sms.adapter import Adapter, _media_kind
from glc.channels.catalogue.twilio_sms.schemas import TwilioInboundForm
from glc.channels.envelope import Attachment, ChannelReply
from tests.channels.mocks.twilio_sms_mock import BOT_PHONE, OWNER_ID, TwilioSmsMock


@pytest.fixture
def mock():
    return TwilioSmsMock()


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("image/jpeg", "image"),
        ("image/png", "image"),
        ("audio/amr", "audio"),
        ("audio/mpeg", "audio"),
        ("video/mp4", "video"),
        ("text/vcard", "file"),
        ("application/pdf", "file"),
    ],
)
def test_media_kind_mapping(content_type, expected):
    assert _media_kind(content_type) == expected


@pytest.mark.parametrize("body", ["STOP", "stop", "  Stop  ", "unsubscribe", "CANCEL"])
async def test_stop_keyword_surfaced(body):
    adapter = Adapter(config={})
    raw = {"From": OWNER_ID, "To": BOT_PHONE, "Body": body, "NumMedia": "0"}
    msg = await adapter.on_message(raw)
    assert msg.metadata.get("sms_keyword") == "STOP"


async def test_help_keyword_surfaced():
    adapter = Adapter(config={})
    raw = {"From": OWNER_ID, "To": BOT_PHONE, "Body": "help", "NumMedia": "0"}
    msg = await adapter.on_message(raw)
    assert msg.metadata.get("sms_keyword") == "HELP"


async def test_normal_message_has_no_keyword():
    adapter = Adapter(config={})
    raw = {"From": OWNER_ID, "To": BOT_PHONE, "Body": "stop by later", "NumMedia": "0"}
    msg = await adapter.on_message(raw)
    assert "sms_keyword" not in msg.metadata


async def test_outbound_art_ref_resolves_via_public_base(mock):
    adapter = Adapter(config={"mock": mock, "artifact_public_base": "https://cdn.example/art"})
    reply = ChannelReply(
        channel="twilio_sms",
        channel_user_id=OWNER_ID,
        text="pic",
        attachments=[Attachment(kind="image", ref="art:abc123def4560000")],
    )
    await adapter.send(reply)
    assert mock.send_log[-1].get("MediaUrl") == "https://cdn.example/art/abc123def4560000"


async def test_outbound_unresolvable_art_ref_is_skipped_not_dropped(mock):
    adapter = Adapter(config={"mock": mock})  # no public base configured
    reply = ChannelReply(
        channel="twilio_sms",
        channel_user_id=OWNER_ID,
        text="pic",
        attachments=[Attachment(kind="image", ref="art:abc123def4560000")],
    )
    result = await adapter.send(reply)
    out = mock.send_log[-1]
    assert "MediaUrl" not in out  # no reachable URL -> not attached
    assert result.get("skipped_media") == ["art:abc123def4560000"]  # recorded, not silent


def test_inbound_form_coerces_and_lists_media():
    raw = {
        "From": "+1",
        "To": "+2",
        "Body": "hi",
        "NumMedia": "2",
        "MediaUrl0": "https://m/0.jpg",
        "MediaContentType0": "image/jpeg",
        "MediaUrl1": "https://m/1.mp4",
        "MediaContentType1": "video/mp4",
    }
    form = TwilioInboundForm.from_raw(raw)
    assert form.NumMedia == 2  # coerced str -> int
    items = form.media_items()
    assert [i.url for i in items] == ["https://m/0.jpg", "https://m/1.mp4"]
    assert [i.content_type for i in items] == ["image/jpeg", "video/mp4"]


def test_inbound_form_tolerates_garbage_num_media():
    form = TwilioInboundForm.from_raw({"From": "+1", "NumMedia": "not-a-number"})
    assert form.NumMedia == 0
    assert form.media_items() == []
