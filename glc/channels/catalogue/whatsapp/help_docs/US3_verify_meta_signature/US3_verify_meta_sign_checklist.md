# US-3: verify_meta_signature — Strategy & Checklist

**Branch:** `feature/us3-verify-meta-signature`
**File to change:** `glc/channels/catalogue/whatsapp/adapter.py`
**Depends on:** nothing (Wave 1, fully parallel)
**Feeds into:** US-9 (`on_message` orchestrator)

---

## Strategy

### What US-3 delivers

A single module-level helper function in `adapter.py`:

```python
def verify_meta_signature(raw_body: bytes, headers: dict) -> bool:
```

It is the **inverse** of `_sign()` in `tests/channels/mocks/whatsapp_mock.py` —
the mock signs webhooks with HMAC-SHA256; this function verifies them.
(`_sign` creates a signature; `verify_meta_signature` checks one — same algorithm, opposite roles.)

### Algorithm (HMAC-SHA256, Meta Cloud API)

```
1. secret   = os.environ.get("WHATSAPP_APP_SECRET", "")
2. sig      = headers.get("X-Hub-Signature-256", "")
3. If secret is empty OR sig does not start with "sha256=" → return False
4. expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
5. return   hmac.compare_digest(expected, sig.removeprefix("sha256="))
```

Three invariants that must hold:
- **Missing header** (`{}`) → False, no computation attempted
- **Wrong secret** (tampered) → False, compare_digest ensures constant time
- **Correct HMAC** → True

### Why constant-time comparison matters

`hmac.compare_digest` prevents timing attacks where an attacker could brute-force
the secret by measuring how quickly string comparison short-circuits. Using `==`
instead would be a security defect even though both produce the same boolean.

### Placement decision

`verify_meta_signature` lives as a **module-level function** in `adapter.py`, NOT
as a method on `Adapter`. Reasons:
- US-9's `on_message` calls it internally — no need for it to be public API on the class
- Pure function (no `self`) is directly unit-testable without instantiating the adapter
- HANDOFF §2.7 confirms helper names and placement are the team's choice

### What US-3 does NOT do

- Does NOT touch `on_message` or `send` — those are US-9 and US-10 respectively
- Does NOT parse the JSON body — that is US-4 (`parse_meta_payload`)
- Does NOT make pytest Test 7 pass on its own — Test 7 calls `on_message`, which is
  wired up in US-9. US-3's acceptance criteria are verified manually (see §4 below).

### How the mock and function interlock

```
whatsapp_mock.py                        adapter.py
────────────────                        ──────────
_sign(body, secret):
  hmac.new(secret, body, sha256)   ←→  verify_meta_signature(raw_body, headers):
  hexdigest()                            hmac.new(secret, raw_body, sha256)
                                         hexdigest()
                                         compare_digest(expected, from_header)

queue_signed_webhook()   →  (raw, {"X-Hub-Signature-256": "sha256=<hex>"})
queue_unsigned_webhook() →  (raw, {})
queue_tampered_webhook() →  (raw, {"X-Hub-Signature-256": "sha256=<wrong>"})
```

### How Test 7 will use this function (preview, implemented in US-9)

Test 7 passes `{"raw_body": raw, "headers": headers}` to `on_message`. US-9 will
detect this Shape B input and call `verify_meta_signature(raw, headers)`. If it
returns False → `on_message` returns None. If True → continue to parse + classify.

---

## Checklist

### Pre-flight

- [x] Confirm active branch is `feature/us3-verify-meta-signature`
- [x] Confirm `WHATSAPP_APP_SECRET` is present in `.env`
      (value = `"test-app-secret"` for local runs; real value from Meta Developer Console for live tests)
- [x] Re-read `_sign()` in [whatsapp_mock.py](../../../../../../../tests/channels/mocks/whatsapp_mock.py)
      (lines 86-87) — `verify_meta_signature` is its inverse

### Implementation

- [x] Open [adapter.py](../../../adapter.py)
- [x] Add imports at the top (after `from __future__ import annotations`):
      `import hashlib`, `import hmac`, `import os`
