"""Trust-level setup helper for local Teams adapter demos.

Manages the pairing store (~/.glc/pairings.sqlite) so you can demo
all three trust levels against the Bot Framework Emulator without
going through the full pairing flow.

Usage (run from repo root):
    # Show current pairings
    python glc/channels/catalogue/teams/setup/trust_setup.py --show

    # Pair as owner (trust=owner_paired)
    python glc/channels/catalogue/teams/setup/trust_setup.py --owner

    # Pair as regular user (trust=user_paired)
    python glc/channels/catalogue/teams/setup/trust_setup.py --user

    # Revert to untrusted (removes pairing)
    python glc/channels/catalogue/teams/setup/trust_setup.py --revoke

    # Override the user ID (defaults to the Emulator's stable anonymous ID)
    python glc/channels/catalogue/teams/setup/trust_setup.py --owner --user-id <id>

How to find your Emulator user ID:
    Start local_emulator_runner.py, send any message, and look for:
        Received activity ... from='<id>'
    in the server terminal. Pass that ID via --user-id if it differs
    from the default below.
"""

from __future__ import annotations

import argparse
import sys
import time

CHANNEL = "teams"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage Teams adapter trust levels for local demo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--owner",
        action="store_true",
        help="Pair user as owner_paired (highest trust)",
    )
    group.add_argument(
        "--user",
        action="store_true",
        help="Pair user as user_paired (standard trust)",
    )
    group.add_argument(
        "--revoke",
        action="store_true",
        help="Remove pairing — next message will be untrusted",
    )
    group.add_argument(
        "--show",
        action="store_true",
        help="Show all current pairings for the teams channel",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        metavar="ID",
        help=(
            "Emulator user ID. Find it in the server logs: "
            "Received activity ... from='<id>'. "
            "Required for --owner / --user / --revoke."
        ),
    )
    parser.add_argument(
        "--handle",
        default="demo-user",
        metavar="NAME",
        help="Display name stored with the pairing (default: demo-user)",
    )

    args = parser.parse_args()

    from glc.security.pairing import _conn, get_pairing_store  # noqa: PLC0415

    store = get_pairing_store()

    # --show works without a user-id; all other actions require one
    if not args.show and args.user_id is None:
        print("Error: --user-id is required for this action.")
        print("Find it in the server logs:")
        print("  Received activity type='message' from='<id>'")
        print("Then run:")
        print(f"  trust_setup.py {sys.argv[1]} --user-id <id>")
        return 1

    if args.show:
        records = [r for r in store.all_pairings() if r.channel == CHANNEL]
        if not records:
            print("No pairings for the 'teams' channel.")
        else:
            print(f"{'User ID':<45} {'Handle':<15} {'Trust level'}")
            print("-" * 75)
            for r in records:
                print(f"{r.channel_user_id:<45} {r.user_handle:<15} {r.trust_level}")
        return 0

    if args.owner:
        store.force_pair_owner(CHANNEL, args.user_id, user_handle=args.handle)
        print(f"✓ Paired {args.user_id!r} as owner_paired")
        print("  Next message in Emulator → trust=owner_paired")
        return 0

    if args.user:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO pairings "
                "(channel, channel_user_id, user_handle, trust_level, paired_at) "
                "VALUES (?,?,?,?,?)",
                (CHANNEL, args.user_id, args.handle, "user_paired", time.time()),
            )
        print(f"✓ Paired {args.user_id!r} as user_paired")
        print("  Next message in Emulator → trust=user_paired")
        return 0

    if args.revoke:
        removed = store.revoke(CHANNEL, args.user_id)
        if removed:
            print(f"✓ Revoked pairing for {args.user_id!r}")
            print("  Next message in Emulator → trust=untrusted")
        else:
            print(f"  No pairing found for {args.user_id!r} — already untrusted")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
