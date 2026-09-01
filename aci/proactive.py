"""
Proactivity — turn learned behaviour (patterns.py) into timely suggestions, and, only
once a suggestion has EARNED trust, into action.

This reuses ACI's one hard-won primitive: confidence is earned from OUTCOMES, never
asserted — the same rule that makes the skill library self-curating. A suggestion begins
as a proposal. Each time you accept it, its ψ rises; each time you dismiss it, its ψ
decays. Only a *benign* action whose ψ has crossed the auto-threshold is ever performed
without asking, and even then with a one-tap undo. Bounded autonomy is therefore a
property of the data (earned ψ + a conservative benign allowlist), not a hope:

    tier "suggest"  → propose it, wait for the user
    tier "auto"     → benign + trust earned → do it, tell the user, offer undo

Everything consequential or outward-facing stays "suggest" no matter how confident.
"""
from __future__ import annotations
import time
from typing import Optional

from . import patterns as _pat

PROACTIVE_SOURCE = "PROACTIVE"

# Verbs safe to perform automatically once trusted. Anything not here is proposal-only,
# however confident — deletes, sends, purchases, settings and the like always ask.
BENIGN = {"open", "recall", "find", "search", "remember", "note", "summarize",
          "summarise", "digest", "show", "list", "play", "pause"}

_FLOOR = 0.15        # below this support, don't surface at all — noise, not a pattern
_AUTO_PSI = 2.0      # earned ψ needed before a benign action may auto-run (~10 accepts)


def _conf_monad(aci, action: str):
    for m in aci.list_monads(500, source_type=PROACTIVE_SOURCE):
        if (m.metadata or {}).get("action") == action:
            return m
    return None


def _confidence(aci, action: str) -> float:
    m = _conf_monad(aci, action)
    return float(m.truth_value) if m else 1.0    # neutral prior for an unseen action


def record_feedback(aci, action: str, accepted: bool, weight: float = 1.0) -> float:
    """Earned-confidence update: accept raises ψ, dismiss decays it (same discipline as
    skill_outcome). This is what makes proactivity self-correcting — a suggestion the user
    keeps rejecting stops being offered; one they keep taking earns the right to auto-run."""
    action = (action or "").strip()
    m = _conf_monad(aci, action)
    if m is None:
        m = aci.monadise(f"proactive:{action}", source_type=PROACTIVE_SOURCE,
                         metadata={"kind": "proactive", "action": action},
                         truth_value=1.0, summary=f"proactive:{action}", dedup=False)
    if accepted:
        m.truth_value = min(m.truth_value + 0.2 * weight, 50.0)
        m.entropy = max(m.entropy * 0.9, 0.0)
    else:
        m.truth_value = max(m.truth_value * 0.6, 0.05)     # decay, never to zero
        m.entropy = m.entropy + 0.2 * weight
    m.timestamp = int(time.time() * 1000)
    aci.store.upsert(m)
    aci.field.add(m)
    return float(m.truth_value)


def suggest(aci, hour: Optional[int] = None, dow: Optional[int] = None,
            last_action: str = "", app: str = "", min_count: int = 3) -> Optional[dict]:
    """Given the current context (time, last action), propose the single most likely next
    action — or None if nothing clears the bar. Two signals combine: sequence ('you open Y
    right after X') and time-of-day ('you usually do Z around now'), each amplified by the
    action's earned confidence. Returns {action, why, support, confidence, tier}."""
    now = time.localtime()
    hour = now.tm_hour if hour is None else hour
    dow = now.tm_wday if dow is None else dow
    pats = _pat.patterns(aci, min_count=min_count)
    if not pats:
        return None
    total = sum(p["count"] for p in pats) or 1
    cand = []                                    # (action, support, why)
    if last_action:
        for p in pats:
            if p["action"] == last_action and p["next"]:
                cand.append((p["next"], p["next_count"] / max(p["count"], 1),
                             f"you usually do this right after “{last_action}”"))
    for p in pats:
        if hour in (p["peak_hours"] or []):
            cand.append((p["action"], p["count"] / total, f"you usually do this around {hour:02d}:00"))
    best = None
    for action, support, why in cand:
        if not action or action == last_action or support < _FLOOR:
            continue
        conf = _confidence(aci, action)
        score = support * conf
        if best is None or score > best["_score"]:
            verb = action.split()[0].lower()
            tier = "auto" if (conf >= _AUTO_PSI and verb in BENIGN) else "suggest"
            best = {"action": action, "why": why, "support": round(support, 3),
                    "confidence": round(conf, 3), "tier": tier, "_score": score}
    if best:
        best.pop("_score", None)
    return best
