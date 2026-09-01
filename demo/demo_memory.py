"""
ACI demo - the invisible cognition layer made visible.

Runs fully offline (stdlib only). Shows the four things the substrate does that
a plain AI/app cannot:
    1. Cross-session persistent memory
    2. Contradiction detection with an explainable trace
    3. Storage compression via monadisation + dedup
    4. Recall by meaning

Run:  py demo/demo_memory.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aci import ACI                      # noqa: E402
from adapters.llm_memory import LLMMemory  # noqa: E402


def line(title=""):
    print("\n" + "=" * 68)
    if title:
        print(title)
        print("=" * 68)


def main():
    aci = ACI(db_path=":memory:", observer_id="user-alok")
    assistant = LLMMemory(aci)

    line("1. PERSISTENT MEMORY  (facts learned across different 'sessions')")
    facts = [
        ("My accountant is Sarah Chen.", {"subject": "accountant", "predicate": "is", "object": "Sarah Chen"}),
        ("Project Apollo deadline is March 15.", {"subject": "project apollo", "predicate": "deadline", "object": "March 15"}),
        ("I prefer morning meetings.", {"subject": "meeting preference", "predicate": "is", "object": "morning"}),
        ("Our AWS bill last month was 42000 dollars.", {"subject": "aws bill", "predicate": "was", "object": "42000"}),
    ]
    for text, meta in facts:
        assistant.remember(text, **meta)
        print(f"  learned: {text}")

    line("2. RECALL BY MEANING  (months later, different wording)")
    for q in ["who handles my taxes?", "when is the apollo project due?", "how much do we spend on cloud?"]:
        hits = aci.recall(q, k=1)
        ans = hits[0].monad.summary if hits else "(nothing)"
        print(f"  Q: {q}\n     -> {ans}  (score={hits[0].score:.2f})")

    line("3. CONTRADICTION DETECTION  (new info conflicts with memory)")
    conflicting = "Project Apollo deadline is April 2."
    print(f"  incoming: {conflicting}")
    result = aci.validate(conflicting, metadata={
        "subject": "project apollo", "predicate": "deadline", "object": "April 2"})
    print()
    print("  " + result.explain().replace("\n", "\n  "))

    line("4. MEMORY-AUGMENTED CHAT  (LLM gets the recalled context)")
    out = assistant.chat("Remind me who my accountant is")
    print(f"  recalled: {out['recalled']}")
    print(f"  reply:    {out['reply']}")

    line("5. COMPRESSION / OPTIMIZATION  (the free payoff of monadising)")
    # ingest a large document several times to show compression + dedup
    big_doc = ("Quarterly report. " + ("Revenue grew steadily across all regions. " * 400))
    for _ in range(3):                    # same doc 3x -> dedup
        aci.monadise(big_doc, source_type="FILE",
                     summary="Q3 report: revenue grew across regions")
    stats = aci.compress()
    for kk, vv in stats.items():
        print(f"  {kk:20}: {vv}")

    aci.close()
    line("ACI demo complete - the layer was invisible; the effects were not.")


if __name__ == "__main__":
    main()
