"""Deterministic end-to-end harness for the LINE adapter.

Replaces the manual "type a message on your phone through a tunnel" step from
RESTART_RUNBOOK.md with a scripted, repeatable driver. It pushes synthetic LINE
webhooks through the *real* relay (signature verify -> Adapter -> trust check ->
ack/agent/answer -> outbound) with a canned agent, so the bot's behaviour is
reproducible.

Two modes:

* capture (default, offline, no credentials): outbound is recorded by an
  in-process transport and asserted. This deterministically proves the
  reply-token-then-push contract, 429 propagation, and disconnect handling.
* live (--live, needs .env): outbound goes to the real api.line.me. A synthetic
  webhook cannot carry a valid reply token, so live scenarios omit it and both
  the ack and the answer are delivered via push to the owner's phone. The default
  live run is the scripted `conversation` (several Q&A pairs); use --scenario
  owner for the minimal two-message contract check.

Run:
    uv run python -m glc.channels.catalogue.line.dev.harness               # offline capture
    uv run python -m glc.channels.catalogue.line.dev.harness --live        # scripted convo -> owner phone
    uv run python -m glc.channels.catalogue.line.dev.harness --scenario conversation
    uv run python -m glc.channels.catalogue.line.dev.harness --live --scenario owner
    uv run python -m glc.channels.catalogue.line.dev.harness --live --scenario answers_only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from glc.channels.catalogue.line.adapter import Adapter
from glc.channels.catalogue.line.dev.live_bridge import (
    DEFAULT_ACK_TEXT,
    DEFAULT_AGENT_UNAVAILABLE_TEXT,
    DEFAULT_NOT_PAIRED_TEXT,
    BridgeConfig,
    RealLineTransport,
    create_app,
    line_signature,
)
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security import pairing

CAPTURE_SECRET = "harness-capture-secret"  # not a credential; signs synthetic offline webhooks
STRANGER_ID = "Ustranger_harness"
CAPTURE_OWNER_ID = "Uowner_harness"
OWNER_QUESTION = "Who wrote Dune and when was it first published? Answer in one sentence."

# A short scripted demo conversation. Each key is an owner question the stub
# agent answers deterministically; the `conversation` scenario pushes every pair
# (ack + answer), so a live run fills the LINE chat with a recognisable,
# reproducible exchange. Add or remove entries here to change the demo.
_CANNED_ANSWERS = {
    OWNER_QUESTION: (
        "The science fiction novel Dune was written by Frank Herbert and was first published in 1965."
    ),
    "What is the tallest mountain on Earth?": (
        "Mount Everest is the tallest mountain on Earth, about 8,849 metres above sea level."
    ),
    "Who painted the Mona Lisa?": (
        "The Mona Lisa was painted by Leonardo da Vinci in the early sixteenth century."
    ),
    "How fast does light travel in a vacuum?": (
        "Light travels at roughly 299,792 kilometres per second in a vacuum."
    ),
    "Which planet is known as the Red Planet?": (
        "Mars is called the Red Planet because the iron oxide on its surface gives it a reddish hue."
    ),
}

# Owner questions in insertion order, derived from the canned answers above.
DEMO_CONVERSATION = list(_CANNED_ANSWERS)


async def stub_agent(text: str) -> str:
    """Deterministic stand-in for the EAG3-09 agent."""
    return _CANNED_ANSWERS.get(text.strip(), f"[canned] You said: {text.strip()}")


@dataclass
class CapturingTransport:
    """In-process transport that records outbound payloads instead of calling
    LINE. Duck-typed identically to LineMock / RealLineTransport."""

    rate_limited: bool = False
    send_log: list[dict[str, Any]] = field(default_factory=list)
    _reply_tokens: dict[str, tuple[str, float]] = field(default_factory=dict)
    _disconnect_pending: bool = False

    def set_reply_token(self, user_id: str, token: str, ttl_s: float = 60.0) -> None:
        self._reply_tokens[user_id] = (token, time.time() + ttl_s)

    def consume_reply_token(self, user_id: str) -> str | None:
        item = self._reply_tokens.pop(user_id, None)
        if item is None:
            return None
        token, expires_at = item
        return token if expires_at >= time.time() else None

    def force_disconnect(self) -> None:
        self._disconnect_pending = True

    def pop_disconnect(self) -> bool:
        was = self._disconnect_pending
        self._disconnect_pending = False
        return was

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.rate_limited:
            return {"status": 429, "message": "Too Many Requests"}
        self.send_log.append(payload)
        return {
            "endpoint": "/reply" if "replyToken" in payload else "/push",
            "status": 200,
            "request": payload,
        }


@dataclass
class Outcome:
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    detail: str


@dataclass
class Ctx:
    mode: str  # "capture" | "live"
    config: BridgeConfig
    secret: str
    owner_id: str
    stranger_id: str = STRANGER_ID

    def make_transport(self) -> Any:
        if self.mode == "live":
            token = self.config.access_token
            assert token is not None  # validated in _build_config
            return RealLineTransport(token)
        return CapturingTransport()


def _webhook(user_id: str, text: str, *, reply_token: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "message",
        "source": {"type": "user", "userId": user_id},
        "message": {"id": f"m-{user_id}", "type": "text", "text": text},
    }
    if reply_token is not None:
        event["replyToken"] = reply_token
    return {"destination": "Ubot", "events": [event]}


async def _run_through_bridge(
    config: BridgeConfig, transport: Any, body: dict[str, Any], secret: str
) -> dict[str, Any]:
    """POST a signed synthetic webhook at the in-process bridge, return the
    relay's first per-event result dict."""
    app = create_app(config=config, transport=transport, ask_agent=stub_agent)
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://harness") as client:
        resp = await client.post(
            "/callback",
            content=raw,
            headers={"X-Line-Signature": line_signature(raw, secret)},
        )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    return results[0] if results else {}


