"""FastAPI bridge from real LINE webhooks.

This is live/demo wiring, not part of the narrow adapter contract tested by
tests/channels/test_line.py. It intentionally drives the same Adapter class the
tests use, with a real transport object standing in for LineMock.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from glc.channels.catalogue.line.adapter import Adapter, LineTransport
from glc.channels.envelope import ChannelReply

LINE_MESSAGE_API = "https://api.line.me/v2/bot/message"
DEFAULT_AGENT_URL = "http://127.0.0.1:8200/agent/query"
DEFAULT_ACK_TEXT = "Got it. I am working on your answer."
DEFAULT_NOT_PAIRED_TEXT = (
    "This LINE account is not paired with the assistant yet. "
    "Ask the owner to pair this LINE user id, then try again."
)
DEFAULT_AGENT_UNAVAILABLE_TEXT = "The EAG3-09 agent is unavailable right now. Please try again later."

AskAgent = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class BridgeConfig:
    access_token: str | None
    channel_secret: str | None
    agent_url: str
    ack_text: str
    not_paired_text: str
    agent_unavailable_text: str
    agent_timeout_s: float

    @classmethod
    def from_env(cls) -> BridgeConfig:
        load_dotenv()
        return cls(
            access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"),
            channel_secret=os.getenv("LINE_CHANNEL_SECRET"),
            agent_url=os.getenv("AGENT_URL", DEFAULT_AGENT_URL),
            ack_text=os.getenv("LINE_ACK_TEXT", DEFAULT_ACK_TEXT),
            not_paired_text=os.getenv("LINE_NOT_PAIRED_TEXT", DEFAULT_NOT_PAIRED_TEXT),
            agent_unavailable_text=os.getenv("LINE_AGENT_UNAVAILABLE_TEXT", DEFAULT_AGENT_UNAVAILABLE_TEXT),
            agent_timeout_s=float(os.getenv("AGENT_TIMEOUT_S", "300")),
        )


class RealLineTransport:
    """Reference ``LineTransport`` implementation: calls LINE's Messaging API
    over httpx (duck-typed replacement for ``LineMock``)."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
        self._reply_tokens: dict[str, tuple[str, float]] = {}

    def set_reply_token(self, user_id: str, token: str, ttl_s: float = 60.0) -> None:
        self._reply_tokens[user_id] = (token, time.time() + ttl_s)

    def consume_reply_token(self, user_id: str) -> str | None:
        item = self._reply_tokens.pop(user_id, None)
        if item is None:
            return None
        token, expires_at = item
        return token if expires_at >= time.time() else None

    def pop_disconnect(self) -> bool:
        return False

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = "/reply" if "replyToken" in payload else "/push"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{LINE_MESSAGE_API}{endpoint}", headers=headers, json=payload)

        try:
            body: Any = response.json()
        except ValueError:
            body = {"text": response.text}

        result = {
            "endpoint": endpoint,
            "status": response.status_code,
            "body": body,
            "x_line_request_id": response.headers.get("x-line-request-id"),
        }
        print(f"[line] outbound endpoint={endpoint} status={response.status_code}", flush=True)
        return result


def verify_line_signature(body: bytes, signature: str | None, channel_secret: str) -> bool:
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


def line_signature(body: bytes, channel_secret: str) -> str:
    """Generate a LINE-compatible signature for local smoke tests."""
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _status(result: Any) -> int:
    if isinstance(result, dict) and isinstance(result.get("status"), int):
        return int(result["status"])
    return 200


def _endpoint(result: Any) -> str | None:
    if isinstance(result, dict) and isinstance(result.get("endpoint"), str):
        return result["endpoint"]
    return None


async def ask_agent_via_http(text: str, *, config: BridgeConfig) -> str:
    async with httpx.AsyncClient(timeout=config.agent_timeout_s) as client:
        response = await client.post(config.agent_url, json={"text": text})
    response.raise_for_status()
    payload = response.json()
    answer = payload.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer
    return "(the EAG3-09 agent returned an empty answer)"


