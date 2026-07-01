"""Twilio webhook signature verification.

Twilio signs every webhook it sends with your account's `TWILIO_AUTH_TOKEN`
and puts the result in the `X-Twilio-Signature` HTTP header. Verifying it
proves the request genuinely came from Twilio and was not forged by someone
who merely learned the webhook URL. Without this check, an attacker can POST
`From=<owner number>` and be trusted as the owner — see README Limitation 1.

Algorithm (form-encoded POST webhooks):
  1. Start with the full request URL (including any query string).
  2. Append every POST parameter, sorted by key, as `key + value` with no
     separators.
  3. HMAC-SHA1 that string with the auth token as the key.
  4. Base64-encode the digest.
  5. Constant-time compare against the `X-Twilio-Signature` header.

Validated against Twilio's published test vector in the test suite.

Reference: https://www.twilio.com/docs/usage/security#validating-requests
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping


def expected_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    """Compute the signature Twilio would send for this request."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(
    auth_token: str,
    url: str,
    params: Mapping[str, str],
    signature: str | None,
) -> bool:
    """Return True iff `signature` is a valid Twilio signature for the request.

    `params` must be exactly the POST parameters Twilio sent — no synthetic or
    framework-added keys. A missing token or signature returns False (we fail
    closed: an unverifiable request is treated as not authentic).
    """
    if not auth_token or not signature:
        return False
    expected = expected_signature(auth_token, url, params)
    # Constant-time comparison avoids leaking how much of the signature matched.
    return hmac.compare_digest(expected, signature)
