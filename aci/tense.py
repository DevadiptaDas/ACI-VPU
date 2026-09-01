"""
Tense / temporal-orientation detection — populates the 3D-time weights
(temporal_past / present / future) that were previously dormant.

This is a DIFFERENT axis from `valid_from` (when a fact was asserted): it captures
what time the fact's CONTENT refers to — a fact stored today can be about the past
("the loader failed last year") or the future ("maintenance is scheduled next month").

Deterministic, on-device, $0. Conservative by design: it only leans a fact past/future
when there's a clear marker, defaulting to present. Recall uses it ONLY as a tiebreaker
and ONLY when the query itself has a clear tense intent — so neutral queries are never
perturbed (no regression).
"""
from __future__ import annotations
import re

_PAST = {"was", "were", "had", "did", "failed", "delayed", "completed", "ended",
         "occurred", "happened", "previously", "former", "finished", "resolved",
         "closed", "fixed", "launched", "signed", "filed"}
_FUT = {"will", "shall", "planned", "scheduled", "upcoming", "soon", "tomorrow",
        "forthcoming", "pending", "anticipated", "expected", "due"}

# uniform fallback (matches the old dormant default so it's a no-op when undecided)
NEUTRAL = (0.15, 0.70, 0.15)


def content_tense_weights(text: str):
    """Return (past, present, future) distribution for a fact's content."""
    t = (text or "").lower()
    w = set(re.findall(r"[a-z']+", t))
    fut_words = w & _FUT
    if "due" in fut_words and "due to" in t:    # "due to" is causal, not a deadline ("due soon")
        fut_words.discard("due")
    fut = bool(fut_words) or "next " in t or "going to" in t
    past = (bool(w & _PAST) or bool(re.search(r"\b[a-z]{3,}ed\b", t))
            or "last " in t or " ago" in t)
    if fut and not past:
        return (0.10, 0.20, 0.70)
    if past and not fut:
        return (0.70, 0.20, 0.10)
    if past and fut:
        return (0.35, 0.20, 0.45)         # mixed -> slight future lean
    return NEUTRAL                          # present default


def query_tense(q: str):
    """The tense a query is asking about, or None (neutral -> no tense effect)."""
    ql = (q or "").lower()
    if any(k in ql for k in ("upcoming", "planned", "scheduled", "next ", "will ",
                             "going to", "future", "soon", "pending", "due ")):
        return "future"
    if any(k in ql for k in ("happened", "what was", "previously", "earlier",
                             "history", "last ", " ago", "did ", "used to", "former")):
        return "past"
    if any(k in ql for k in ("current", "currently", "right now", "status",
                             "at present", "as of now", "these days")):
        return "present"
    return None


def dominant(monad) -> str:
    """The monad's dominant temporal orientation."""
    p, n, f = monad.temporal_past, monad.temporal_present, monad.temporal_future
    if f >= p and f >= n:
        return "future"
    if p >= n and p >= f:
        return "past"
    return "present"
