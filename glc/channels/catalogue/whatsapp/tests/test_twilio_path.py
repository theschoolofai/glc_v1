from __future__ import annotations

from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from twilio.request_validator import RequestValidator

from glc.channels.catalogue.whatsapp.adapter import (
    Adapter,
    provider_cache,
    verify_twilio_signature,
)
from glc.channels.envelope import ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.whatsapp_mock import OWNER_ID, WhatsappMock


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    provider_cache.clear()
    yield
    provider_cache.clear()


@pytest.fixture(autouse=True)
def _isolated_glc_state(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("GLC_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("GLC_PAIRING_DB", str(tmp_path / "pairings.sqlite"))
    monkeypatch.setenv("GLC_GATEWAY_DB", str(tmp_path / "gateway.sqlite"))

    import glc.config as _cfg

    _cfg.CONFIG_DIR = cfg
    import glc.security.pairing as _p

    _p._singleton = None
    import glc.security.rate_limits as _r

    _r._limiter = None
    import glc.policy.engine as _e

    _e._engine = None
    import glc.audit.store as _a

    _a._singleton = None
    yield


def test_verify_twilio_signature_valid():
    url = "https://example.com/webhook"
    params = {"Body": "hello", "From": "whatsapp:+123456789"}
    auth_token = "test_auth_token"

    # Compute valid signature using Twilio's RequestValidator
    validator = RequestValidator(auth_token)
    signature = validator.compute_signature(url, params)

    assert verify_twilio_signature(url, params, signature, auth_token) is True


def test_verify_twilio_signature_invalid():
    url = "https://example.com/webhook"
    params = {"Body": "hello", "From": "whatsapp:+123456789"}
    auth_token = "test_auth_token"

    assert verify_twilio_signature(url, params, "wrong_signature", auth_token) is False


def test_verify_twilio_signature_missing_credentials():
    url = "https://example.com/webhook"
    params = {"Body": "hello"}

    assert verify_twilio_signature(url, params, "sig", "") is False
    assert verify_twilio_signature(url, params, "", "token") is False
    assert verify_twilio_signature(url, params, "sig", None) is False
    assert verify_twilio_signature(url, params, None, "token") is False


def test_verify_twilio_signature_exception_handled():
    url = "https://example.com/webhook"
    params = {"Body": "hello"}
    auth_token = "test_auth_token"

    with patch("glc.channels.catalogue.whatsapp.adapter.RequestValidator") as mock_validator:
        # Mock RequestValidator to raise an exception on validation
        mock_validator.return_value.validate.side_effect = Exception("Validation failed")

        assert verify_twilio_signature(url, params, "sig", auth_token) is False


@pytest.mark.asyncio
async def test_twilio_inbound_populates_cache_and_send_uses_twilio(monkeypatch):
    adapter = Adapter(config={"mock": WhatsappMock()})
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")

    url = "https://example.com/twilio-webhook"
    auth_token = "test_auth_token"
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", url)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", auth_token)
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    params = {
        "From": "whatsapp:+919999990000",
        "Body": "hello from twilio",
        "WaId": OWNER_ID,
        "ProfileName": "owner",
        "MessageSid": "SM123",
        "NumMedia": "0",
    }
    signature = RequestValidator(auth_token).compute_signature(url, params)
    raw_body = urlencode(params).encode()

    msg = await adapter.on_message(
        {"raw_body": raw_body, "headers": {"X-Twilio-Signature": signature}}
    )
    assert msg is not None
    assert msg.metadata["provider"] == "twilio"
    assert provider_cache[OWNER_ID] == "twilio"

    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="reply via twilio")
    result = await adapter.send(reply)

    assert result["messages"]
    assert adapter.config["mock"].send_log[-1] == {
        "To": f"whatsapp:{OWNER_ID}",
        "From": "whatsapp:+14155238886",
        "Body": "reply via twilio",
    }


@pytest.mark.asyncio
async def test_send_falls_back_to_twilio_on_meta_131030_and_caches_provider(monkeypatch):
    adapter = Adapter(config={})
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")

    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    async def fake_send_meta(payload):
        assert payload["to"] == OWNER_ID
        return {
            "error": {
                "code": 131030,
                "message": "Recipient phone number not in allowed list",
            }
        }

    async def fake_send_twilio(payload):
        assert payload == {
            "To": f"whatsapp:{OWNER_ID}",
            "From": "whatsapp:+14155238886",
            "Body": "fallback",
        }
        return {"sid": "SM456", "status": "queued"}

    monkeypatch.setattr("glc.channels.catalogue.whatsapp.adapter._send_meta", fake_send_meta)
    monkeypatch.setattr("glc.channels.catalogue.whatsapp.adapter._send_twilio", fake_send_twilio)

    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="fallback")
    result = await adapter.send(reply)

    assert result == {"sid": "SM456", "status": "queued"}
    assert provider_cache[OWNER_ID] == "twilio"
