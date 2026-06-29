"""Mock for local microphone testing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import time

OWNER_ID = "owner_id"
STRANGER_ID = "stranger_id"


@dataclass
class MockMessageEvent:
    audio_data: bytes
    channel_user_id: str
    timestamp: float = 0.0


class LocalMicMock:
    """Mock for local microphone testing."""

    def __init__(self):
        self.play_log: List[bytes] = []
        self._disconnected = False
        self.rate_limited = False
        self._current_user_id = None
        self._messages: List[MockMessageEvent] = []
        self._pop_disconnect_called = False
        self._send_calls: List[Dict[str, Any]] = []

    def pop_disconnect(self) -> bool:
        """Check if disconnect was triggered and clear it."""
        if self._disconnected:
            self._disconnected = False
            self._pop_disconnect_called = True
            return True
        return False

    def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Mock send method for rate limiting."""
        self._send_calls.append(payload)
        if self.rate_limited:
            return {"status": 429}
        return {"status": "sent"}

    def queue_owner_message(self, text: str = "hello") -> MockMessageEvent:
        """Queue a message from owner."""
        audio_data = bytes([i % 256 for i in range(1000)])
        event = MockMessageEvent(
            audio_data=audio_data,
            channel_user_id=OWNER_ID,
            timestamp=time.time()
        )
        self._current_user_id = OWNER_ID
        self._messages.append(event)
        return event

    def queue_stranger_message(self, text: str = "hi") -> MockMessageEvent:
        """Queue a message from stranger."""
        audio_data = bytes([i % 256 for i in range(1000)])
        event = MockMessageEvent(
            audio_data=audio_data,
            channel_user_id=STRANGER_ID,
            timestamp=time.time()
        )
        self._current_user_id = STRANGER_ID
        self._messages.append(event)
        return event

    def queue_silence(self) -> MockMessageEvent:
        """Queue a silence message."""
        audio_data = bytes([0] * 1000)
        event = MockMessageEvent(
            audio_data=audio_data,
            channel_user_id=OWNER_ID,
            timestamp=time.time()
        )
        self._current_user_id = OWNER_ID
        self._messages.append(event)
        return event

    def force_disconnect(self):
        """Force a disconnect."""
        self._disconnected = True

    def play(self, audio_data: bytes):
        """Mock play function."""
        if self._disconnected:
            raise Exception("Adapter disconnected")
        self.play_log.append(audio_data)
