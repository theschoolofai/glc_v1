# IMAP/SMTP adapter — Zoho Mail (and any standard IMAP/SMTP server).
#
# Modules:
#   adapter.py      — thin orchestrator (on_message + send)
#   artifacts.py    — ephemeral attachment store
#   connection.py   — IMAP session + IDLE + reconnect
#   mime_parser.py  — pure MIME walker
#   smtp_sender.py  — SMTP STARTTLS sender
#   uid_tracker.py  — SQLite UID deduplication
#   server.py       — Zoho live demo poll loop
#   schemas.py      — Pydantic types
