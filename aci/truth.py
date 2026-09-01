"""
Multi-valued / paraconsistent truth + contradiction detection.

Ported from aios_app uqrt/MultiValuedTruth.kt. Truth is not binary; we measure
consistency, coherence, interference, and detect contradictions via the XOR gate
(|psi1 - psi2|) plus subject overlap.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .monad import Monad
from .embeddings import cosine
from . import logic_gates as gates


@dataclass
class MultiValuedTruth:
    consistency: float
    coherence: float
    interference: float
    paraconsistency: float
    reasoning: str

    @property
    def is_valid(self) -> bool:
        return self.consistency > 0.5 and self.coherence > 0.4

    def qualitative(self) -> str:
        if self.consistency > 0.8 and self.coherence > 0.8:
            return "HIGHLY_CONSISTENT"
        if self.consistency > 0.6 and self.coherence > 0.6:
            return "MODERATELY_CONSISTENT"
        if self.interference > 0.7:
            return "HIGH_INTERFERENCE"
        return "TRANSITIONAL"


def _subject(m: Monad) -> Optional[str]:
    """A monad's 'subject' for fact-level contradiction (subject+predicate key)."""
    subj = m.metadata.get("subject")
    pred = m.metadata.get("predicate")
    if subj and pred:
        return f"{subj.strip().lower()}::{pred.strip().lower()}"
    if subj:
        return subj.strip().lower()
    return None


def detect_contradiction(a: Monad, b: Monad,
                         subject_overlap_threshold: float = 0.35) -> Optional[dict]:
    """Return contradiction info if a and b talk about the same subject but assert
    different things; else None."""
    # 1) Fact-level: same subject::predicate, different value
    sa, sb = _subject(a), _subject(b)
    if sa and sb and sa == sb:
        va = (a.metadata.get("object") or a.value or a.summary).strip().lower()
        vb = (b.metadata.get("object") or b.value or b.summary).strip().lower()
        if va and vb and va != vb:
            return {
                "type": "fact",
                "subject": sa,
                "value_a": va, "value_b": vb,
                "interference": 1.0,
                "explanation": f"Same subject '{sa}' asserts conflicting values: "
                               f"'{va}' vs '{vb}'.",
            }
        return None

    # 2) Semantic-level: high topical overlap + divergent truth (XOR)
    overlap = cosine(a.embedding, b.embedding) if a.embedding and b.embedding else 0.0
    kw_overlap = len(set(a.keywords) & set(b.keywords)) / max(
        1, len(set(a.keywords) | set(b.keywords)))
    topical = max(overlap, kw_overlap)
    if topical >= subject_overlap_threshold:
        xor = gates.XOR(a.truth_value, b.truth_value)
        ta = (a.value or a.summary or "").lower()
        tb = (b.value or b.summary or "").lower()
        neg_flip = _has_negation(ta) != _has_negation(tb)     # not/no/never/nothing/...
        antonym = _opposing_concepts(ta, tb)                  # cloud vs local, public vs private, ...
        if (neg_flip or antonym) and topical >= 0.5:
            return {
                "type": "semantic",
                "topical_overlap": round(topical, 3),
                "xor": round(xor, 3),
                "interference": min(1.0, topical),
                "polarity": "negation" if neg_flip else "antonym",
                "explanation": "Topically related statements with opposing polarity "
                               f"(overlap={topical:.2f}, via "
                               f"{'negation' if neg_flip else 'opposing concepts'}).",
            }
    return None


_NEG = ("not", "no", "never", "false", "nothing", "none", "without",
        "cannot", "can't", "won't", "isn't", "aren't", "doesn't", "don't")

# Opposing concept groups: a statement leaning to one side contradicts one leaning
# to the other (only when each side has its concept and NOT the other's). Curated +
# extensible; whole-word matched. Honest scope: heuristic - real semantic
# contradiction (paraphrase/antonym at large) needs an NLI model or an LLM judge.
_OPP = [
    ({"cloud", "online", "remote", "server", "hosted"},
     {"local", "offline", "on-device", "ondevice", "locally", "device"}),
    ({"public"}, {"private"}),
    ({"enabled", "active"}, {"disabled", "inactive"}),
    ({"increase", "increased", "higher", "more", "raise", "raised"},
     {"decrease", "decreased", "lower", "lowered", "less", "reduce", "reduced"}),
    ({"allowed", "allow", "permitted", "permit"},
     {"blocked", "denied", "deny", "forbidden", "prohibited"}),
    ({"true", "yes", "correct"}, {"wrong", "incorrect"}),
    ({"open", "opened"}, {"closed", "shut"}),
]


def _words(text: str):
    import re
    return set(re.findall(r"[a-z][a-z-]*", text))


def _has_negation(text: str) -> bool:
    return bool(_words(text) & set(_NEG))


def _opposing_concepts(ta: str, tb: str) -> bool:
    wa, wb = _words(ta), _words(tb)
    for side_a, side_b in _OPP:
        a_in_A, a_in_B = bool(wa & side_a), bool(wa & side_b)
        b_in_A, b_in_B = bool(wb & side_a), bool(wb & side_b)
        # a leans one side (and not the other) while b leans the opposite
        if (a_in_A and not a_in_B and b_in_B and not b_in_A) or \
           (a_in_B and not a_in_A and b_in_A and not b_in_B):
            return True
    return False


def evaluate(monad: Monad, related: List[Monad]) -> MultiValuedTruth:
    """Coherence of a monad against related evidence."""
    if not related:
        return MultiValuedTruth(
            consistency=monad.normalized_truth(),
            coherence=1.0 - min(monad.entropy, 1.0),
            interference=0.0,
            paraconsistency=monad.normalized_truth(),
            reasoning="No related evidence; standalone assessment.",
        )
    contradictions = [c for r in related if (c := detect_contradiction(monad, r))]
    interference = max([c["interference"] for c in contradictions], default=0.0)
    sims = [cosine(monad.embedding, r.embedding) for r in related if r.embedding]
    coherence = (sum(sims) / len(sims)) if sims else 0.5
    consistency = max(0.0, monad.normalized_truth() - 0.5 * interference)
    para = max(0.0, min(1.0, consistency * 0.5 + coherence * 0.3 - interference * 0.2 + 0.2))
    reason = ("Consistent with evidence." if interference == 0
              else f"{len(contradictions)} contradiction(s) detected.")
    return MultiValuedTruth(consistency, coherence, interference, para, reason)
