"""Isolate GLC state for the twilio_sms adapter test suite.

The repo-level tests/conftest.py only covers the tests/ tree, so tests that
live here (e.g. test_extra.py, which calls force_pair_owner) would otherwise
write to the real ~/.glc pairing DB. This mirrors that isolation: each test
gets fresh config/audit/pairing/gateway DBs under tmp, so nothing touches the
user's ~/.glc and the pairing store is writable even in a sandbox.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_glc_state(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("GLC_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("GLC_PAIRING_DB", str(tmp_path / "pairings.sqlite"))
    monkeypatch.setenv("GLC_GATEWAY_DB", str(tmp_path / "gateway.sqlite"))

    # Reset singletons that cache the config dir at first access.
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