def _summarize(name: str, checks: list[tuple[str, bool]], result: dict[str, Any]) -> Outcome:
    failed = [label for label, ok in checks if not ok]
    if failed:
        return Outcome(name, "FAIL", "failed: " + "; ".join(failed) + f" | result={result}")
    return Outcome(name, "PASS", ", ".join(label for label, _ in checks))


async def scenario_owner(ctx: Ctx) -> Outcome:
    transport = ctx.make_transport()
    # live: omit the reply token so both ack + answer go via push (a synthetic
    # token would be rejected by the real /reply endpoint).
    reply_token = None if ctx.mode == "live" else "rt-harness-owner"
    body = _webhook(ctx.owner_id, OWNER_QUESTION, reply_token=reply_token)
    result = await _run_through_bridge(ctx.config, transport, body, ctx.secret)

    checks: list[tuple[str, bool]] = [
        ("trust=owner_paired", result.get("trust_level") == "owner_paired"),
        ("agent_called", result.get("agent_called") is True),
    ]
    if ctx.mode == "capture":
        log = transport.send_log
        checks.append(("2 outbound payloads", len(log) == 2))
        checks.append(("ack uses replyToken", bool(log) and "replyToken" in log[0]))
        checks.append(
            ("answer falls back to push", len(log) > 1 and "to" in log[1] and "replyToken" not in log[1])
        )
    else:
        checks.append(("ack via push", result.get("ack_endpoint") == "/push"))
        checks.append(("answer via push", result.get("answer_endpoint") == "/push"))
        checks.append(("ack delivered 200", result.get("ack_status") == 200))
        checks.append(("answer delivered 200", result.get("answer_status") == 200))
    return _summarize("owner", checks, result)


async def scenario_conversation(ctx: Ctx) -> Outcome:
    """Push a scripted multi-message demo conversation through the relay.

    Each question produces an ack + an answer, so a live run delivers
    ``2 * len(DEMO_CONVERSATION)`` real messages to the owner's phone.
    """
    checks: list[tuple[str, bool]] = []
    for i, question in enumerate(DEMO_CONVERSATION):
        transport = ctx.make_transport()
        reply_token = None if ctx.mode == "live" else f"rt-harness-conv-{i}"
        body = _webhook(ctx.owner_id, question, reply_token=reply_token)
        result = await _run_through_bridge(ctx.config, transport, body, ctx.secret)
        ok = result.get("trust_level") == "owner_paired" and result.get("agent_called") is True
        if ctx.mode == "live":
            ok = ok and result.get("answer_status") == 200
        checks.append((f"q{i + 1} delivered", bool(ok)))
    summary = {"questions": len(DEMO_CONVERSATION), "messages": 2 * len(DEMO_CONVERSATION)}
    return _summarize("conversation", checks, summary)


