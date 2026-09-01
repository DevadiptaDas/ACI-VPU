"""
sim_monad_mesh.py — SIMULATION of the federated monad mesh.

Spins up 3 independent ACI nodes (separate in-memory stores, shared embedder so
vectors are comparable) and a minimal federation layer, then tests the mesh's
COGNITIVE behaviour:

  T1 federated recall   — a query on the mesh reaches knowledge held on OTHER nodes
  T2 selective sharing  — monads marked private never leave their node
  T3 conflict resolution— merging conflicting facts, higher-truth wins (validate/supersede)
  T4 offline / partition— a peer being down degrades gracefully (no crash, partial answer)
  T5 dedup on merge     — the same fact on two nodes appears once
  T6 latency model       — illustrative cost of fan-out

This validates the LOGIC of the mesh (federation, merge, conflict, privacy, offline).
It does NOT test real networking (NAT, internet latency, true partitions),
security under malicious nodes, sybil resistance, or behaviour at large scale —
those need real multi-node deployment.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/sim_monad_mesh.py
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                                    # noqa: E402
from aci.embeddings import get_default                     # noqa: E402

EMB = get_default()                                        # shared so cross-node vectors compare


def node(name):
    return ACI(db_path=":memory:", observer_id=name, embedder=EMB)


def store(n, text, shared=True, truth=1.0, subj=None, pred=None, obj=None):
    md = {"shared": shared}
    if subj:
        md.update(subject=subj, predicate=pred, object=obj)
    n.monadise(text, source_type="KNOWLEDGE", metadata=md, truth_value=truth)


# ---- the federation layer (the mesh) ----
class Down(Exception):
    pass


def federated_recall(query, nodes, k=5, exclude_private=True, down=()):
    """Query every reachable peer, collect SHARED monads, merge + dedup by content."""
    seen, merged, reached = set(), [], 0
    for n in nodes:
        if n.observer_id in down:
            continue                                       # peer unreachable -> skip
        try:
            hits = n.recall(query, k=k)
        except Exception:
            continue                                       # graceful degradation
        reached += 1
        for h in hits:
            m = h.monad
            if exclude_private and not m.metadata.get("shared", False):
                continue
            key = m.value.strip().lower()
            if key in seen:
                continue                                   # dedup across nodes
            seen.add(key)
            merged.append({"node": n.observer_id, "sim": round(h.similarity, 3),
                           "truth": m.truth_value, "text": m.value})
    merged.sort(key=lambda x: -x["sim"])
    return merged, reached


# ---- build the mesh ----
A, B, C = node("A"), node("B"), node("C")
store(A, "The Helios project deadline is in March 2026.", shared=True, truth=0.5,
      subj="Helios project", pred="deadline", obj="March 2026")
store(B, "Dr. Aanya Rao is the lead engineer on the Helios project.", shared=True)
store(C, "The Helios project budget is 4.2 million dollars.", shared=True)
store(C, "CONFIDENTIAL client identity: the Helios client is Northwind Corp.", shared=False)
# a conflicting, higher-trust deadline arrives on node B
store(B, "The Helios project deadline was moved to April 2026.", shared=True, truth=0.95,
      subj="Helios project", pred="deadline", obj="April 2026")
# duplicate of A's fact also exists on C (to test dedup)
store(C, "The Helios project deadline is in March 2026.", shared=True, truth=0.5)

MESH = [A, B, C]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


print("=" * 80)
print(" MONAD MESH SIMULATION — 3 nodes, federated layer")
print("=" * 80)

# T1 — federated recall reaches OTHER nodes' knowledge
print("\nT1  federated recall (mesh should surface leader+budget that node A lacks)")
solo, _ = federated_recall("tell me about the Helios project", [A])
mesh, reached = federated_recall("tell me about the Helios project", MESH)
mesh_blob = " ".join(r["text"].lower() for r in mesh)
has_leader = "aanya" in mesh_blob
has_budget = "budget" in mesh_blob
print(f"     solo(A) facts: {len(solo)}   mesh facts: {len(mesh)} across {reached} nodes")
check("T1 mesh reaches remote knowledge", has_leader and has_budget and len(mesh) > len(solo),
      f"leader={has_leader}, budget={has_budget}")

# T2 — selective sharing: the CONFIDENTIAL monad must never appear
print("\nT2  selective sharing (private 'Northwind Corp' must NOT leak)")
leak, _ = federated_recall("who is the Helios client", MESH)
leaked = any("northwind" in r["text"].lower() for r in leak)
check("T2 private monad does not leak", not leaked, f"leaked={leaked}")

# T3 — conflict resolution: merge into one view, higher-truth deadline wins
print("\nT3  conflict resolution (April@0.95 should beat March@0.5 after merge)")
M = node("M")
for n in (A, B, C):
    for m in n.store.all():
        if m.metadata.get("shared", False):
            M.monadise(m.value, source_type="KNOWLEDGE", metadata=dict(m.metadata),
                       truth_value=m.truth_value)
hits = M.recall("When is the Helios project deadline?", k=5)
top = hits[0].monad.value.lower() if hits else ""
v = M.validate("The Helios project deadline is in March 2026.", truth_value=0.5)
check("T3 higher-truth fact surfaces on top", "april" in top, f"top='{top[:50]}'")
check("T3 validate flags the stale low-truth claim", not v.is_consistent,
      f"consistent={v.is_consistent}")

# T4 — offline / partition: node B down, mesh still answers from A + C
print("\nT4  offline / partition (node B down -> partial but working)")
part, reached = federated_recall("tell me about the Helios project", MESH, down={"B"})
ok_partial = reached == 2 and len(part) > 0 and not any("aanya" in r["text"].lower() for r in part)
check("T4 degrades gracefully (no crash, partial answer)", ok_partial,
      f"reached={reached} nodes, facts={len(part)}")

# T5 — dedup on merge: A and C both hold the March-deadline fact -> appears once
print("\nT5  dedup on merge (March-deadline duplicated on A & C -> once)")
allr, _ = federated_recall("Helios project deadline", MESH)
march_count = sum(1 for r in allr if "march 2026" in r["text"].lower())
check("T5 duplicate fact merged to one", march_count == 1, f"march copies returned={march_count}")

# T6 — latency model (illustrative, not pass/fail)
print("\nT6  latency model (fan-out cost)")
t0 = time.time()
for _ in range(5):
    federated_recall("Helios project", MESH)
serial_ms = (time.time() - t0) / 5 * 1000
print(f"     serial fan-out over 3 nodes: ~{serial_ms:.0f} ms/query "
      f"(real mesh would PARALLELISE -> ~1 node's latency, not the sum)")

print("\n" + "-" * 80)
p = sum(results)
print(f"  RESULT: {p}/{len(results)} mesh-logic tests passed")
print("  NOTE: validates federation/merge/conflict/privacy/offline LOGIC only.")
print("  NOT tested (needs real deployment): NAT/internet transport, malicious")
print("  nodes, sybil resistance, behaviour at hundreds of nodes.")
print("=" * 80)
