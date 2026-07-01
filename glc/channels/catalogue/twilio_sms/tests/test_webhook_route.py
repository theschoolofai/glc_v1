"""Sandbox-safe tests for the webhook receiver app (build_app).

These use FastAPI's TestClient with a fake adapter + recording callback.
They do NOT touch the gateway WS or the ~/.glc pairing store, so they run
cleanly in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from glc.channels.catalogue.twilio_sms import artifacts
from glc.channels.catalogue.twilio_sms.webhook import (
    WEBHOOK_PATH,
    build_app,
    compute_signature,
)
from glc.channels.envelope import ChannelMessage

AUTH_TOKEN = "test_token_abc123"
BASE = "http://testserver"


class FakeAdapter:
    """Minimal adapter: parses a form into a ChannelMessage."""

    async def on_message(self, form):
        return ChannelMessage(
            channel="twilio_sms",
            channel_user_id=form.get("From", ""),
            user_handle=form.get("From", ""),
            text=form.get("Body") or None,
            trust_level="owner_paired",
            arrived_at=datetime.now(UTC),
        )


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("GLC_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv("GLC_TWILIO_SKIP_SIG", raising=False)


def _client_and_seen():
    seen: list[ChannelMessage] = []

    async def handle_message(msg):
        seen.append(msg)

    app = build_app(FakeAdapter(), handle_message)
    return TestClient(app), seen


def test_valid_signature_accepted_and_handled():
    client, seen = _client_and_seen()
    form = {"From": "+19999999999", "To": "+15555550100", "Body": "hi", "NumMedia": "0"}
    sig = compute_signature(AUTH_TOKEN, f"{BASE}{WEBHOOK_PATH}", form)

    resp = client.post(WEBHOOK_PATH, data=form, headers={"X-Twilio-Signature": sig})

    assert resp.status_code == 200
    assert "<Response></Response>" in resp.text
    assert len(seen) == 1
    assert isinstance(seen[0], ChannelMessage)
    assert seen[0].channel_user_id == "+19999999999"
    assert seen[0].text == "hi"


def test_bad_signature_rejected_403():
    client, seen = _client_and_seen()
    form = {"From": "+19999999999", "Body": "hi", "NumMedia": "0"}

    resp = client.post(WEBHOOK_PATH, data=form, headers={"X-Twilio-Signature": "wrong"})

    assert resp.status_code == 403
    assert seen == []  # handler never called on a forged webhook


def test_missing_signature_rejected_403():
    client, seen = _client_and_seen()
    form = {"From": "+19999999999", "Body": "hi", "NumMedia": "0"}

    resp = client.post(WEBHOOK_PATH, data=form)

    assert resp.status_code == 403
    assert seen == []


def test_skip_sig_env_bypasses_verification(monkeypatch):
    monkeypatch.setenv("GLC_TWILIO_SKIP_SIG", "1")
    client, seen = _client_and_seen()
    form = {"From": "+19999999999", "Body": "hi", "NumMedia": "0"}

    resp = client.post(WEBHOOK_PATH, data=form)  # no signature

    assert resp.status_code == 200
    assert len(seen) == 1


def test_artifact_route_serves_stored_bytes():
    client, _ = _client_and_seen()
    ref = artifacts.put(b"\xff\xd8\xff jpeg", content_type="image/jpeg")
    sha = ref.removeprefix("art:")

    resp = client.get(f"/artifacts/{sha}")

    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff jpeg"
    assert resp.headers["content-type"].startswith("image/jpeg")


def test_artifact_route_404_for_unknown_or_bad_sha():
    client, _ = _client_and_seen()
    assert client.get("/artifacts/deadbeefdeadbeef").status_code == 404
    # Traversal / non-hex shas resolve to None via the store's _validate_ref.
    assert client.get("/artifacts/notavalidsha").status_code == 404
