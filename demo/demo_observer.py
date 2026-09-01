"""
Phase-2 demo: OBSERVER-RELATIVE REASONING (the differentiator).

ONE shared knowledge base. TWO observers. Different, contextually-correct answers
- because truth is observer-relative (ψ × the observer's trust in the source),
over only what each observer can see. No vanilla vector-DB / RAG does this.

Run:  py demo/demo_observer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci import ACI, Observer  # noqa: E402


def line(t=""):
    print("\n" + "=" * 70)
    if t:
        print(t)
        print("=" * 70)


def main():
    aci = ACI(db_path=":memory:")

    line("SCENARIO A - trust frame: same fact base, conflicting sources")
    # Two competing claims about the same fact, from different sources. They are
    # NOT superseded (different source) - both persist as competing claims.
    aci.monadise("Acme deal price is 12000 dollars.", source_type="CRM", observer_id="global",
                 metadata={"subject": "acme deal", "predicate": "price", "object": "12000 dollars"},
                 truth_value=2.0)
    aci.monadise("Acme deal price is 9500 dollars.", source_type="CONTRACT", observer_id="global",
                 metadata={"subject": "acme deal", "predicate": "price", "object": "9500 dollars"},
                 truth_value=2.0)

    legal = Observer(id="legal", trust={"CONTRACT": 3.0, "CRM": 0.3})   # trusts signed contracts
    sales = Observer(id="sales", trust={"CRM": 3.0, "CONTRACT": 0.3})   # trusts the CRM

    q = "what is the acme deal price"
    print(f"  Q (both ask the same): '{q}'")
    print(f"    LEGAL  observer -> {aci.recall(q, k=1, observer=legal)[0].monad.value}")
    print(f"    SALES  observer -> {aci.recall(q, k=1, observer=sales)[0].monad.value}")
    print("    (same KB, opposite answers - resolved by each observer's trust frame)")

    line("SCENARIO B - visibility: private belief vs shared knowledge")
    aci.monadise("The Earth is round.", source_type="SCIENCE", observer_id="global",
                 metadata={"subject": "earth", "predicate": "shape", "object": "round"},
                 truth_value=3.0)
    aci.monadise("The Earth is flat.", source_type="BELIEF", observer_id="alice",
                 metadata={"subject": "earth", "predicate": "shape", "object": "flat"},
                 truth_value=2.0)

    # Alice sees her private belief + global, and trusts her own belief most.
    alice = Observer(id="alice", visible={"alice", "global"},
                     trust={"BELIEF": 3.0, "SCIENCE": 0.5})
    # The public can only see shared/global knowledge (not Alice's private monad).
    public = Observer(id="public", visible={"global"})

    q2 = "what is the shape of the earth"
    print(f"  Q: '{q2}'")
    print(f"    ALICE  (private view) -> {aci.recall(q2, k=1, observer=alice)[0].monad.value}")
    print(f"    PUBLIC (shared view)  -> {aci.recall(q2, k=1, observer=public)[0].monad.value}")
    print("    (Alice keeps her belief privately; the public sees only shared truth)")

    aci.close()
    line("Observer-relative reasoning: one substrate, many contextual truths.")


if __name__ == "__main__":
    main()
