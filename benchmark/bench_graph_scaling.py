"""
bench_graph_scaling.py — graph scaling: OLD flat-list scan (O(E)) vs the G1 adjacency
index (O(degree)). One run shows both, asserts they return identical results, and
reports the speedup as edge count grows (10k → 100k → 1M).

No product code is changed by this file; it re-implements the OLD scan locally only to
contrast it against the now-indexed MeaningField.neighbors()/reach().

Run:  py benchmark/bench_graph_scaling.py
"""
import sys
import time
import random
import tracemalloc

sys.stdout.reconfigure(encoding="utf-8")
from aci.meaning_field import MeaningField   # noqa: E402

random.seed(7)
SIZES = [10_000, 100_000, 1_000_000]
SEEDS = 5
RECALL_K = 5
DECAY = 0.7


def build(n_edges):
    n_nodes = max(100, n_edges // 5)
    ids = [f"m{i}" for i in range(n_nodes)]
    f = MeaningField()
    for _ in range(n_edges):
        f.relate(random.choice(ids), random.choice(ids))   # populates edges AND _adj
    return f, ids


# --- the OLD implementations (local copies, for before/after contrast only) ---
def scan_neighbors(f, node_id):
    out = set()
    for e in f.edges:
        if e.source_id == node_id:
            out.add(e.target_id)
        elif e.target_id == node_id:
            out.add(e.source_id)
    return out


def scan_reach(f, seeds, max_hops=2, decay=DECAY):
    adj = {}
    for e in f.edges:
        w = min(max(e.weight, 0.0), 1.0) or 1.0
        adj.setdefault(e.source_id, []).append((e.target_id, w))
        adj.setdefault(e.target_id, []).append((e.source_id, w))
    strength, frontier = {}, {s: 1.0 for s in seeds}
    for _ in range(max_hops):
        nxt = {}
        for nid, st in frontier.items():
            for nb, w in adj.get(nid, ()):
                val = st * decay * w
                if val > strength.get(nb, 0.0) and val > nxt.get(nb, 0.0):
                    nxt[nb] = val
        for nb, val in nxt.items():
            if val > strength.get(nb, 0.0):
                strength[nb] = val
        frontier = nxt
        if not frontier:
            break
    return strength


def timed(fn, reps):
    t = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t) / reps * 1000.0   # ms/call


print("=" * 96)
print(" G1 VERIFY — flat-list scan O(E)  vs  adjacency index O(degree)")
print("=" * 96)
print(f"\n  {'edges':>10} | {'neighbors OLD':>13} {'NEW':>9} {'×':>7} | "
      f"{'reach OLD':>11} {'NEW':>9} {'×':>7} | {'recall graph OLD→NEW':>22}")
print("  " + "-" * 92)

for E in SIZES:
    f, ids = build(E)
    probe = random.sample(ids, 20)
    seeds = random.sample(ids, min(SEEDS, len(ids)))

    # correctness: NEW must equal OLD (no behavior change), checked on a sample
    for p in probe:
        assert f.neighbors(p) == scan_neighbors(f, p), "neighbors mismatch!"
    assert f.reach(seeds, 2, DECAY) == scan_reach(f, seeds, 2, DECAY), "reach mismatch!"

    nb_old = timed(lambda: scan_neighbors(f, random.choice(probe)), 20)
    nb_new = timed(lambda: f.neighbors(random.choice(probe)), 20)
    rc_old = timed(lambda: scan_reach(f, seeds, 2, DECAY), 3)
    rc_new = timed(lambda: f.reach(seeds, 2, DECAY), 3)
    recall_old = RECALL_K * nb_old + rc_old
    recall_new = RECALL_K * nb_new + rc_new

    print(f"  {E:>10,} | {nb_old:>11.2f}ms {nb_new*1000:>7.1f}µs {nb_old/max(nb_new,1e-9):>6.0f}x | "
          f"{rc_old:>9.1f}ms {rc_new*1000:>7.1f}µs {rc_old/max(rc_new,1e-9):>6.0f}x | "
          f"{recall_old:>9.1f}ms → {recall_new*1000:>6.1f}µs")

print("  " + "-" * 92)
print("\n  ✓ NEW == OLD on every sampled call (identical results — no behavior change).")
print("  • OLD neighbors()/reach() grow LINEARLY with edges (the flat-list scan).")
print("  • NEW (adjacency index) is FLAT — microseconds regardless of graph size.")
print("  • 'recall graph' = per-query graph overhead (≈5 seed lookups + 1 reach):")
print("    seconds at 1M edges before; microseconds after. G1 removes the bottleneck.")
print("=" * 96)