async def handle_text_event(
    *,
    adapter: Adapter,
    event: dict[str, Any],
    destination: str | None,
    config: BridgeConfig,
    ask_agent: AskAgent,
) -> dict[str, Any]:
    message = await adapter.on_message({"destination": destination, "events": [event]})
    if message is None:
        print("[line] inbound dropped before relay", flush=True)
        return {"agent_called": False, "dropped": True}

    print(
        f"[line] inbound user_id={message.channel_user_id} trust={message.trust_level} text={message.text!r}",
        flush=True,
    )

    if message.trust_level == "untrusted":
        result = await adapter.send(
            ChannelReply(
                channel="line",
                channel_user_id=message.channel_user_id,
                text=config.not_paired_text,
            )
        )
        return {
            "user_id": message.channel_user_id,
            "trust_level": message.trust_level,
            "agent_called": False,
            "not_paired": True,
            "reply_status": _status(result),
            "reply_endpoint": _endpoint(result),
        }

    ack_result = await adapter.send(
        ChannelReply(channel="line", channel_user_id=message.channel_user_id, text=config.ack_text)
    )
    ack_status = _status(ack_result)
    if ack_status == 429:
        return {
            "user_id": message.channel_user_id,
            "trust_level": message.trust_level,
            "agent_called": False,
            "ack_status": ack_status,
            "ack_endpoint": _endpoint(ack_result),
            "rate_limited": True,
        }

    try:
        answer = await ask_agent(message.text or "")
    except Exception as exc:
        print(f"[agent] error: {exc!r}", flush=True)
        answer = config.agent_unavailable_text

    answer_result = await adapter.send(
        ChannelReply(channel="line", channel_user_id=message.channel_user_id, text=answer)
    )
    return {
        "user_id": message.channel_user_id,
        "trust_level": message.trust_level,
        "agent_called": answer != config.agent_unavailable_text,
        "ack_status": ack_status,
        "ack_endpoint": _endpoint(ack_result),
        "answer_status": _status(answer_result),
        "answer_endpoint": _endpoint(answer_result),
    }


def create_app(
    *,
    config: BridgeConfig | None = None,
    transport: Any | None = None,
    ask_agent: AskAgent | None = None,
) -> FastAPI:
    config = config or BridgeConfig.from_env()
    if transport is None and config.access_token:
        # Typed binding so mypy checks RealLineTransport satisfies LineTransport.
        real: LineTransport = RealLineTransport(config.access_token)
        transport = real

    app = FastAPI(title="GLC LINE to EAG3-09 bridge")
    adapter = Adapter(config={"transport": transport}) if transport is not None else None

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "line_configured": bool(config.channel_secret and transport is not None),
            "agent_url": config.agent_url,
        }

    async def _line_webhook(request: Request, x_line_signature: str | None) -> dict[str, Any]:
        if not config.channel_secret or adapter is None:
            raise HTTPException(status_code=503, detail="LINE bridge is not configured")

        body = await request.body()
        if not verify_line_signature(body, x_line_signature, config.channel_secret):
            raise HTTPException(status_code=403, detail="bad LINE signature")

        try:
            raw = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc

        events = raw.get("events") or []
        if not events:
            print("[line] webhook verification ping: no events", flush=True)
            return {"ok": True, "events": 0, "handled": 0, "skipped": 0, "results": []}

        agent_fn = ask_agent
        if agent_fn is None:

            async def default_agent_fn(text: str) -> str:
                return await ask_agent_via_http(text, config=config)

            agent_fn = default_agent_fn

        handled = 0
        skipped = 0
        results: list[dict[str, Any]] = []
        for event in events:
            if event.get("type") != "message":
                skipped += 1
                continue
            if (event.get("message") or {}).get("type") != "text":
                skipped += 1
                continue
            handled += 1
            results.append(
                await handle_text_event(
                    adapter=adapter,
                    event=event,
                    destination=raw.get("destination"),
                    config=config,
                    ask_agent=agent_fn,
                )
            )

        return {"ok": True, "events": len(events), "handled": handled, "skipped": skipped, "results": results}

    @app.post("/callback")
    async def callback(
        request: Request, x_line_signature: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return await _line_webhook(request, x_line_signature)

    return app


app = create_app()