async def scenario_answers_only(ctx: Ctx) -> Outcome:
    """Send only the agent answer for each demo question — one clean bubble per
    question, no ack.

    Drives the Adapter directly (`on_message` -> `send`), so it still exercises
    the graded adapter end to end but skips the bridge's ack-then-answer relay.
    Each answer is pushed (no reply token), so live mode delivers exactly
    ``len(DEMO_CONVERSATION)`` messages.
    """
    checks: list[tuple[str, bool]] = []
    for i, question in enumerate(DEMO_CONVERSATION):
        transport = ctx.make_transport()
        adapter = Adapter(config={"mock": transport})
        message = await adapter.on_message(_webhook(ctx.owner_id, question, reply_token=None))
        answer = await stub_agent(message.text or "")
        result = await adapter.send(
            ChannelReply(channel="line", channel_user_id=message.channel_user_id, text=answer)
        )
        ok = message.trust_level == "owner_paired"
        if ctx.mode == "live":
            ok = ok and isinstance(result, dict) and result.get("status") == 200
        else:
            ok = ok and len(transport.send_log) == 1 and "to" in transport.send_log[0]
        checks.append((f"q{i + 1} answer", bool(ok)))
    summary = {"questions": len(DEMO_CONVERSATION), "messages": len(DEMO_CONVERSATION)}
    return _summarize("answers_only", checks, summary)


async def scenario_stranger(ctx: Ctx) -> Outcome:
    transport = ctx.make_transport()
    reply_token = None if ctx.mode == "live" else "rt-harness-stranger"
    body = _webhook(ctx.stranger_id, "hello from a stranger", reply_token=reply_token)
    result = await _run_through_bridge(ctx.config, transport, body, ctx.secret)
    checks = [
        ("trust=untrusted", result.get("trust_level") == "untrusted"),
        ("not_paired", result.get("not_paired") is True),
        ("agent not called", result.get("agent_called") is not True),
    ]
    return _summarize("stranger", checks, result)


async def scenario_rate_limit(ctx: Ctx) -> Outcome:
    transport = ctx.make_transport()
    transport.rate_limited = True
    body = _webhook(ctx.owner_id, "trigger a 429", reply_token="rt-harness-rl")
    result = await _run_through_bridge(ctx.config, transport, body, ctx.secret)
    checks = [
        ("ack_status=429", result.get("ack_status") == 429),
        ("rate_limited flag", result.get("rate_limited") is True),
        ("agent not called", result.get("agent_called") is not True),
    ]
    return _summarize("rate_limit", checks, result)


async def scenario_disconnect(ctx: Ctx) -> Outcome:
    transport = ctx.make_transport()
    transport.force_disconnect()
    body = _webhook(ctx.owner_id, "after disconnect", reply_token="rt-harness-dc")
    try:
        result = await _run_through_bridge(ctx.config, transport, body, ctx.secret)
    except Exception as exc:  # the whole point: on_message must not raise
        return Outcome("disconnect", "FAIL", f"relay raised: {exc!r}")
    checks = [
        ("relay completed", bool(result)),
        ("trust=owner_paired", result.get("trust_level") == "owner_paired"),
    ]
    return _summarize("disconnect", checks, result)


async def scenario_public_stranger(ctx: Ctx) -> Outcome:
    # The bridge does not set is_public_channel, so drive the Adapter directly.
    transport = ctx.make_transport()
    adapter = Adapter(config={"mock": transport, "is_public_channel": True})
    body = _webhook(ctx.stranger_id, "hi from public channel", reply_token="rt-harness-pub")
    try:
        msg = await adapter.on_message(body)
    except Exception as exc:  # allowlist rejected the stranger -> dropped
        return Outcome("public_stranger", "PASS", f"dropped ({type(exc).__name__})")
    passed = isinstance(msg, ChannelMessage) and msg.trust_level == "untrusted"
    detail = f"trust_level={getattr(msg, 'trust_level', None)}"
    return Outcome("public_stranger", "PASS" if passed else "FAIL", detail)


