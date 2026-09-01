"""
bench_field_primary_retrieval.py — PHASE 4: does meaning-field-PRIMARY retrieval
surface connected-but-lexically-different truth that similarity-primary misses?

The distinctive case is a HIDDEN MULTI-HOP bridge. Today's default recall gives a flat
bonus to 1-hop neighbours of the seeds. So we make the answer reachable only through an
intermediate that is itself NOT query-similar (not a seed): the answer B is 2 hops from
the only seed A, via a bridge C that the embedder ranks low. The default's 1-hop bonus
cannot reach B; field-primary's weighted 2-hop reach can.

  - similarity-primary = recall(field_primary=False)  (embedder + 1-hop bonus; today's default)
  - field-primary      = recall(field_primary=True)   (weighted 2-hop reach + truth lead)

Run:  py benchmark/bench_field_primary_retrieval.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from aci.aci import ACI                          # noqa: E402
from aci.embeddings import UqrtMcaEmbedder       # noqa: E402  (light, deterministic)

a = ACI(db_path=":memory:", observer_id="p4", embedder=UqrtMcaEmbedder())

# A: the ONLY query-similar seed.  C: a bridge that is NOT query-similar (won't be a seed).
# B: the ANSWER, 2 hops from A via C, sharing NO query word.
mA = a.monadise("The Zorland federation is a sovereign northern state.", source_type="KNOWLEDGE")
mC = a.monadise("Those ministries occupy one central administrative district.", source_type="KNOWLEDGE")
mB = a.monadise("Mirex is the principal city that houses those ministries.", source_type="KNOWLEDGE")

# distractors: a few SHARE query words (bury B on similarity); the rest are unrelated filler
# so the top-5 seed anchor stays a minority of the store.
DISTRACT = [
    "A federation is a political union of self-governing states.",
    "The northern state of Veld elects its assembly each year.",
    "The Zorland federation maintains a large standing army.",
    "The capital of the Eastland republic lies on the coast.",
    "Photosynthesis converts sunlight into chemical energy.",
    "Glaciers store most of the planet's fresh water.",
    "The bakery on the corner sells fresh sourdough bread.",
    "The orchestra tuned their instruments before the show.",
    "Honey can remain edible for thousands of years.",
    "Coral reefs host a quarter of all marine species.",
    "The comet returns to the inner system every decade.",
    "Solar panels perform best when facing true south.",
]
for d in DISTRACT:
    a.monadise(d, source_type="KNOWLEDGE")

Q = "what is the capital of the Zorland federation"      # shares words with A; none with B/C


def rank_B(fp, k=5):
    for i, h in enumerate(a.recall(Q, k=k, field_primary=fp), 1):
        if "Mirex" in h.monad.value:
            return i
    return None


print("=" * 88)
print(" PHASE 4 — MEANING-FIELD-PRIMARY RETRIEVAL  (hidden 2-hop bridge)")
print("=" * 88)
print(f"\n  query: '{Q}'")
print("  answer B ('Mirex...'): no query word, 2 hops from seed A via a non-seed bridge C.\n")

print("  (1) NO field edges yet:")
print(f"      similarity-primary  rank of answer: {rank_B(False)}")
print(f"      field-primary       rank of answer: {rank_B(True)}")

a.relate(mA.id, mC.id, "ASSOCIATIVE", 1.0)               # A -> C  (C is NOT a seed)
a.relate(mC.id, mB.id, "ASSOCIATIVE", 1.0)               # C -> B  (B is 2 hops from seed A)
rs, rf = rank_B(False), rank_B(True)
print("\n  (2) after linking the hidden bridge  A -> C -> B :")
print(f"      similarity-primary  rank of answer: {rs}   (1-hop bonus can't cross a non-seed bridge)")
print(f"      field-primary       rank of answer: {rf}   (weighted 2-hop reach)")

print("\n" + "-" * 88)
top3_field = rf is not None and rf <= 3
lifted = (rf is not None) and (rs is None or rf < rs)
ok = top3_field and lifted
if ok:
    print(f"  VERDICT: field-primary lifts the 2-hop answer to rank {rf} (similarity: {rs}) — it")
    print("  surfaces connected, lexically-different truth the embedder buries. The field leads;")
    print("  the embedder is a coarse sieve.")
else:
    print(f"  VERDICT: NEEDS DIAGNOSIS — field rank={rf}, similarity rank={rs}.")
print("=" * 88)
