"""
sim_6d_time.py — test the dormant 6D-time structure (temporal_past/present/future +
spacetime coords). Two questions:

  Q1  Do the 6D fields currently carry ANY signal? (or are they uniform/zero?)
  Q2  If we POPULATE the temporal weights by tense, does tense-aware recall beat
      plain similarity on tense-oriented queries ("what happened" vs "what's upcoming")?
      i.e. does the past/present/future axis add something valid_from cannot?

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/sim_6d_time.py
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                                    # noqa: E402
from aci.embeddings import get_default                     # noqa: E402

EMB = get_default()
a = ACI(db_path=":memory:", observer_id="t", embedder=EMB)

# same topic, three tenses — similarity alone CANNOT tell them apart
corpus = [
    "The Helios launch was delayed last year due to a fuel fault.",          # past
    "The Helios launch is currently proceeding on schedule.",               # present
    "The Helios launch is planned for next spring with a new rocket.",       # future
    "The reactor inspection was completed in 2023.",                        # past
    "The reactor is operating normally right now.",                        # present
    "The reactor maintenance is scheduled for next month.",                 # future
]
for text in corpus:
    a.monadise(text, source_type="KNOWLEDGE")

print("=" * 78)
print(" 6D-TIME TEST")
print("=" * 78)

# Q1 — current state of the 6D fields
print("\nQ1  Do the 6D fields carry any signal as stored?")
ms = a.store.all()
tw = set((round(m.temporal_past, 2), round(m.temporal_present, 2), round(m.temporal_future, 2)) for m in ms)
sc = set(tuple(m.spacetime) for m in ms)
print(f"    distinct temporal-weight triples across {len(ms)} monads: {tw}")
print(f"    distinct spacetime vectors: {sc}")
print("    -> if there's only ONE triple/vector, the 6D fields are UNIFORM = zero information.")

# Q2 — populate temporal weights by tense, test tense-aware recall
PAST = ("was", "were", "had", "failed", "delayed", "completed", "ago", "last", "previously", "ended")
FUT = ("will", "planned", "scheduled", "upcoming", "next", "soon", "future", "going to")

def tense_of(text):
    t = text.lower()
    if any(w in re.findall(r"[a-z]+", t) for w in FUT) or "next " in t:
        return "future"
    if any(w in re.findall(r"[a-z]+", t) for w in PAST):
        return "past"
    return "present"

# attach tense weights (the POPULATION step the product doesn't do today)
weights = {}
for m in ms:
    weights[m.id] = tense_of(m.value)

def query_tense(q):
    ql = q.lower()
    if any(w in ql for w in ("upcoming", "plan", "next", "future", "will", "going to")):
        return "future"
    if any(w in ql for w in ("happened", "was", "past", "last", "delayed", "history")):
        return "past"
    return "present"

def topk(q, tense_aware):
    want = query_tense(q)
    hits = a.recall(q, k=6)
    scored = []
    for h in hits:
        s = h.score
        if tense_aware and weights.get(h.monad.id) == want:
            s += 0.3
        scored.append((s, weights.get(h.monad.id), h.monad.value))
    scored.sort(key=lambda x: -x[0])
    return scored[0], want

queries = [
    "what is the upcoming plan for the Helios launch",   # future
    "what happened to the Helios launch",                # past
    "what is the current status of the reactor",         # present
    "what maintenance is coming up for the reactor",     # future
]
print("\nQ2  tense-aware recall vs plain similarity:")
base_ok, cand_ok = 0, 0
for q in queries:
    b, want = topk(q, False)
    c, _ = topk(q, True)
    base_ok += (b[1] == want)
    cand_ok += (c[1] == want)
    print(f"    {q[:46]:46} want={want:7} base_top={str(b[1]):7} cand_top={c[1]}")
print(f"\n    correct-tense top-1: baseline={base_ok}/{len(queries)}  tense-aware={cand_ok}/{len(queries)}")

print("\n" + "-" * 78)
print("  VIEW: (a) if Q1 shows uniform fields -> 6D time carries ZERO info as-is.")
print("        (b) Q2 shows whether the past/present/future axis (a DIFFERENT signal")
print("            from valid_from) would help IF populated. Spatial coords are not")
print("            tested — they're meaningless for a document/memory store.")
print("-" * 78)
