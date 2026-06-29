"""Local glue server -- bridges Bot Framework Emulator to the real
Teams adapter (glc/channels/catalogue/teams/adapter.py) without
needing GLC's gateway, an Azure Bot resource, or a Teams tenant.

Run from the repo root:
    uv run python glc/channels/catalogue/teams/setup/emulator_runner.py

Then in Bot Framework Emulator:
    1. Click "Open Bot"
    2. Bot URL: http://localhost:3978/api/messages
    3. Leave Microsoft App ID / Password BLANK (anonymous local testing)
    4. Click Connect, then type a message.

Trust level demo:
    By default all messages arrive as trust=untrusted. Use trust_setup.py
    to pair the Emulator user before sending a message:

        # owner trust
        python glc/channels/catalogue/teams/setup/trust_setup.py --owner

        # regular user trust
        python glc/channels/catalogue/teams/setup/trust_setup.py --user

        # back to untrusted
        python glc/channels/catalogue/teams/setup/trust_setup.py --revoke
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from glc.channels.catalogue.teams.adapter import Adapter
from glc.channels.envelope import ChannelReply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("emulator_runner")

app = FastAPI()
adapter = Adapter(config={})


@app.post("/api/messages")
async def messages(request: Request) -> Any:
    try:
        activity = await request.json()
        log.info(
            "Received activity type=%r from=%r text=%r",
            activity.get("type"),
            (activity.get("from") or {}).get("id"),
            activity.get("text"),
        )

        msg = await adapter.on_message(activity)

        if msg is None:
            log.info("on_message returned None — skipping reply")
            return {}

        log.info(
            "Parsed message: text=%r trust=%r user=%r",
            msg.text,
            msg.trust_level,
            msg.channel_user_id,
        )

        reply_text = f"GLC teams adapter received: {msg.text!r} (trust={msg.trust_level})"
        reply = ChannelReply(
            channel="teams",
            channel_user_id=msg.channel_user_id,
            text=reply_text,
            thread_id=msg.thread_id,
        )

        if os.environ.get("TEAMS_APP_ID"):
            await adapter.send(reply)
            return {}
        else:
            log.info("Returning inline reply: %r", reply_text)
            return {
                "type": "message",
                "text": reply_text,
                "replyToId": msg.thread_id,
            }

    except Exception:
        log.error("Unhandled exception:\n%s", traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": "internal error — see server terminal"},
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3978)
