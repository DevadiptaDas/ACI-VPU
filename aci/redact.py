"""
Secret redaction (Phase 2 / E3) - keep credentials OUT of the store.

Now that ACI can observe clipboard and screen, it must never persist passwords,
API keys, tokens, or card numbers. Two layers:
  * redact_text(s)      -> masks known secret shapes inside captured text
  * is_probably_secret  -> a whole clipboard entry that looks like a bare credential
                           is skipped entirely (not even stored redacted)
  * is_sensitive_window -> while a password manager / login screen is focused,
                           capture is suppressed altogether
Pure stdlib, deterministic, unit-tested.
"""
from __future__ import annotations
import math
import re
from collections import Counter

_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}", re.I)),
    ("credential-assign", re.compile(r"(?i)\b(pass(?:word)?|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*\S+")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

_SENSITIVE_PROC = ("keepass", "1password", "bitwarden", "lastpass", "keeper",
                   "dashlane", "protonpass", "enpass", "nordpass", "passwordsafe")
_SENSITIVE_TITLE = ("password", "sign in", "signin", "log in", "login",
                    "authenticator", "2fa", "one-time", "verify your", "passcode")


def redact_text(s: str):
    """Return (redacted_text, num_redactions)."""
    if not s:
        return s, 0
    out, n = s, 0
    for label, pat in _PATTERNS:
        out, c = pat.subn(f"[REDACTED:{label}]", out)
        n += c
    return out, n


def is_probably_secret(s: str) -> bool:
    """True if the whole string looks like a bare copied credential: no whitespace,
    credential-length, and high character-class diversity + entropy."""
    t = (s or "").strip()
    if not t or any(ws in t for ws in (" ", "\n", "\t")):
        return False
    if not (8 <= len(t) <= 256):
        return False
    classes = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    counts = Counter(t)
    entropy = -sum((c / len(t)) * math.log2(c / len(t)) for c in counts.values())
    return classes >= 3 and entropy >= 3.0


def is_sensitive_window(title: str, process: str) -> bool:
    t, p = (title or "").lower(), (process or "").lower()
    return (any(x in p for x in _SENSITIVE_PROC) or
            any(x in t for x in _SENSITIVE_TITLE))
