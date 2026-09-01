"""
Skill Memory — a shared, self-curating SKILL library on top of ACI.

A skill is just a monad (source_type="SKILL"):
  • subject = the skill's NAME      -> its identity / supersession key
  • predicate = "skill"
  • object = a fingerprint of the body -> a CHANGED body is a new version
  • summary carries the intent       -> semantic recall finds it by goal
  • value (body) = the procedure / prompt / know-how

Everything else is existing ACI mechanics, so no new engine behaviour is invented:
  • shared across AIs   — one store, many agents (no new transport)
  • confidence is EARNED — reuse/success raises ψ, failure lowers it (skill_outcome)
  • better version wins  — a new body for the same NAME supersedes the old, but only
                           once it is at least as credible (ACI's credibility-gated
                           supersession) — a proven skill is not silently overwritten

SCOPE: DECLARATIVE skills only (know-how / procedures / prompts). EXECUTABLE skills
(code an agent runs) are deliberately NOT here — those need a consent + sandbox layer
and are deferred. Shared skills earn trust from OUTCOMES; they are never trusted on
assertion alone (same discipline as the extraction grounding gate).
"""
from __future__ import annotations
import hashlib
import time
from typing import List, Optional

SKILL_SOURCE = "SKILL"


def _fp(body: str) -> str:
    return hashlib.sha1((body or "").strip().encode("utf-8")).hexdigest()[:12]


def _view(m) -> dict:
    md = m.metadata or {}
    return {
        "id": m.id,
        "name": md.get("skill") or md.get("subject") or "",
        "intent": md.get("intent") or (m.summary or ""),
        "body": m.value,
        "confidence": round(float(m.truth_value), 3),   # ψ — earned, not asserted
        "uses": round(float(getattr(m, "weight", 1.0)), 1),
        "author": md.get("author") or m.observer_id,
        "tags": md.get("tags", ""),
    }


def save_skill(aci, name: str, intent: str, body: str, *,
               args: Optional[list] = None, tags: Optional[list] = None,
               author: Optional[str] = None, context: Optional[str] = None,
               truth_value: float = 1.0) -> dict:
    """Publish a skill into shared memory. Re-saving the SAME body corroborates it
    (ψ up); a CHANGED body for the same name is a new version that supersedes the old
    once it is at least as credible."""
    name = (name or "").strip()
    if not name or not (intent or "").strip() or not (body or "").strip():
        raise ValueError("save_skill requires non-empty name, intent and body")
    meta = {
        "kind": "skill",
        "skill": name,
        "subject": name.lower(),          # identity -> supersession key (subject::predicate)
        "predicate": "skill",
        "object": _fp(body),              # version fingerprint
        "intent": intent.strip(),
        "author": author or aci.observer_id,
    }
    if args:
        meta["args"] = ", ".join(str(a) for a in args) if isinstance(args, (list, tuple)) else str(args)
    if tags:
        meta["tags"] = ",".join(str(t) for t in tags) if isinstance(tags, (list, tuple)) else str(tags)
    m = aci.monadise(body, source_type=SKILL_SOURCE, metadata=meta,
                     truth_value=truth_value, summary=f"Skill[{name}]: {intent.strip()}",
                     observer_id=author, context=context)
    return _view(m)


def find_skills(aci, intent: str, k: int = 5, context: Optional[str] = None) -> List[dict]:
    """Discover skills by intent (semantic). Superseded versions are excluded by recall;
    results are ordered by ACI's score (similarity x truth x recency)."""
    hits = aci.recall(intent, k=max(k * 4, 12), context=context)
    out: List[dict] = []
    for h in hits:
        m = h.monad
        if m.source_type != SKILL_SOURCE:
            continue
        v = _view(m)
        v["score"] = round(float(getattr(h, "score", 0.0)), 4)
        out.append(v)
        if len(out) >= k:
            break
    return out


def skill_outcome(aci, skill_id: str, success: bool, weight: float = 1.0) -> Optional[dict]:
    """Record whether a skill actually WORKED. Success reinforces (ψ up, entropy down);
    failure decays (ψ down, entropy up). This outcome signal is what makes the library
    self-curating — the one feedback primitive ACI lacked (monadise only ever boosted)."""
    m = aci.store.get(skill_id)
    if m is None or m.source_type != SKILL_SOURCE:
        return None
    if success:
        m.truth_value = min(m.truth_value + 0.1 * weight, 50.0)
        m.entropy = max(m.entropy * 0.9, 0.0)
        m.weight = getattr(m, "weight", 1.0) + weight
    else:
        m.truth_value = max(m.truth_value * 0.6, 0.05)   # decay, never to zero
        m.entropy = m.entropy + 0.2 * weight
    m.timestamp = int(time.time() * 1000)
    aci.store.upsert(m)
    aci.field.add(m)
    return _view(m)
