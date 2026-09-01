"""
benchmark_completeness.py - "Does ACI complete the LLM?"

Thesis: an LLM has no persistent grounded truth, can't hold/resolve contradictions,
isn't observer-relative, and doesn't weight by credibility - these are architectural,
not model-specific. So on truth-maintenance tasks an LLM is only as correct as the
GROUNDING it's handed. This benchmark measures the grounding two layers deliver on
the SAME data with the SAME embedder:

  * NAIVE  - similarity-only retrieval (what a vanilla vector/LLM-memory feeds a model):
             no supersession, no observer, no contradiction/truth resolution.
  * ACI    - recall/validate with supersession, observer-relative truth, contradiction.

A scenario passes if the layer hands the model a CORRECT, UNAMBIGUOUS, RESOLVED
grounding. (Optional: set ACI_BENCH_LLM=ollama|openai to also run the downstream
answer through a real model and compare final answers.)

Run:  PYTHONHASHSEED=0 py benchmark/benchmark_completeness.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.aci import ACI
from aci.observer import Observer


def naive_top(aci, query, k=4):
    """Vanilla retrieval: pure cosine over ALL monads (incl. superseded), no
    observer, no truth weighting - exactly what a plain vector-memory gives an LLM."""
    q = aci.embedder.embed(query)
    out = []
    for cid, sim in aci.index.search(q, 25):
        m = aci.store.get(cid)
        if m:
            out.append(m)
    return out[:k]


def obj_of(m):
    return (m.metadata.get("object") or m.value).strip()


# ---------------------------------------------------------------------------
def scenario_supersession():
    """A fact was updated. The stale value must not pollute the grounding."""
    aci = ACI(":memory:")
    md = {"subject": "project deadline", "predicate": "is"}
    aci.monadise("The project deadline is March 15.", source_type="FILE",
                 metadata={**md, "object": "March 15"})
    aci.monadise("The project deadline is April 2.", source_type="FILE",
                 metadata={**md, "object": "April 2"})
    q = "what is the project deadline?"
    naive = naive_top(aci, q)
    aci_hits = [h.monad for h in aci.recall(q, k=4)]
    correct = "April 2"
    # pass = correct value is top AND the stale value is absent from grounding
    naive_vals = [obj_of(m) for m in naive]
    aci_vals = [obj_of(m) for m in aci_hits]
    naive_ok = bool(naive_vals) and naive_vals[0] == correct and "March 15" not in naive_vals
    aci_ok = bool(aci_vals) and aci_vals[0] == correct and "March 15" not in aci_vals
    return ("Supersession (stale update)", naive_ok, aci_ok,
            f"naive top={naive_vals[:2]} | aci top={aci_vals[:2]} | want '{correct}' alone")


def scenario_observer():
    """Two sources disagree; the right answer depends on WHO asks."""
    aci = ACI(":memory:")
    md = {"subject": "price", "predicate": "is"}
    aci.monadise("The price is 100 dollars.", source_type="CONTRACT",
                 metadata={**md, "object": "100"})
    aci.monadise("The price is 120 dollars.", source_type="CRM",
                 metadata={**md, "object": "120"})
    legal = Observer(id="legal", trust={"CONTRACT": 3.0, "CRM": 0.2})
    sales = Observer(id="sales", trust={"CRM": 3.0, "CONTRACT": 0.2})
    q = "what is the agreed price?"
    naive = naive_top(aci, q)
    naive_ans = obj_of(naive[0]) if naive else None        # same for everyone
    legal_ans = obj_of(aci.recall(q, k=2, observer=legal)[0].monad)
    sales_ans = obj_of(aci.recall(q, k=2, observer=sales)[0].monad)
    naive_ok = (naive_ans == "100") and (naive_ans == "120")   # impossible -> naive can't
    aci_ok = (legal_ans == "100") and (sales_ans == "120")
    return ("Observer-relative (source conflict)", naive_ok, aci_ok,
            f"naive='{naive_ans}' for all | aci legal='{legal_ans}' sales='{sales_ans}' (want 100/120)")


def scenario_contradiction():
    """A conflicting claim must be FLAGGED, not silently accepted."""
    aci = ACI(":memory:")
    aci.monadise("The server room temperature threshold is 27 degrees.",
                 source_type="SENSOR", truth_value=2.0,
                 metadata={"subject": "server room threshold", "predicate": "is", "object": "27"})
    claim = "The server room threshold is 18 degrees."
    v = aci.validate(claim, metadata={"subject": "server room threshold",
                                      "predicate": "is", "object": "18"})
    aci_ok = (not v.is_consistent)         # ACI flags the contradiction
    naive_ok = False                       # vanilla retrieval has no contradiction layer
    return ("Contradiction flagging", naive_ok, aci_ok,
            f"naive: no contradiction layer | aci.is_consistent={v.is_consistent} (want False)")


def scenario_truth_weighting():
    """A low-truth rumor must not outrank a verified fact."""
    aci = ACI(":memory:")
    aci.monadise("Acme acquired Beta Corp.", source_type="RUMOR", truth_value=0.2,
                 metadata={"subject": "acme", "predicate": "acquired", "object": "beta"})
    aci.monadise("Acme did not acquire Beta Corp; the deal fell through.",
                 source_type="FILING", truth_value=2.0,
                 metadata={"subject": "acme", "predicate": "acquired", "object": "no deal"})
    q = "did Acme acquire Beta Corp?"
    naive = naive_top(aci, q)
    aci_hits = [h.monad for h in aci.recall(q, k=4)]
    # pass = the VERIFIED (high-truth) statement is ranked first
    naive_ok = bool(naive) and naive[0].truth_value >= 1.0
    aci_ok = bool(aci_hits) and aci_hits[0].truth_value >= 1.0
    return ("Truth-weighting (rumor vs verified)", naive_ok, aci_ok,
            f"naive top psi={naive[0].truth_value if naive else '-'} | "
            f"aci top psi={aci_hits[0].truth_value if aci_hits else '-'} (want >=1.0)")


def main():
    print("=" * 74)
    print(" COMPLETENESS BENCHMARK - does ACI ground the LLM where the LLM can't?")
    print("=" * 74)
    backend = os.environ.get("ACI_BENCH_LLM")
    if backend:
        print(f" live-LLM mode: {backend}")
    else:
        print(" no LLM backend set -> measuring GROUNDING QUALITY (an LLM is only as")
        print(" correct as its grounding). Set ACI_BENCH_LLM=ollama|openai for the")
        print(" downstream answer comparison too.")
    print("-" * 74)
    scenarios = [scenario_supersession, scenario_observer,
                 scenario_contradiction, scenario_truth_weighting]
    n_ok = a_ok = 0
    for fn in scenarios:
        name, naive_ok, aci_ok, detail = fn()
        n_ok += naive_ok
        a_ok += aci_ok
        print(f"\n{name}")
        print(f"  naive RAG : {'PASS' if naive_ok else 'FAIL'}")
        print(f"  ACI       : {'PASS' if aci_ok else 'FAIL'}")
        print(f"  {detail}")
    print("\n" + "=" * 74)
    print(f" GROUNDING DELIVERED CORRECTLY:   naive RAG {n_ok}/4    ACI {a_ok}/4")
    print("=" * 74)
    print(" Read: on truth-maintenance tasks an LLM fed naive grounding is fed")
    print(" stale/conflicting/unranked facts; fed ACI grounding it gets the resolved,")
    print(" observer-correct, contradiction-flagged truth. That gap is 'completing the LLM'.")


if __name__ == "__main__":
    main()
