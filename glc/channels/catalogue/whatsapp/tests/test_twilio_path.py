from __future__ import annotations

import json
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from twilio.request_validator import RequestValidator

from glc.channels.catalogue.whatsapp.adapter import (
    Adapter,
    _headers,
    _is_meta_131030,
    _send_meta,
    _send_twilio,
    provider_cache,
    verify_twilio_signature,
)
from glc.channels.envelope import ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.whatsapp_mock import OWNER_ID, STRANGER_ID, WhatsappMock


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


def test_headers_accept_asgi_header_tuples():
    headers = _headers(
        {
            "headers": [
                (b"X-Twilio-Signature", b"sig-123"),
                ("X-Hub-Signature-256", "sha256=abc"),
            ]
        }
    )

    assert headers == {
        "x-twilio-signature": "sig-123",
        "x-hub-signature-256": "sha256=abc",
    }


def test_is_meta_131030_handles_int_and_string_codes():
    assert _is_meta_131030({"error": {"code": 131030}}) is True
    assert _is_meta_131030({"error": {"code": "131030"}}) is True
    assert _is_meta_131030({"error": "Unauthorized"}) is False
    assert _is_meta_131030({"error": {"code": 131047}}) is False


class _FakeResponse:
    def __init__(self, status_code: int, *, json_data=None, text: str = "oops"):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise json.JSONDecodeError("Expecting value", self.text, 0)
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return self._response


@pytest.mark.asyncio
async def test_send_meta_returns_structured_error_for_non_json_response(monkeypatch):
    monkeypatch.setattr(
        "glc.channels.catalogue.whatsapp.adapter.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeResponse(502)),
    )

    result = await _send_meta({"to": OWNER_ID})

    assert result == {
        "error": {
            "provider": "meta",
            "code": "non_json_response",
            "message": "non-JSON response",
        },
        "status": 502,
    }


@pytest.mark.asyncio
async def test_send_twilio_returns_structured_error_for_non_json_response(monkeypatch):
    monkeypatch.setattr(
        "glc.channels.catalogue.whatsapp.adapter.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeResponse(503)),
    )

    result = await _send_twilio({"To": "whatsapp:+1", "From": "whatsapp:+2", "Body": "hi"})

    assert result == {
        "error": {
            "provider": "twilio",
            "code": "non_json_response",
            "message": "non-JSON response",
        },
        "status": 503,
    }


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


@pytest.mark.asyncio
async def test_mock_send_falls_back_to_twilio_on_meta_131030_and_caches_provider(monkeypatch):
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    mock = WhatsappMock()

    async def fake_send(payload):
        if payload.get("messaging_product") == "whatsapp":
            return {"error": {"code": 131030, "message": "Recipient phone number not in allowed list"}}
        mock.send_log.append(payload)
        return {"sid": "SM789", "status": "queued"}

    mock.send = fake_send
    adapter = Adapter(config={"mock": mock})

    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="fallback")
    result = await adapter.send(reply)

    assert result == {"sid": "SM789", "status": "queued"}
    assert mock.send_log == [
        {
            "To": f"whatsapp:{OWNER_ID}",
            "From": "whatsapp:+14155238886",
            "Body": "fallback",
        }
    ]
    assert provider_cache[OWNER_ID] == "twilio"


@pytest.mark.asyncio
async def test_mock_send_does_not_cache_provider_on_error():
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")

    mock = WhatsappMock()

    async def fake_send(payload):
        return {"error": {"code": 80007, "message": "rate limited"}, "status": 429}

    mock.send = fake_send
    adapter = Adapter(config={"mock": mock})

    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="retry later")
    result = await adapter.send(reply)

    assert result["status"] == 429
    assert OWNER_ID not in provider_cache


@pytest.mark.asyncio
async def test_twilio_send_returns_config_error_when_from_env_missing():
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")
    provider_cache[OWNER_ID] = "twilio"

    adapter = Adapter(config={"mock": WhatsappMock()})
    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="reply via twilio")

    result = await adapter.send(reply)

    assert result == {
        "error": {
            "provider": "twilio",
            "code": "missing_twilio_whatsapp_from",
            "message": "TWILIO_WHATSAPP_FROM is not set",
        },
        "status": 500,
    }


@pytest.mark.asyncio
async def test_meta_fallback_returns_config_error_when_twilio_from_env_missing(monkeypatch):
    adapter = Adapter(config={})
    store = get_pairing_store()
    store.force_pair_owner("whatsapp", OWNER_ID, user_handle="owner")

    async def fake_send_meta(payload):
        return {"error": {"code": "131030", "message": "Recipient phone number not in allowed list"}}

    monkeypatch.setattr("glc.channels.catalogue.whatsapp.adapter._send_meta", fake_send_meta)

    reply = ChannelReply(channel="whatsapp", channel_user_id=OWNER_ID, text="fallback")
    result = await adapter.send(reply)

    assert result == {
        "error": {
            "provider": "twilio",
            "code": "missing_twilio_whatsapp_from",
            "message": "TWILIO_WHATSAPP_FROM is not set",
        },
        "status": 500,
    }


@pytest.mark.asyncio
async def test_public_stranger_drop_does_not_populate_provider_cache():
    adapter = Adapter(config={"mock": WhatsappMock(), "is_public_channel": True})
    raw = adapter.config["mock"].queue_stranger_message("hi from public")

    result = await adapter.on_message(raw)

    assert result is None
    assert STRANGER_ID not in provider_cache
