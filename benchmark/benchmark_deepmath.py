"""
benchmark_deepmath.py - do the DEEP UQRT constructs give a measurable, USP-grade
benefit over what we already have? Two fair head-to-heads:

  TEST 1  3-time (past/present/future) temporal truth   vs  single-timestamp recency
  TEST 2  observer-warped meaning metric                vs  fixed cosine similarity

Honest goal: find out whether the deep ideas EARN their place, and - just as
important - whether the benefit is *unique to the deep math* or replicable by a
standard mechanism. Run:  PYTHONHASHSEED=0 py benchmark/benchmark_deepmath.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.aci import ACI
from aci.embeddings import cosine


def obj(m):
    return (m.metadata.get("object") or m.value).strip()


# ===========================================================================
# TEST 1 - temporal truth: the currently-valid fact != the most-recently-stored one
# ===========================================================================
def test_temporal():
    aci = ACI(":memory:")
    md = {"subject": "ceo of acme", "predicate": "is"}
    # added oldest -> newest; the NEWEST (Carol) is a FUTURE appointment
    aci.monadise("The CEO of Acme is Alice.", source_type="FILE",
                 metadata={**md, "object": "Alice", "valid_from": 2018, "valid_to": 2021})
    aci.monadise("The CEO of Acme is Bob.", source_type="FILE",
                 metadata={**md, "object": "Bob", "valid_from": 2021, "valid_to": 2024})
    aci.monadise("The CEO of Acme is Carol.", source_type="FILE",   # uniform phrasing
                 metadata={**md, "object": "Carol", "valid_from": 2024, "valid_to": 2099})
    now = 2023
    q = "who is the CEO of Acme?"

    # baseline: ACI default recall (storage-recency + supersession). Newest-stored wins.
    base_hits = aci.recall(q, k=1, include_superseded=True)
    base_ans = obj(base_hits[0].monad) if base_hits else None

    # treatment: pick the fact whose validity window contains `now` (the 3-time idea)
    valid = [m for m in aci.store.all()
             if m.metadata.get("valid_from", -1e9) <= now < m.metadata.get("valid_to", 1e9)
             and m.metadata.get("subject") == "ceo of acme"]
    temp_ans = obj(valid[0]) if valid else None

    correct = "Bob"
    return {
        "name": "Temporal truth (current != newest-stored)",
        "baseline": ("recency/supersession", base_ans, base_ans == correct),
        "treatment": ("temporal validity window", temp_ans, temp_ans == correct),
        "want": correct,
    }


# ===========================================================================
# TEST 2 - observer-warped meaning metric vs fixed cosine (sense disambiguation)
# ===========================================================================
def test_warped_metric():
    aci = ACI(":memory:")
    docs = {
        "Java-prog": "Java is a high-level programming language for building applications.",
        "Java-isle": "Java is an island in Indonesia famous for beaches and volcanoes.",
        "Py-prog": "Python is a popular programming language for data science.",
        "Bali-isle": "Bali is a tropical island near Java popular with tourists.",
    }
    emb = {k: aci.embedder.embed(v) for k, v in docs.items()}
    q = aci.embedder.embed("tell me about Java")

    # fixed cosine: ONE ranking for everyone
    fixed = sorted(docs, key=lambda k: -cosine(q, emb[k]))
    fixed_top = fixed[0]

    # observer-warped: blend the observer's context direction into the metric
    prog_ctx = aci.embedder.embed("software programming language code development")
    trav_ctx = aci.embedder.embed("travel island beach tourism vacation")
    lam = 1.0

    def warped_top(ctx):
        return sorted(docs, key=lambda k: -(cosine(q, emb[k]) + lam * cosine(ctx, emb[k])))[0]

    prog_top = warped_top(prog_ctx)
    trav_top = warped_top(trav_ctx)

    # programmer should get the programming sense; traveler the island sense
    fixed_ok = (fixed_top == "Java-prog") and (fixed_top == "Java-isle")  # impossible -> can't serve both
    warped_ok = (prog_top == "Java-prog") and (trav_top == "Java-isle")
    return {
        "name": "Observer-warped metric (sense disambiguation)",
        "baseline": ("fixed cosine", f"{fixed_top} for everyone", fixed_ok),
        "treatment": ("observer-warped", f"prog={prog_top}, travel={trav_top}", warped_ok),
        "want": "prog->Java-prog, travel->Java-isle",
    }


def main():
    print("=" * 74)
    print(" DEEP-MATH BENCHMARK - do 6D/temporal + warped-meaning-geometry earn it?")
    print("=" * 74)
    for t in (test_temporal(), test_warped_metric()):
        print(f"\n{t['name']}   (want: {t['want']})")
        bl, bv, bok = t["baseline"]
        tl, tv, tok = t["treatment"]
        print(f"  baseline  [{bl}] -> {bv}   {'PASS' if bok else 'FAIL'}")
        print(f"  treatment [{tl}] -> {tv}   {'PASS' if tok else 'FAIL'}")
    print("\n" + "=" * 74)


if __name__ == "__main__":
    main()
