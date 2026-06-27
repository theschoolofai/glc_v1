import asyncio
import websockets
import json
import pytest
from glc.config import get_or_create_install_token

@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires running local gateway on port 8111")
async def test_line_bridge_ws():
    token = get_or_create_install_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    async with websockets.connect("ws://localhost:8111/v1/channels/line", additional_headers=headers) as ws:
        msg = {
            "channel": "line",
            "channel_user_id": "U123456",
            "user_handle": "U123456",
            "text": "Hello test",
            "trust_level": "untrusted",
            "arrived_at": "2026-06-26T15:00:00Z"
        }
        await ws.send(json.dumps(msg))
        reply = await ws.recv()
        print("Received:", reply)

if __name__ == "__main__":
    asyncio.run(test_line_bridge_ws())
