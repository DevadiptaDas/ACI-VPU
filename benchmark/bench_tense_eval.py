"""
bench_tense_eval.py — gate for the 3D-time (tense-aware recall) feature.

Uses the REAL implementation: monadise now auto-populates temporal weights from
content tense, and recall(tense_aware=True/False) applies the tiebreaker. We A/B
tense-aware ON vs OFF on tense-oriented queries over a mixed-tense corpus.

Decision rule: keep the feature ON only if it beats the baseline on tense queries
AND (separately, via benchmark_eval) doesn't regress the main trust eval.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/bench_tense_eval.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                                    # noqa: E402
from aci.embeddings import get_default                     # noqa: E402

a = ACI(db_path=":memory:", observer_id="t", embedder=get_default())

# mixed-tense corpus (same topics across past / present / future)
corpus = [
    "The Helios launch was delayed last year due to a fuel fault.",        # past
    "The Helios launch is proceeding on schedule today.",                 # present
    "The Helios launch is planned for next spring.",                      # future
    "The reactor inspection was completed in 2023.",                      # past
    "The reactor is operating normally.",                                # present
    "The reactor maintenance is scheduled for next month.",               # future
    "The vendor contract was signed in January.",                        # past
    "The vendor contract is currently under review.",                    # present
    "The vendor contract renewal is due soon.",                          # future
]
for text in corpus:
    a.monadise(text, source_type="KNOWLEDGE")

# verify the weights are no longer uniform
triples = set((round(m.temporal_past, 2), round(m.temporal_present, 2),
               round(m.temporal_future, 2)) for m in a.store.all())
print("populated temporal triples (should be >1 distinct):", triples)

# (query, expected unique phrase in the correct answer)
QUERIES = [
    ("what happened with the Helios launch", "delayed last year"),
    ("what is the upcoming plan for the Helios launch", "next spring"),
    ("what is the current status of the reactor", "operating normally"),
    ("what is scheduled next for the reactor", "scheduled for next month"),
    ("what happened to the vendor contract", "signed in january"),
    ("what is the current status of the vendor contract", "under review"),
]


def top1(query, tense_aware):
    h = a.recall(query, k=4, tense_aware=tense_aware)
    return h[0].monad.value.lower() if h else ""


print("\n" + "=" * 80)
print(" TENSE EVAL — tense-aware recall vs baseline")
print("=" * 80)
base, cand = 0, 0
for q, expect in QUERIES:
    b = top1(q, False)
    c = top1(q, True)
    bok = expect in b
    cok = expect in c
    base += bok
    cand += cok
    print(f"  {q[:44]:44} want={expect[:22]:22} base={'Y' if bok else 'n'} tense={'Y' if cok else 'n'}")
print("-" * 80)
print(f"  correct@1:  baseline={base}/{len(QUERIES)}   tense-aware={cand}/{len(QUERIES)}")
if cand > base:
    print("  VERDICT: KEEP — tense-aware recall measurably beats baseline.")
elif cand == base:
    print("  VERDICT: NEUTRAL — no gain; reconsider (but check it doesn't hurt either).")
else:
    print("  VERDICT: REVERT — tense-aware HURTS.")
print("=" * 80)
