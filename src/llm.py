"""Thin LLM layer: provider-agnostic, cached, instrumented, and guarded.

Four deliberate choices, each of which has a reason beyond tidiness.

*Provider-agnostic.* Calls go through `complete()`, not a vendor SDK. Swapping
Gemini for a self-hosted model is a config change, not a rewrite. For a Japanese
enterprise client this is not hypothetical: the likely objection to any LLM
feature is where the data goes, and an architecture that can move providers is
the answer to it.

*Cached to disk.* The free tier caps requests per day. Without a cache,
re-running an evaluation burns quota on questions already answered; with one,
iteration is free and results are reproducible.

*Instrumented.* Latency, token counts and estimated cost are recorded per call.
The role is explicitly about operating what you ship - "monitor quality, latency
and cost in production" - so a component that cannot report its own cost is not
finished.

*Guarded.* `_check_payload` refuses prompts that look like raw event logs. Free
-tier API data is used to improve the provider's models, so raw operation logs
must not leave the machine. Only derived material - labels, activity signatures,
aggregates - is ever sent. The guard makes that a property of the code rather
than a promise in a document.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests

from common import ROOT, BUILD

CACHE_DIR = BUILD / "llm_cache"
ENV_FILE = ROOT / ".env.local"          # gitignored; never committed
DEFAULT_MODEL = "gemini-3.8-flash"
# Tried in order when the primary returns 404 (model retired) or 503 (demand).
# Both happen in practice: gemini-2.5-flash was retired for new keys mid-project,
# and gemini-3.7-flash returned 503 on first contact.
MODEL_FALLBACKS = ("gemini-3.6-flash", "gemini-3.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Free-tier Flash is $0. Kept so cost reporting still works on a paid tier.
# Thinking tokens are billed as output and dominate short prompts - a 5-token
# question cost 74 thinking tokens against 1 visible one - so they are counted.
PRICE_PER_MTOK = {"in": 0.30, "out": 2.50}

# Markers that indicate raw log content rather than derived analysis.
_RAW_LOG_MARKERS = (
    '"event_id"', '"timestamp_ms"', '"schema_version"', '"correlation"',
    '"username_hash"', '"machine_id"', '"active_browser_tab"',
)
MAX_PROMPT_CHARS = 20_000


class LLMUnavailable(RuntimeError):
    """No API key configured. Callers should fall back to deterministic behaviour."""


class PayloadRefused(ValueError):
    """The prompt looked like raw log data. See the governance note above."""


@dataclass
class Stats:
    calls: int = 0
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: list = field(default_factory=list)
    errors: int = 0

    @property
    def est_cost_usd(self) -> float:
        return (self.tokens_in / 1e6 * PRICE_PER_MTOK["in"]
                + self.tokens_out / 1e6 * PRICE_PER_MTOK["out"])

    def summary(self) -> str:
        lat = sorted(self.latency_ms)
        p50 = lat[len(lat) // 2] if lat else 0
        p95 = lat[int(len(lat) * 0.95)] if lat else 0
        return (f"calls={self.calls} cache_hits={self.cache_hits} errors={self.errors} "
                f"tok_in={self.tokens_in} tok_out={self.tokens_out} "
                f"latency_p50={p50:.0f}ms p95={p95:.0f}ms "
                f"est_cost=${self.est_cost_usd:.4f}")


def _api_key() -> str | None:
    """Key from the environment, else from a gitignored .env.local.

    The key is never passed through code, chat or commits - it is read from a
    file the developer creates locally.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    if not ENV_FILE.exists():
        return None
    # utf-8-sig: PowerShell 5.1's `-Encoding utf8` writes a BOM, which would
    # otherwise end up glued to the first key name.
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line or ":" in line:
            name, _, val = line.partition("=" if "=" in line else ":")
            if "GEMINI" in name.upper() or "API_KEY" in name.upper():
                return val.strip().strip('"').strip("'")
        else:
            return line.strip('"').strip("'")   # a bare key on its own line
    return None


def available() -> bool:
    return _api_key() is not None


