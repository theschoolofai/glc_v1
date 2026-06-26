"""Schema validator: every adapter class advertises the canonical
ChannelMessage / ChannelReply types unchanged. Run from CI.

Passing this script does not mean the adapter works — it means the
adapter has not redefined the envelope shape. Re-shaping the envelope
breaks every other adapter and the agent runtime.
"""

from __future__ import annotations

import sys

from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.channels.registry import discover

CANONICAL = {
    "ChannelMessage": ChannelMessage,
    "ChannelReply": ChannelReply,
}


def main() -> int:
    failures: list[str] = []
    for name, _cls in sorted(discover().items()):
        try:
            mod = sys.modules[f"glc.channels.catalogue.{name}.adapter"]
        except KeyError:
            __import__(f"glc.channels.catalogue.{name}.adapter")
            mod = sys.modules[f"glc.channels.catalogue.{name}.adapter"]
        for sym, want in CANONICAL.items():
            local = getattr(mod, sym, None)
            if local is None:
                continue
            if local is not want:
                failures.append(f"{name}: {sym} re-defined locally — must use glc.channels.envelope.{sym}")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print(f"OK: envelope canonical across {len(discover())} adapters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