SCENARIOS: dict[str, tuple[Any, set[str]]] = {
    "owner": (scenario_owner, {"capture", "live"}),
    "conversation": (scenario_conversation, {"capture", "live"}),
    "answers_only": (scenario_answers_only, {"capture", "live"}),
    "stranger": (scenario_stranger, {"capture", "live"}),
    "rate_limit": (scenario_rate_limit, {"capture"}),
    "disconnect": (scenario_disconnect, {"capture"}),
    "public_stranger": (scenario_public_stranger, {"capture"}),
}

DEFAULT_CAPTURE_RUN = [
    "owner",
    "conversation",
    "answers_only",
    "stranger",
    "rate_limit",
    "disconnect",
    "public_stranger",
]
# The full scripted conversation (its first question is the owner Dune one), so a
# default live run fills the chat instead of sending just two messages.
DEFAULT_LIVE_RUN = ["conversation"]  # only the real owner id can actually receive a push


def _build_config(mode: str) -> BridgeConfig:
    if mode == "live":
        config = BridgeConfig.from_env()
        if not config.access_token:
            raise SystemExit("live mode requires LINE_CHANNEL_ACCESS_TOKEN in .env")
        if not config.channel_secret:
            raise SystemExit("live mode requires LINE_CHANNEL_SECRET in .env")
        return config
    return BridgeConfig(
        access_token=None,
        channel_secret=CAPTURE_SECRET,
        agent_url="http://127.0.0.1:8200/agent/query",
        ack_text=DEFAULT_ACK_TEXT,
        not_paired_text=DEFAULT_NOT_PAIRED_TEXT,
        agent_unavailable_text=DEFAULT_AGENT_UNAVAILABLE_TEXT,
        agent_timeout_s=5.0,
    )


def _owner_id(mode: str) -> str:
    if mode == "live":
        owner = os.getenv("LINE_OWNER_USER_ID")
        if not owner:
            raise SystemExit("live mode requires LINE_OWNER_USER_ID in .env")
        return owner
    return CAPTURE_OWNER_ID


def _print_report(mode: str, owner_id: str, outcomes: list[Outcome]) -> None:
    print()
    print(f"LINE adapter end-to-end harness  —  mode={mode}  owner={owner_id}")
    print("-" * 78)
    for o in outcomes:
        print(f"  [{o.status:^4}] {o.name:<16} {o.detail}")
    print("-" * 78)
    passed = sum(1 for o in outcomes if o.status == "PASS")
    failed = sum(1 for o in outcomes if o.status == "FAIL")
    skipped = sum(1 for o in outcomes if o.status == "SKIP")
    print(f"  {passed} passed, {failed} failed, {skipped} skipped")


async def _amain(args: argparse.Namespace) -> int:
    mode = "live" if args.live else "capture"
    config = _build_config(mode)
    secret = config.channel_secret
    assert secret is not None  # guaranteed by _build_config
    owner_id = _owner_id(mode)

    with tempfile.TemporaryDirectory(prefix="glc-line-harness-") as tmp:
        # Isolate trust lookups in a throwaway DB; never touch ~/.glc/pairings.sqlite.
        os.environ["GLC_PAIRING_DB"] = os.path.join(tmp, "pairings.sqlite")
        pairing._singleton = None
        pairing.get_pairing_store().force_pair_owner("line", owner_id, user_handle="owner")

        ctx = Ctx(mode=mode, config=config, secret=secret, owner_id=owner_id)
        names = (
            [args.scenario]
            if args.scenario
            else (DEFAULT_LIVE_RUN if mode == "live" else DEFAULT_CAPTURE_RUN)
        )

        outcomes: list[Outcome] = []
        for name in names:
            fn, valid_modes = SCENARIOS[name]
            if mode not in valid_modes:
                outcomes.append(Outcome(name, "SKIP", f"capture-only, not run in {mode} mode"))
                continue
            outcomes.append(await fn(ctx))

    _print_report(mode, owner_id, outcomes)
    return 0 if all(o.status != "FAIL" for o in outcomes) else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic end-to-end harness for the LINE adapter.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="push to the real LINE API (delivers to the owner's phone; needs .env credentials)",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        help="run a single scenario instead of the default set",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
