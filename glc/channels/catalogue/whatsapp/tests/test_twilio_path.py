from unittest.mock import patch

from twilio.request_validator import RequestValidator

from glc.channels.catalogue.whatsapp.adapter import verify_twilio_signature


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

