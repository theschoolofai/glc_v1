import os
import hmac
import hashlib
import base64
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
import httpx
import websockets
from dotenv import load_dotenv

from glc.config import get_or_create_install_token
from glc.channels.catalogue.line.adapter import Adapter
from glc.channels.envelope import ChannelReply

# Load environment variables
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GATEWAY_WS_URL = os.getenv("GATEWAY_WS_URL", "ws://localhost:8111/v1/channels/line")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    # Do not log the actual values, just the fact that they are missing
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET in environment")

adapter = Adapter()
ws_connection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ws_connection
    install_token = get_or_create_install_token()
    headers = {"Authorization": f"Bearer {install_token}"}
    
    async def ws_loop():
        global ws_connection
        while True:
            try:
                # Connect to gateway WS
                async with websockets.connect(GATEWAY_WS_URL, additional_headers=headers) as ws:
                    ws_connection = ws
                    print("Connected to glc gateway websocket.")
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if "error" in data:
                                print("Gateway returned error:", data["error"])
                                continue
                                
                            reply = ChannelReply(**data)
                            
                            # Build LINE wire payload
                            payload = await adapter.send(reply)
                            
                            endpoint = "https://api.line.me/v2/bot/message/reply" if "replyToken" in payload else "https://api.line.me/v2/bot/message/push"
                            
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(
                                    endpoint,
                                    json=payload,
                                    headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
                                )
                                if resp.status_code >= 400:
                                    # Log generically to avoid leaking user info
                                    print(f"LINE API Error: HTTP {resp.status_code}") 
                        except Exception as e:
                            # Log generically
                            print("Error processing reply message:", repr(e))
            except Exception:
                print("WS connection error, reconnecting in 2s...")
                await asyncio.sleep(2)

    bg_task = asyncio.create_task(ws_loop())
    yield
    bg_task.cancel()
    if ws_connection:
        await ws_connection.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhooks/line")
async def line_webhook(request: Request, x_line_signature: str = Header(None)):
    if not x_line_signature:
        raise HTTPException(status_code=403, detail="Missing signature")
        
    body = await request.body()
    
    # Verify signature securely
    hash = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    signature = base64.b64encode(hash).decode('utf-8')
    
    # Use hmac.compare_digest for timing attack prevention
    if not hmac.compare_digest(signature, x_line_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    if "events" not in data or not data["events"]:
        return {"status": "ok"}
    
    # Filter events in the webhook entry point
    for event in data.get("events", []):
        if event.get("type") == "message":
            # The adapter expects the native webhook format
            channel_message = await adapter.on_message({"events": [event]})
            if channel_message and ws_connection:
                try:
                    await ws_connection.send(channel_message.model_dump_json())
                except Exception:
                    print("Failed to forward message to gateway")
            
    return {"status": "ok"}
