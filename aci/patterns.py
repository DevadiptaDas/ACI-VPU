"""
Behavioral memory — ACI learns HOW you work, not just WHAT you know.

Every user action (a command issued, a file opened, an app launched) is logged as a
lightweight USAGE monad. Pattern mining reads those events back and surfaces the
recurring *shape* of your work: which actions are frequent, when in the day they happen,
and which action tends to follow which. That is the substrate the proactivity engine
(proactive.py) turns into timely suggestions — and, once a suggestion earns confidence,
into action.

This invents no new engine. A usage event is just a monad (source_type=USAGE); mining is
an ordinary scan-and-aggregate over those monads. Events are bounded (prune_usage) so
behavioral memory stays a rolling window and never crowds the knowledge store.
"""
from __future__ import annotations
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

USAGE_SOURCE = "USAGE"
_MAX_EVENTS = 4000          # behavioral memory is a rolling window, not an archive
_PRUNE_EVERY = 250          # amortise the cap check — prune once every N logged events
_since_prune = 0


def _bucket(ts_ms: int):
    lt = time.localtime(ts_ms / 1000.0)
    return lt.tm_hour, lt.tm_wday          # hour 0-23, weekday 0=Mon..6=Sun


def log_event(aci, action: str, target: str = "", app: str = "",
              ts: Optional[int] = None, meta: Optional[dict] = None):
    """Record one thing the user did. Cheap, dedup OFF — each occurrence is its own event
    in time, which is exactly what makes frequency and timing measurable. Returns the monad
    (or None if `action` was empty)."""
    action = (action or "").strip()
    if not action:
        return None
    ts = int(ts if ts is not None else time.time() * 1000)
    hour, dow = _bucket(ts)
    md = {"kind": "usage", "action": action, "target": (target or "").strip(),
          "app": (app or "").strip(), "hour": hour, "dow": dow}
    if meta:
        for k, v in meta.items():
            md.setdefault(k, v)
    summary = action + (f" {target}" if target else "") + (f" [{app}]" if app else "")
    m = aci.monadise(summary, source_type=USAGE_SOURCE, metadata=md,
                     truth_value=1.0, summary=summary, dedup=False)
    global _since_prune                          # keep behavioral memory self-bounding
    _since_prune += 1
    if _since_prune >= _PRUNE_EVERY:
        _since_prune = 0
        try:
            prune_usage(aci)
        except Exception:
            pass
    return m


def _events(aci, limit: int = _MAX_EVENTS) -> List:
    return list(aci.list_monads(limit, source_type=USAGE_SOURCE))


def _key(m) -> str:
    md = m.metadata or {}
    a = md.get("action", "")
    t = md.get("target", "")
    return (a + " " + t).strip() if t else a


def patterns(aci, min_count: int = 3, limit: int = _MAX_EVENTS) -> List[dict]:
    """Mine recurring behaviour. Returns actions seen >= min_count, each with how often it
    occurred, the hours it clusters in, the weekdays it clusters on, and the action that
    most often FOLLOWS it — ranked by frequency. Descriptive only; proactive.py decides
    what (if anything) to do with each pattern."""
    evs = _events(aci, limit)
    evs.sort(key=lambda m: m.timestamp)          # chronological → 'what follows what' is valid
    keys = [_key(m) for m in evs]
    counts: Counter = Counter()
    hours: Dict[str, Counter] = defaultdict(Counter)
    dows: Dict[str, Counter] = defaultdict(Counter)
    nxt: Dict[str, Counter] = defaultdict(Counter)
    for i, m in enumerate(evs):
        k = keys[i]
        if not k:
            continue
        md = m.metadata or {}
        counts[k] += 1
        hours[k][md.get("hour")] += 1
        dows[k][md.get("dow")] += 1
        if i + 1 < len(keys) and keys[i + 1] and keys[i + 1] != k:
            nxt[k][keys[i + 1]] += 1
    out: List[dict] = []
    for k, c in counts.most_common():
        if c < min_count:
            continue
        follows = nxt[k].most_common(1)
        out.append({
            "action": k, "count": c,
            "peak_hours": [h for h, _ in hours[k].most_common(3) if h is not None],
            "peak_dows": [d for d, _ in dows[k].most_common(3) if d is not None],
            "next": follows[0][0] if follows else None,
            "next_count": follows[0][1] if follows else 0,
        })
    return out


def prune_usage(aci, keep: int = _MAX_EVENTS) -> int:
    """Cap behavioral memory to the most recent `keep` events; forget the oldest surplus.
    Behavioral memory must never grow without bound or compete with the knowledge store."""
    evs = _events(aci, keep * 3 + 200)
    if len(evs) <= keep:
        return 0
    evs.sort(key=lambda m: m.timestamp)          # oldest first
    dropped = 0
    for m in evs[:len(evs) - keep]:
        try:
            if aci.forget(m.id):
                dropped += 1
        except Exception:
            pass
    return dropped
