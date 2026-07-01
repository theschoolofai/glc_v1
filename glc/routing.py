"""Capability-aware router. Same RPM/RPD bookkeeping as V1, but now it can
skip providers that lack a requested capability (tools/reasoning/structured/caching)."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

LIMITS = {
    "ollama": {"rpm": 9999, "rpd": 9999999, "tpm": 99999999, "cooldown": 0, "max_ctx": 32000},
    "cerebras": {
        "rpm": 30,
        "rpd": 9999,
        "tpm": 60000,
        "cooldown": 2,
        "max_ctx": 8000,
        "tokens_per_day": 1_000_000,
    },
    "groq": {"rpm": 30, "rpd": 1000, "tpm": 6000, "cooldown": 2, "max_ctx": 100000},
    "nvidia": {"rpm": 40, "rpd": 9999, "tpm": 100000, "cooldown": 2, "max_ctx": 100000},
    "gemini": {"rpm": 15, "rpd": 1000, "tpm": 250000, "cooldown": 4, "max_ctx": 1000000},
    "openrouter": {"rpm": 20, "rpd": 50, "tpm": 99999999, "cooldown": 3, "max_ctx": 100000},
    "github": {"rpm": 10, "rpd": 50, "tpm": 99999999, "cooldown": 6, "max_ctx": 8000},
}

# Multiple Gemini keys (one per Google project) fan out into gemini_1..gemini_N
# providers, each carrying an identical copy of the base "gemini" limits — every
# key is a separate project with its own free-tier quota. MAX_GEMINI_KEYS caps how
# many limit rows we generate, so there is never a gemini_N provider without one.
MAX_GEMINI_KEYS = 10
for _i in range(1, MAX_GEMINI_KEYS + 1):
    LIMITS[f"gemini_{_i}"] = dict(LIMITS["gemini"])

SHORTCUTS = {
    "g": "gemini",
    "gem": "gemini",
    "gemini": "gemini",
    "n": "nvidia",
    "nv": "nvidia",
    "nvidia": "nvidia",
    "o": "ollama",
    "oll": "ollama",
    "ollama": "ollama",
    "gr": "groq",
    "groq": "groq",
    "c": "cerebras",
    "cer": "cerebras",
    "cerebras": "cerebras",
    "or": "openrouter",
    "opr": "openrouter",
    "openrouter": "openrouter",
    "gh": "github",
    "ghb": "github",
    "github": "github",
}


def resolve(name):
    if not name:
        return None
    return SHORTCUTS.get(name.lower())


class RateState:
    def __init__(self):
        self.calls_minute = deque()
        self.tokens_minute = deque()
        self.calls_today = 0
        self.tokens_today = 0
        self.day_start = self._day_start()
        self.last_call = 0.0
        self.unavailable_until = 0.0
        self.unavailable_reason = ""

    @staticmethod
    def _day_start():
        now = time.time()
        return now - (now % 86400)

    def gc(self):
        now = time.time()
        if now - self.day_start >= 86400:
            self.calls_today = 0
            self.tokens_today = 0
            self.day_start = self._day_start()
        cutoff = now - 60
        while self.calls_minute and self.calls_minute[0] < cutoff:
            self.calls_minute.popleft()
        while self.tokens_minute and self.tokens_minute[0][0] < cutoff:
            self.tokens_minute.popleft()

    def can_use(self, limits, est_tokens=0):
        self.gc()
        now = time.time()
        if now < self.unavailable_until:
            return False, f"backoff: {self.unavailable_reason} ({self.unavailable_until - now:.0f}s left)"
        wait = limits["cooldown"] - (now - self.last_call)
        if wait > 0:
            return False, f"cooldown ({wait:.1f}s)"
        if len(self.calls_minute) >= limits["rpm"]:
            return False, "RPM limit"
        if self.calls_today >= limits["rpd"]:
            return False, "RPD limit"
        tpm = sum(t for _, t in self.tokens_minute)
        if tpm + est_tokens > limits["tpm"]:
            return False, "TPM limit"
        if "tokens_per_day" in limits and self.tokens_today + est_tokens > limits["tokens_per_day"]:
            return False, "daily token cap"
        return True, None

    def record(self, tokens):
        now = time.time()
        self.calls_minute.append(now)
        self.tokens_minute.append((now, tokens))
        self.calls_today += 1
        self.tokens_today += tokens
        self.last_call = now

    def mark_unavailable(self, seconds: float, reason: str):
        self.unavailable_until = time.time() + seconds
        self.unavailable_reason = reason

    def snapshot(self, limits):
        self.gc()
        now = time.time()
        tpm = sum(t for _, t in self.tokens_minute)
        return {
            "rpm_used": len(self.calls_minute),
            "rpm_limit": limits["rpm"],
            "rpd_used": self.calls_today,
            "rpd_limit": limits["rpd"],
            "tpm_used": tpm,
            "tpm_limit": limits["tpm"],
            "tokens_today": self.tokens_today,
            "tokens_per_day": limits.get("tokens_per_day"),
            "cooldown_remaining": max(0, limits["cooldown"] - (now - self.last_call))
            if self.last_call
            else 0,
            "last_call": self.last_call,
            "backoff_remaining": max(0, self.unavailable_until - now),
            "backoff_reason": self.unavailable_reason if now < self.unavailable_until else "",
        }


class Router:
    def __init__(self, providers: dict, order: list[str]):
        self.providers = providers
        self.order = self.expand(order)
        self.state = defaultdict(RateState)
        self.lock = asyncio.Lock()

    def expand(self, names):
        """Map logical names/aliases to concrete provider keys, in order.

        Applies shortcut aliases (g/gem -> gemini), fans a group name out to its
        live instances (gemini -> gemini_1..N), drops unknowns, and de-dups while
        preserving order. Routing all candidate lists through here means "gemini"
        resolves to the configured keys in the default ladder, agent pins, and
        tier routing alike."""
        out, seen = [], set()
        for n in names:
            r = resolve(n) or n
            hits = [r] if r in self.providers else [p for p in self.providers if p.startswith(r + "_")]
            for p in hits:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        return out

    def candidates(self, override=None):
        if override:
            return self.expand([override])
        return list(self.order)

    def pick(self, est_tokens, candidates, required_caps: list[str] | None = None):
        attempts = []
        for name in candidates:
            limits = LIMITS[name]
            prov = self.providers[name]
            caps = getattr(prov, "capabilities", {})
            if required_caps:
                missing = [c for c in required_caps if not caps.get(c)]
                if missing:
                    attempts.append({"provider": name, "reason": f"skipped:no_{missing[0]}"})
                    continue
            if est_tokens > limits["max_ctx"]:
                attempts.append(
                    {"provider": name, "reason": f"prompt {est_tokens} > max_ctx {limits['max_ctx']}"}
                )
                continue
            ok, why = self.state[name].can_use(limits, est_tokens)
            if ok:
                return name, attempts
            attempts.append({"provider": name, "reason": why})
        return None, attempts

    def all_status(self):
        out = {}
        for name in self.providers:
            out[name] = self.state[name].snapshot(LIMITS[name])
            out[name]["model"] = self.providers[name].model
            out[name]["capabilities"] = getattr(self.providers[name], "capabilities", {})
        return out


# -----------------------------------------------------------------------------
# V3 Router pool — separate failover ring for routing-decision LLM calls.
# Same rate-state machinery, separate state dict so router quotas never compete
# with worker quotas (provider keys are shared but providers meter per-model).
# -----------------------------------------------------------------------------

DEFAULT_ROUTER_ORDER = ["cerebras", "groq", "nvidia", "github"]


class RouterPool:
    """Failover ring for router-LLM calls. Mirrors `Router` but for the
    Perception/Memory/Decision routing classifiers. Each call is logged with
    a call_role marker (router_perception | router_memory | router_decision)
    so the dashboard can show router activity separately from worker activity.
    """

    def __init__(self, providers: dict, order: list[str]):
        self.providers = providers
        self.order = [p for p in order if p in providers]
        self.state = defaultdict(RateState)
        self.lock = asyncio.Lock()

    def candidates(self):
        return list(self.order)

    def pick(self, est_tokens=400):
        """Pick first available router provider. Caps require nothing — router
        LLMs only need to emit one word, no tools/reasoning/structured needed."""
        attempts = []
        for name in self.candidates():
            limits = LIMITS[name]
            ok, why = self.state[name].can_use(limits, est_tokens)
            if ok:
                return name, attempts
            attempts.append({"provider": name, "reason": why})
        return None, attempts

    def all_status(self):
        out = {}
        for name in self.providers:
            out[name] = self.state[name].snapshot(LIMITS[name])
            out[name]["model"] = self.providers[name].model
        return out
