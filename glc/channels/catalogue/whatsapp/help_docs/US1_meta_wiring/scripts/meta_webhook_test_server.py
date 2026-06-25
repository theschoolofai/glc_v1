"""Minimal Meta webhook verification + logging server for US-1.

Run from repo root:
    uv run python glc/channels/catalogue/whatsapp/help_docs/US1_meta_wiring/scripts/meta_webhook_test_server.py

Listens on port 8765 by default (different from the main GLC server).
Reads WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN from .env at the repo root.
"""

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv


def _find_repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("pyproject.toml not found — run from within the repo")


load_dotenv(_find_repo_root() / ".env")

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "glc-verify-token-us1")
APP_SECRET   = os.environ.get("WHATSAPP_APP_SECRET", "")
PORT         = int(os.environ.get("WEBHOOK_PORT", "8765"))


def _verify_signature(body: bytes, sig_header: str) -> bool:
    if not APP_SECRET or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params    = parse_qs(parsed.query)
        mode      = (params.get("hub.mode")         or [""])[0]
        token     = (params.get("hub.verify_token") or [""])[0]
        challenge = (params.get("hub.challenge")    or [""])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN:
            print(f"[webhook] ✅ Verification OK — challenge={challenge!r}")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(challenge.encode())
        else:
            print(f"[webhook] ❌ Bad verify_token: got {token!r}, expected {VERIFY_TOKEN!r}")
            self.send_response(403)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        sig    = self.headers.get("X-Hub-Signature-256", "")

        if APP_SECRET and not _verify_signature(body, sig):
            print("[webhook] ⚠️  Signature mismatch — payload may be forged")
            self.send_response(403)
            self.end_headers()
            return

        try:
            data = json.loads(body)
            print("[webhook] ✅ Inbound payload:")
            print(json.dumps(data, indent=2))
        except Exception:
            print(f"[webhook] Raw body: {body!r}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, fmt, *args):  # silence default access log noise
        pass


if __name__ == "__main__":
    print(f"[webhook] Server listening on port {PORT}")
    print(f"[webhook] VERIFY_TOKEN = {VERIFY_TOKEN!r}")
    print(f"[webhook] APP_SECRET   = {'(set)' if APP_SECRET else '(NOT SET — signature checks skipped)'}")
    HTTPServer(("", PORT), Handler).serve_forever()
