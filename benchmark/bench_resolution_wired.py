"""
bench_resolution_wired.py — PHASE 1 WIRING TEST: does the resolution dynamic behave
correctly on REAL ACI monads (not the scalar abstraction)?

Exercises ACI(resolve_contradictions=True) on an in-memory store with real
truth_value / entropy / supersession / recall. Confirms:
  W1 truth vs lie + corroboration -> truth wins, lie marked superseded, recall = truth
  W2 entrenched truth vs weak repeated lie -> truth survives (noise resistance)
  W3 equal-trust competing claims -> standoff: BOTH stay live (no fake winner)
  W4 control: SAME as W1 but flag OFF -> both stay live (old behavior; flag truly gates)

NEVER touches a production DB — db_path=':memory:' only.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/bench_resolution_wired.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                       # noqa: E402
from aci.embeddings import get_default        # noqa: E402

EMB = get_default()


def fresh(resolve):
    return ACI(db_path=":memory:", observer_id="w", embedder=EMB,
               resolve_contradictions=resolve)


def fact(a, subj, pred, obj, text, psi, source="KNOWLEDGE"):
    # Soft resolution targets CROSS-source competing claims (the ones the hard _supersede
    # leaves alive). Same-source corrections keep last-write-wins (existing behavior),
    # so these tests use distinct source_types to isolate the Phase-1 dynamic.
    a.monadise(text, source_type=source,
               metadata={"subject": subj, "predicate": pred, "object": obj}, truth_value=psi)


def status(a, subj, pred, obj):
    """Return (truth_value, superseded?) for the matching monad."""
    for m in a.store.all():
        if (m.metadata.get("subject") == subj and m.metadata.get("predicate") == pred
                and (m.metadata.get("object") or "").lower() == obj.lower()):
            return m.truth_value, m.metadata.get("status") == "superseded"
    return None, None


def recall_top(a, q):
    h = a.recall(q, k=3)
    return h[0].monad.value.lower() if h else ""


print("=" * 84)
print(" PHASE 1 WIRING TEST — resolution dynamics on REAL ACI monads (in-memory)")
print("=" * 84)
results = []

# W1: truth (high) vs lie (low), cross-source, then corroborate the truth a few times.
a = fresh(True)
fact(a, "zorland", "capital", "Mirex", "The capital of Zorland is Mirex", 4.0, "KNOWLEDGE")
fact(a, "zorland", "capital", "Drav", "The capital of Zorland is Drav", 1.0, "WEB")
for _ in range(4):
    fact(a, "zorland", "capital", "Mirex", "The capital of Zorland is Mirex", 4.0, "KNOWLEDGE")  # corroborate
t_mirex, sup_mirex = status(a, "zorland", "capital", "Mirex")
t_drav, sup_drav = status(a, "zorland", "capital", "Drav")
top = recall_top(a, "what is the capital of Zorland")
ok1 = (t_mirex > t_drav) and sup_drav and (not sup_mirex) and ("mirex" in top)
results.append(ok1)
print(f"\n  W1 truth vs lie + corroboration")
print(f"     Mirex psi={t_mirex:.2f} superseded={sup_mirex} | Drav psi={t_drav:.2f} superseded={sup_drav}")
print(f"     recall -> '{top[:40]}'   ->  {'PASS' if ok1 else 'FAIL'}")

# W2: entrenched truth (corroborated 6x) vs 3 weak low-trust lies.
a = fresh(True)
for _ in range(6):
    fact(a, "reactor", "state", "online", "The reactor is online", 3.5, "KNOWLEDGE")
for _ in range(3):
    fact(a, "reactor", "state", "offline", "The reactor is offline", 0.6, "WEB")
t_on, sup_on = status(a, "reactor", "state", "online")
t_off, sup_off = status(a, "reactor", "state", "offline")
ok2 = (t_on > t_off) and (not sup_on) and ("online" in recall_top(a, "what is the reactor state"))
results.append(ok2)
print(f"\n  W2 entrenched truth vs weak repeated lies (noise resistance)")
print(f"     online psi={t_on:.2f} superseded={sup_on} | offline psi={t_off:.2f} superseded={sup_off}")
print(f"     ->  {'PASS' if ok2 else 'FAIL'}")

# W3: equal-trust competing claims -> genuine standoff, both stay live.
a = fresh(True)
fact(a, "door", "state", "open", "The door is open", 2.0, "KNOWLEDGE")
fact(a, "door", "state", "closed", "The door is closed", 2.0, "WEB")
t_o, sup_o = status(a, "door", "state", "open")
t_c, sup_c = status(a, "door", "state", "closed")
ok3 = (not sup_o) and (not sup_c)        # neither forced out
results.append(ok3)
print(f"\n  W3 equal-trust standoff (hold both, no fake winner)")
print(f"     open psi={t_o:.2f} superseded={sup_o} | closed psi={t_c:.2f} superseded={sup_c}")
print(f"     ->  {'PASS' if ok3 else 'FAIL'}")

# W4: control — SAME as W1 but flag OFF. Old behavior: cross-source claims both live.
a = fresh(False)
fact(a, "zorland", "capital", "Mirex", "The capital of Zorland is Mirex", 4.0, "KNOWLEDGE")
fact(a, "zorland", "capital", "Drav", "The capital of Zorland is Drav", 1.0, "WEB")
for _ in range(4):
    fact(a, "zorland", "capital", "Mirex", "The capital of Zorland is Mirex", 4.0, "KNOWLEDGE")
_, sup_drav_off = status(a, "zorland", "capital", "Drav")
ok4 = (sup_drav_off is False)            # nothing superseded -> flag truly gates the dynamic
results.append(ok4)
print(f"\n  W4 control: flag OFF -> resolution must NOT run")
print(f"     Drav superseded={sup_drav_off} (expected False)   ->  {'PASS' if ok4 else 'FAIL'}")

print("\n" + "=" * 84)
print(f"  WIRING RESULT: {sum(results)}/{len(results)} passed.")
print("  GROUNDED ON REAL MONADS." if all(results) else "  NEEDS DIAGNOSIS.")
print("=" * 84)