- [x] Added `verify_meta_signature` as a **module-level function** (before the `Adapter` class):
  ```python
  def verify_meta_signature(raw_body: bytes, headers: dict) -> bool:
      secret = os.environ.get("WHATSAPP_APP_SECRET", "")
      sig_header = headers.get("X-Hub-Signature-256", "")
      if not secret or not sig_header.startswith("sha256="):
          return False
      expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
      return hmac.compare_digest(expected, sig_header.removeprefix("sha256="))
  ```
- [x] Function signature matches HANDOFF §7.3 spec:
  - Parameter 1: `raw_body: bytes`
  - Parameter 2: `headers: dict`
  - Return: `bool`
- [x] `on_message` and `send` remain `NotImplementedError` stubs — not touched

### Manual verification (3 required cases per HANDOFF §7.3)

- [x] Case 1 — unsigned (`headers={}`) → `False` **PASS**
- [x] Case 2 — tampered (wrong secret in header) → `False` **PASS**
- [x] Case 3 — valid (correct HMAC) → `True` **PASS**

### Quality gates

- [x] `ruff check glc/channels/catalogue/whatsapp/` → **All checks passed**
- [x] `mypy glc/channels/catalogue/whatsapp/` → **Success: no issues found in 5 source files**
- [x] `check_pr_boundaries.py --base integration --head HEAD` → **OK: 2 file(s) changed, all inside 'Group WhatsApp' owned paths**
      *(Note: use `--base integration` not `--base main` — local fork has no local `main` branch; script diffs commits so run after staging)*

### Commit

- [x] Staged: `glc/channels/catalogue/whatsapp/adapter.py` + `help_docs/US3_verify_meta_signature/`
- [x] Committed: `dbf3a0b` — `US-3: verify_meta_signature — HMAC-SHA256 over raw body, constant-time compare`
- [x] Push:
  ```bash
  git push -u origin feature/us3-verify-meta-signature
  ```

### Mini-PR

- [ ] Open pull request inside the fork:
  - **base:** `integration`
  - **compare:** `feature/us3-verify-meta-signature`
  - **title:** `US-3: verify_meta_signature`
  - **body:** document the 3 manual verification cases and their results
- [ ] PR description confirms: no `on_message` changes, no secret hardcoded, 3 cases verified manually
- [ ] Mini-PR approved and merged to `integration`

---

## Edge cases to be aware of (don't fix now — already handled by the spec)

| Scenario | Handled by |
|---|---|
| Header present but value is `"sha256="` (empty after prefix) | `compare_digest("expected", "")` → always False |
| Header present but value has no `"sha256="` prefix (e.g., raw hex) | `startswith("sha256=")` guard → False before computation |
| Empty secret (`WHATSAPP_APP_SECRET` not set) | `not secret` guard → False before computation |
| Body is empty bytes (`b""`) | Valid — HMAC of empty bytes is still a deterministic hash |
| Unicode characters in secret | `secret.encode()` always UTF-8 — consistent with how Meta generates the token |

---

## Dependency map: where this function is consumed

```
US-3  verify_meta_signature()
         │
         └── US-9  on_message() — detects Shape B {"raw_body": bytes, "headers": dict}
                      │           calls verify_meta_signature; returns None if False
                      │
                      └── Test 7 (test_channel_specific_behaviour_signature_verification)
                              unsigned  → None  ✓
                              tampered  → None  ✓
                              valid     → ChannelMessage ✓
```

US-9 cannot be started until US-3, US-4, US-6, and US-7 are all merged to `integration`.
US-3 itself has zero predecessors.

---

## Quick reference: Mock constants used in tests

From `tests/channels/mocks/whatsapp_mock.py`:

| Constant | Value |
|---|---|
| `DEFAULT_APP_SECRET` | `"test-app-secret"` |
| `OWNER_WA_ID` | `"919999990000"` |
| `STRANGER_WA_ID` | `"917777770000"` |
| `PHONE_NUMBER_ID` | `"10987654321"` |

The test fixture `_set_secret` (autouse) does:
```python
monkeypatch.setenv("WHATSAPP_APP_SECRET", DEFAULT_APP_SECRET)
```
So during pytest runs, `WHATSAPP_APP_SECRET` is always `"test-app-secret"`.
