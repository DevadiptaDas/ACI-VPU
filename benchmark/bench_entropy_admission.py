"""
bench_entropy_admission.py — PHASE 6: does entropy-weighted admission stop a confident,
repeated lie from rotting an established truth?

Scenario: "the capital of Zorland is Mirex" is established (high truth, KNOWLEDGE). Then
a confident lie "the capital of Zorland is Drav" is injected repeatedly from a WEB source
(cross-source, so the existing hard supersede does NOT fire — the lie would otherwise just
accumulate). We compare the field WITH vs WITHOUT the admission gate.

  - WITHOUT gate: the lie enters at full truth and dedup reinforcement pumps it up over
    repeats -> it rivals/overtakes the truth (rot).
  - WITH gate: the lie contradicts established higher-truth, so it is admitted on probation
    (discounted truth, raised entropy) and its reinforcement is throttled -> it stays weak;
    recall keeps returning the truth.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/bench_entropy_admission.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                       # noqa: E402
from aci.embeddings import get_default        # noqa: E402

EMB = get_default()
TRUTH = "The capital of the Zorland federation is Mirex."
LIE = "The capital of the Zorland federation is Drav."
Q = "what is the capital of the Zorland federation"
LIE_REPEATS = 5


def run(gate: bool):
    a = ACI(db_path=":memory:", observer_id="p6", embedder=EMB, entropy_admission=gate)
    # establish the truth (high confidence, KNOWLEDGE)
    a.monadise(TRUTH, source_type="KNOWLEDGE",
               metadata={"subject": "zorland", "predicate": "capital", "object": "Mirex"},
               truth_value=4.0)
    # inject a confident lie repeatedly from a different source (cross-source: no hard supersede)
    for _ in range(LIE_REPEATS):
        a.monadise(LIE, source_type="WEB",
                   metadata={"subject": "zorland", "predicate": "capital", "object": "Drav"},
                   truth_value=4.0)

    def psi(obj):
        for m in a.store.all():
            if (m.metadata.get("object") or "").lower() == obj:
                return m.truth_value
        return None
    top = a.recall(Q, k=1)
    return psi("mirex"), psi("drav"), (top[0].monad.value if top else "")


print("=" * 84)
print(" PHASE 6 — ENTROPY-WEIGHTED ADMISSION (anti-rot: confident repeated lie vs truth)")
print("=" * 84)
print(f"\n  established TRUTH: '{TRUTH}'  (psi=4.0, KNOWLEDGE)")
print(f"  injected LIE x{LIE_REPEATS}: '{LIE}'  (psi=4.0 each, WEB)\n")

# the real rot signal is the truth-STATE: does the field end up believing the lie MORE
# than the truth (lie psi > truth psi)? recall on near-identical text is a noisier tiebreak.
for label, gate in (("WITHOUT gate", False), ("WITH gate", True)):
    mirex, drav, top = run(gate)
    believes_lie = drav > mirex
    print(f"  {label:13}: truth psi={mirex:.2f}  lie psi={drav:.2f}  | "
          f"field believes the lie more: {believes_lie}  {'<- ROT' if believes_lie else '<- coherent'}")

print("\n" + "-" * 84)
mirex_off, drav_off, _ = run(False)
mirex_on, drav_on, top_on = run(True)
ok = (drav_off > mirex_off) and (drav_on < mirex_on) and (drav_on < drav_off)
if ok:
    print(f"  VERDICT: GATE WORKS — ungated, the repeated lie OVERTAKES the truth (psi "
          f"{drav_off:.2f} > {mirex_off:.2f}) = rot.")
    print(f"  Gated, the lie is held on probation (psi {drav_on:.2f} < {mirex_on:.2f}) — the field's")
    print("  truth-state stays coherent no matter how often the lie is repeated.")
else:
    print("  VERDICT: NEEDS DIAGNOSIS — see psi above.")
print("=" * 84)
