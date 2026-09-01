"""
Phase-1 demo: ACI on RAW text, with ZERO manual tagging.

Everything here is plain sentences. ACI auto-extracts subject/predicate/object,
so supersession and contradiction work without any metadata. Run:
    py demo/demo_raw.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci import ACI  # noqa: E402


def line(t=""):
    print("\n" + "=" * 66)
    if t:
        print(t)
        print("=" * 66)


def main():
    aci = ACI(db_path=":memory:", observer_id="user")

    line("1. INGEST RAW SENTENCES  (no metadata, no tagging)")
    for s in ["The project deadline is March 15.",
              "My accountant is Sarah Chen.",
              "The server room temperature threshold is 27C."]:
        m = aci.monadise(s, truth_value=2.0)
        print(f"  '{s}'")
        print(f"     auto-extracted -> subject={m.metadata.get('subject')!r} "
              f"predicate={m.metadata.get('predicate')!r} object={m.metadata.get('object')!r}")

    line("2. RAW UPDATE  -> supersession with no tagging")
    aci.monadise("The project deadline is April 2.", truth_value=2.0)
    print("  ingested: 'The project deadline is April 2.'")
    print(f"  recall 'project deadline' -> {aci.recall('project deadline', k=1)[0].monad.value}")

    line("3. CONTRADICTION on raw text")
    v = aci.validate("The project deadline is July 1.")
    print("  incoming: 'The project deadline is July 1.'")
    print(f"  consistent={v.is_consistent}  confidence={v.confidence:.2f}")
    for c in v.contradictions:
        print(f"  - {c.get('explanation', c)}")

    line("4. RECALL by meaning")
    for q in ["accountant", "server room temperature"]:
        print(f"  Q: {q:26} -> {aci.recall(q, k=1)[0].monad.value}")

    aci.close()
    line("Raw-text cognition works with zero manual tagging.")


if __name__ == "__main__":
    main()
