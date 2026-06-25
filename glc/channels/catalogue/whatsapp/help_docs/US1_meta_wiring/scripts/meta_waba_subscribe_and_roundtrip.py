"""
US-1 Phase B — Steps 14 & 15 via Python

Step 14: Subscribe WABA to receive message webhooks on the app.
Step 15: Send a test outbound message and confirm round-trip.

Run from repo root:
    uv run python glc/channels/catalogue/whatsapp/help_docs/US1_meta_wiring/scripts/meta_waba_subscribe_and_roundtrip.py [recipient_number]

recipient_number: E.164 without '+', e.g. <your-personal-number>
If omitted, the script prompts for it.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


def _find_repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("pyproject.toml not found — run from within the repo")


load_dotenv(_find_repo_root() / ".env")

PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
TOKEN           = os.environ.get("WHATSAPP_TOKEN", "")
APP_SECRET      = os.environ.get("WHATSAPP_APP_SECRET", "")
VERIFY_TOKEN    = os.environ.get("WHATSAPP_VERIFY_TOKEN", "glc-verify-token-us1")
WABA_ID         = os.environ.get("WHATSAPP_WABA_ID", "")
APP_ID          = os.environ.get("WHATSAPP_APP_ID", "")

BASE = "https://graph.facebook.com/v20.0"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _post_form(path: str, fields: dict, label: str) -> dict:
    """POST application/x-www-form-urlencoded; returns parsed JSON."""
    url = f"{BASE}/{path}"
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    print(f"\n  → POST {url}")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"  ← {resp.status} OK")
            print(json.dumps(result, indent=4))
            return result
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            result = json.loads(raw)
        except Exception:
            result = {"raw": raw.decode(errors="replace")}
        print(f"  ← HTTP {e.code} ERROR")
        print(json.dumps(result, indent=4))
        return result


def _post_json(path: str, payload: dict, token: str, label: str) -> dict:
    """POST application/json with Bearer token; returns parsed JSON."""
    url = f"{BASE}/{path}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    print(f"\n  → POST {url}")
    print(f"  → payload: {json.dumps(payload, indent=4)}")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"  ← {resp.status} OK")
            print(json.dumps(result, indent=4))
            return result
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            result = json.loads(raw)
        except Exception:
            result = {"raw": raw.decode(errors="replace")}
        print(f"  ← HTTP {e.code} ERROR")
        print(json.dumps(result, indent=4))
        return result


# ---------------------------------------------------------------------------
# Step 14 — Subscribe WABA to app webhooks
# ---------------------------------------------------------------------------

def step14_subscribe_waba() -> bool:
    print("\n" + "=" * 60)
    print("STEP 14 — Subscribe WABA to messages webhook field")
    print("=" * 60)

    if not WABA_ID:
        print("\n❌ WHATSAPP_WABA_ID is not set in .env")
        print("   Add it and re-run. The WABA ID is the numeric ID shown")
        print("   on the 'Step 1. Try it out' panel (WhatsApp Business Account ID).")
        return False

    # Attempt 1: user access token (60-day token) — preferred; needs
    # whatsapp_business_management permission.
    print("\nAttempt 1 — user token (WHATSAPP_TOKEN)")
    result = _post_form(
        f"{WABA_ID}/subscribed_apps",
        {"access_token": TOKEN},
        "step14-user-token",
    )
    if result.get("success"):
        print("\n✅ Step 14 done — WABA subscribed to app webhooks via user token")
        return True

    # Attempt 2: app access token (APP_ID|APP_SECRET) — works if the app
    # has already been granted access to the WABA.
    if APP_ID and APP_SECRET:
        print("\nAttempt 2 — app access token (WHATSAPP_APP_ID|WHATSAPP_APP_SECRET)")
        result = _post_form(
            f"{WABA_ID}/subscribed_apps",
            {"access_token": f"{APP_ID}|{APP_SECRET}"},
            "step14-app-token",
        )
        if result.get("success"):
            print("\n✅ Step 14 done — WABA subscribed to app webhooks via app token")
            return True
    else:
        print("\n  (skipping app-token attempt — WHATSAPP_APP_ID not set in .env)")

    print("\n❌ Step 14 failed. Check the error above.")
    print("   If code=200: the WABA isn't linked to this app — go to")
    print("   developers.facebook.com → WhatsApp → Configuration → Webhook")
    print("   and click Subscribe next to 'messages' manually.")
    return False


# ---------------------------------------------------------------------------
# Step 15 — Round-trip test
# ---------------------------------------------------------------------------

def step15_send_message(recipient: str) -> bool:
    print("\n" + "=" * 60)
    print("STEP 15 — Outbound round-trip test")
    print("=" * 60)

    if not PHONE_NUMBER_ID:
        print("❌ WHATSAPP_PHONE_NUMBER_ID not set in .env")
        return False
    if not TOKEN:
        print("❌ WHATSAPP_TOKEN not set in .env")
        return False

    result = _post_json(
        f"{PHONE_NUMBER_ID}/messages",
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": "Round-trip confirmed from GLC US-1!"},
        },
        TOKEN,
        "step15",
    )

    if result.get("messages"):
        msg_id = result["messages"][0].get("id", "?")
        print(f"\n✅ Step 15 done — message sent, id={msg_id}")
        print("   Check your phone. Then send a reply to confirm the inbound leg.")
        return True

    err = result.get("error", {})
    code = err.get("code")
    if code == 131047:
        print("\n❌ Error 131047: 24-hour messaging window is closed.")
        print("   Send a message TO the test number from your phone first,")
        print("   then re-run this script.")
    elif code == 190:
        print("\n❌ Error 190: access token is invalid or expired.")
        print("   Regenerate WHATSAPP_TOKEN (Step 8) or exchange for 60-day (Step 10).")
    else:
        print("\n❌ Step 15 failed — see error above.")
    return False


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

def main():
    print("GLC US-1 Phase B — Steps 14 & 15")
    print("-" * 40)
    print(f"PHONE_NUMBER_ID = {PHONE_NUMBER_ID or '(NOT SET)'}")
    print(f"TOKEN           = {'(set)' if TOKEN else '(NOT SET)'}")
    print(f"APP_SECRET      = {'(set)' if APP_SECRET else '(NOT SET)'}")
    print(f"WABA_ID         = {WABA_ID or '(NOT SET — add WHATSAPP_WABA_ID to .env)'}")
    print(f"APP_ID          = {APP_ID or '(NOT SET — add WHATSAPP_APP_ID to .env)'}")

    step14_subscribe_waba()

    recipient = sys.argv[1] if len(sys.argv) > 1 else input(
        "\nEnter recipient number (E.164 no '+', e.g. 919886501991): "
    ).strip()
    step15_send_message(recipient)


if __name__ == "__main__":
    main()
