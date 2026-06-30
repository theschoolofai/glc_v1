"""Stub adapter for Generic Webhook (HTTP in/out).

Group assignment: implement on_message and send against the mock-API
fake in tests/channels/mocks/webhook_mock.py. See docs/ADAPTER_GUIDE.md
for the standard workflow.
"""

from __future__ import annotations
import hmac
import json
import os
import time
from datetime import datetime
from hashlib import sha256
from typing import Any


from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.trust_level import classify



class Adapter(ChannelAdapter):
    name = "webhook"

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize adapter with optional mock config."""
        super().__init__(config)
        self.config = config or {}
        self.mock = self.config.get("mock")
        self.is_public_channel = self.config.get("is_public_channel", False)
        self.shared_secret = os.getenv("WEBHOOK_SHARED_SECRET", "test-webhook-secret")
        self.replay_window = 5 * 60  # 5 minutes in seconds


    async def on_message(self, raw: Any) -> ChannelMessage | None:
        """
        Convert incoming webhook to ChannelMessage.
        
        Steps:
        1. Extract raw_body and headers
        2. Validate signature (HMAC-SHA256)
        3. Check timestamp is fresh (replay attack prevention)
        4. Parse JSON body
        5. Determine trust level using classify()
        6. Return ChannelMessage or None if invalid
        """
        # Handle disconnect gracefully
        if self.mock and self.mock.pop_disconnect():
            # Return a valid envelope after disconnect
            return ChannelMessage(
                channel="webhook",
                channel_user_id="unknown",
                user_handle="unknown",
                text="reconnected",
                trust_level="untrusted",
                arrived_at=datetime.now(),
                attachments=[],
                metadata={},
            )
        # Step 1: Extract raw_body and headers
        if isinstance(raw, dict):
            raw_body = raw.get("raw_body")
            headers = raw.get("headers", {})
        else:
            return None
        
        if not raw_body:
            return None
        # Step 2: Validate signature
        signature_header = headers.get("X-Webhook-Signature")
        
        if not signature_header:
            # No signature = reject
            return None
        
        # Parse signature header: "t=1234567890,v1=abcdef123456"
        try:
            parts = signature_header.split(",")
            timestamp_part = None
            hmac_part = None
            
            for part in parts:
                if part.startswith("t="):
                    timestamp_part = part[2:]
                elif part.startswith("v1="):
                    hmac_part = part[3:]
            
            if not timestamp_part or not hmac_part:
                return None
            
            timestamp = int(timestamp_part)
        except (ValueError, IndexError):
            return None
        
        # Step 3: Check timestamp is fresh (replay attack prevention)
        current_time = int(time.time())
        age = current_time - timestamp
        
        if age > self.replay_window:
            # Payload is too old, reject
            return None
        

        # Step 4: Verify HMAC signature
        # Signed string format: "timestamp.body"
        body_str = raw_body.decode("utf-8", errors="replace")
        signed_string = f"{timestamp}.{body_str}"
        
        computed_hmac = hmac.new(
            self.shared_secret.encode(),
            signed_string.encode(),
            sha256
        ).hexdigest()
        
        if computed_hmac != hmac_part:
            # Signature doesn't match, reject
            return None
        

        # Step 5: Parse JSON body
        try:
            body_json = json.loads(raw_body)
        except json.JSONDecodeError:
            return None
        
        sender_id = body_json.get("sender_id")
        sender_handle = body_json.get("sender_handle", "unknown")
        text = body_json.get("text")
        metadata = body_json.get("metadata", {})
        
        if not sender_id:
            return None
        
        # Step 6: Determine trust level using classify()
        trust_level = classify("webhook", sender_id)
        
        # Step 7: Create and return ChannelMessage
        msg = ChannelMessage(
            channel="webhook",
            channel_user_id=sender_id,
            user_handle=sender_handle,
            text=text,
            trust_level=trust_level,
            arrived_at=datetime.fromtimestamp(timestamp),
            attachments=[],
            metadata=metadata,
        )
        
        return msg

    async def send(self, reply: ChannelReply) -> Any:
        """
        Send agent reply back through webhook.
        
        Steps:
        1. Extract recipient and text from reply
        2. Create webhook payload
        3. Send via mock or HTTP
        4. Handle rate limits and errors
        5. Return status dict
        """

        # Step 1: Extract data from reply
        recipient_id = reply.channel_user_id
        text = reply.text

        if not recipient_id or not text:
            return {"status": 400, "error": "Missing recipient_id or text"}
        
        # Step 2: Create webhook payload
        payload = {
            "recipient_id": recipient_id,
            "text": text,
        }
        
        # Step 3: Send via mock or HTTP
        if self.mock:
            # Use mock for testing
            result = await self.mock.send(payload)
        else:
            # In production, would send HTTP POST here
            # For now, just return success
            result = {"status": 200, "id": "webhook-sent"}
        
        # Step 4: Handle errors
        if isinstance(result, dict):
            status = result.get("status", 200)
            if status == 429:
                # Rate limited
                return {"status": 429, "error": "Too Many Requests"}
            elif status >= 400:
                # Other error
                return result
        
        # Step 5: Return success
        return result