# Identifiers that must not leave the machine even without a JSON wrapper: session
# ids, and case and worklist row ids (the shape caseid.ID_RE recovers). The JSON
# markers above catch a pasted event record; these catch the same identifiers
# pasted as plain screen text, which the markers alone let through.
_RAW_ID_PATTERNS = (
    re.compile(r"\bses_\d{8}-\d{6}"),
    re.compile(r"\b[A-Z]{1,6}\d*-\d{2,10}-\d{1,6}\b"),
)


def _check_payload(text: str) -> None:
    if len(text) > MAX_PROMPT_CHARS:
        raise PayloadRefused(
            f"prompt is {len(text)} chars (limit {MAX_PROMPT_CHARS}); "
            "send a summary, not bulk data")
    for marker in _RAW_LOG_MARKERS:
        if marker in text:
            raise PayloadRefused(
                f"prompt contains {marker}, which indicates raw log content. "
                "Only derived material may leave the machine - see src/llm.py.")
    for pattern in _RAW_ID_PATTERNS:
        m = pattern.search(text)
        if m:
            raise PayloadRefused(
                f"prompt contains an identifier ({m.group(0)[:6]}...), which must not "
                "leave the machine - see src/llm.py.")


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL, use_cache: bool = True):
        self.model = model
        self.use_cache = use_cache
        self.stats = Stats()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        return CACHE_DIR / f"{key}.json"

    def complete(self, prompt: str, system: str | None = None,
                 temperature: float = 0.0, max_tokens: int = 1024) -> str:
        _check_payload(prompt)
        if system:
            _check_payload(system)

        key = hashlib.sha256(json.dumps(
            [self.model, system, prompt, temperature, max_tokens],
            ensure_ascii=False).encode()).hexdigest()[:32]
        path = self._cache_path(key)
        if self.use_cache and path.exists():
            self.stats.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["text"]

        api_key = _api_key()
        if not api_key:
            raise LLMUnavailable(
                "No GEMINI_API_KEY. Put it in .env.local (gitignored) as\n"
                "  GEMINI_API_KEY=your-key-here")

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        r = data = None
        for model in (self.model, *MODEL_FALLBACKS):
            t0 = time.time()
            r = requests.post(ENDPOINT.format(model=model),
                              headers={"x-goog-api-key": api_key,
                                       "Content-Type": "application/json"},
                              json=body, timeout=90)
            self.stats.latency_ms.append((time.time() - t0) * 1000)
            self.stats.calls += 1
            if r.status_code == 200:
                data = r.json()
                break
            if r.status_code not in (404, 503):
                break
            self.stats.errors += 1

        if data is None:
            self.stats.errors += 1
            raise RuntimeError(f"{r.status_code}: {r.text[:300]}")

        usage = data.get("usageMetadata", {})
        self.stats.tokens_in += usage.get("promptTokenCount", 0)
        # thinking tokens are billed as output but reported separately
        self.stats.tokens_out += (usage.get("candidatesTokenCount", 0)
                                  + usage.get("thoughtsTokenCount", 0))
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            self.stats.errors += 1
            raise RuntimeError(f"unexpected response shape: {json.dumps(data)[:300]}")

        if self.use_cache:
            path.write_text(json.dumps({"text": text, "usage": usage,
                                        "model": model,
                                        "latency_ms": self.stats.latency_ms[-1]},
                                       ensure_ascii=False), encoding="utf-8")
        return text


if __name__ == "__main__":
    key = _api_key()
    print(f"API key configured: {key is not None}")
    if not key:
        print(f"To enable, create {ENV_FILE} containing:\n  GEMINI_API_KEY=your-key")
        raise SystemExit(0)
    # Do not guess validity from the prefix: Google issues several key formats
    # (an "AQ." key authenticates fine). Ask the API instead.
    import requests as _rq
    _m = _rq.get("https://generativelanguage.googleapis.com/v1beta/models",
                 headers={"x-goog-api-key": key}, timeout=30)
    print(f"key accepted by ListModels: {_m.status_code == 200}")
    llm = LLM()
    print("reply:", llm.complete("Reply with exactly: ok").strip())
    print("stats:", llm.stats.summary())
    # governance guard must actually fire
    try:
        llm.complete('{"event_id": "evt_123", "timestamp_ms": 1782924264999}')
        print("GUARD FAILED - raw log payload was accepted")
    except PayloadRefused as e:
        print(f"guard OK: {e}")
