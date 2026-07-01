"""Tests for Twilio webhook signature verification."""

from __future__ import annotations

from glc.channels.catalogue.twilio_sms.webhook import (
    compute_signature,
    validate_signature,
)

AUTH_TOKEN = "test_auth_token_deadbeef"
URL = "https://example.com/webhooks/twilio_sms"
PARAMS = {
    "From": "+19999999999",
    "To": "+15555550100",
    "Body": "hello",
    "MessageSid": "SM01",
}


def test_valid_signature_passes():
    sig = compute_signature(AUTH_TOKEN, URL, PARAMS)
    assert validate_signature(AUTH_TOKEN, URL, PARAMS, sig) is True


def test_tampered_body_fails():
    sig = compute_signature(AUTH_TOKEN, URL, PARAMS)
    tampered = dict(PARAMS, Body="malicious")
    assert validate_signature(AUTH_TOKEN, URL, tampered, sig) is False


def test_wrong_token_fails():
    sig = compute_signature(AUTH_TOKEN, URL, PARAMS)
    assert validate_signature("other_token", URL, PARAMS, sig) is False


def test_wrong_url_fails():
    sig = compute_signature(AUTH_TOKEN, URL, PARAMS)
    assert validate_signature(AUTH_TOKEN, URL + "?x=1", PARAMS, sig) is False


def test_missing_signature_fails():
    assert validate_signature(AUTH_TOKEN, URL, PARAMS, None) is False
    assert validate_signature(AUTH_TOKEN, URL, PARAMS, "") is False


def test_missing_token_fails():
    sig = compute_signature(AUTH_TOKEN, URL, PARAMS)
    assert validate_signature("", URL, PARAMS, sig) is False


def test_signature_independent_of_param_order():
    # Twilio sorts params by key; a reordered dict yields the same signature.
    reordered = {k: PARAMS[k] for k in reversed(list(PARAMS))}
    assert compute_signature(AUTH_TOKEN, URL, reordered) == compute_signature(AUTH_TOKEN, URL, PARAMS)
