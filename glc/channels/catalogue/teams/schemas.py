"""Channel-specific constants/types for the teams adapter. The canonical
ChannelMessage / ChannelReply envelope lives in glc.channels.envelope and
must not be redefined here (scripts/validate_envelope.py enforces this).
"""

from __future__ import annotations

# Bot Framework attachment content-type for Adaptive Cards. See:
# https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference#adaptive-card
ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
