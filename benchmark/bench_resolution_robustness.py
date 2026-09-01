"""
bench_resolution_robustness.py — is the Phase-1 resolution dynamic a BASIN or a SPIKE?

4/4 on one tuned parameter set proves little if the rule only works at exactly those
values. Here we re-run the same four scenarios across a grid of perturbed parameters
(+/- around the chosen set) and report what FRACTION of configurations still pass 4/4.
A healthy dynamic passes across a band; a fragile one passes only at the center.

Same truth-native rule as bench_contradiction_resolution.py, with the four parameters
lifted into function arguments so they can be swept. (No product code; test only.)

Run:  py benchmark/bench_resolution_robustness.py
"""
import sys
import itertools
sys.stdout.reconfigure(encoding="utf-8")

from aci import logic_gates as g          # noqa: E402


def norm(psi):
    return g.log_compress(psi)


class Claim:
    __slots__ = ("psi", "S", "superseded", "flagged")
    def __init__(self): self.psi, self.S, self.superseded, self.flagged = 1.0, 1.0, False, False
    def kappa(self): return g.coupling_constant(1.0, self.S)


def corroborate(c, ev):
    c.psi = min(g.OR(c.psi, ev * 0.5), 50.0)
    c.S = max(c.S * 0.92, 0.05)


def resolve(a, b, P):
    standoff, margin, pull, dom_erode = P
    gap = abs(norm(a.psi) - norm(b.psi))
    if gap < standoff:
        a.flagged = b.flagged = True
        a.superseded = b.superseded = False
        return
    dom, sub = (a, b) if a.psi >= b.psi else (b, a)
    pressure = 1.0 - g.distance_decay(gap, 1.0)
    ratio = norm(sub.psi) / max(norm(dom.psi), g.EPS)
    sub.psi = max(sub.psi * (1.0 - pull * pressure / sub.kappa()), g.EPS)
    dom.psi = max(dom.psi * (1.0 - dom_erode * pressure * ratio / dom.kappa()), g.EPS)
    sub.S = min(sub.S + 0.05, 2.0)
    dom.S = min(dom.S + 0.03, 2.0)
    hi, lo = (a, b) if a.psi >= b.psi else (b, a)
    hi.superseded = hi.flagged = False
    lo.superseded, lo.flagged = True, False


def run(stream, P):
    A, B = Claim(), Claim()
    cs = [A, B]
    for op in stream:
        if op[0] == "corro":
            corroborate(cs[op[1]], op[2])
        else:
            resolve(cs[op[1]], cs[op[2]], P)
    return A, B


def underdog():
    s = [("corro", 1, 0.8)] * 3
    for _ in range(6): s += [("corro", 0, 1.2), ("conflict", 0, 1)]
    return s
def noise():
    s = [("corro", 0, 1.5)] * 6
    s += [("corro", 1, 0.4), ("conflict", 0, 1)] * 3
    return s
def revision():
    s = [("corro", 0, 1.2)] * 5
    for _ in range(9): s += [("corro", 1, 1.5), ("conflict", 0, 1)]
    return s
def standoff():
    s = []
    for _ in range(8): s += [("corro", 0, 1.0), ("corro", 1, 1.0), ("conflict", 0, 1)]
    return s


def passes_all(P):
    standoff_t, margin = P[0], P[1]
    # S1 underdog: A wins, B superseded, clear margin
    A, B = run(underdog(), P)
    if not (A.psi > B.psi and B.superseded and norm(A.psi) - norm(B.psi) > margin):
        return False
    # S2 noise: A intact, wins
    A, B = run(noise(), P)
    if not (A.psi > B.psi and A.psi > 3.0):
        return False
    # S3 revision: B wins, A superseded, clear margin
    A, B = run(revision(), P)
    if not (B.psi > A.psi and A.superseded and norm(B.psi) - norm(A.psi) > margin):
        return False
    # S4 standoff: both held, flagged, near-equal
    A, B = run(standoff(), P)
    if not (A.flagged and B.flagged and not A.superseded and abs(norm(A.psi) - norm(B.psi)) < standoff_t):
        return False
    return True


CENTER = (0.15, 0.40, 0.55, 0.55)   # standoff, margin, pull, dom_erode (the chosen set)
GRID = {
    "standoff":  [0.10, 0.15, 0.20, 0.25],
    "margin":    [0.25, 0.40, 0.55],
    "pull":      [0.40, 0.55, 0.70, 0.85],
    "dom_erode": [0.35, 0.55, 0.75],
}

print("=" * 80)
print(" PHASE 1 ROBUSTNESS — does the resolution rule pass across a BAND of params?")
print("=" * 80)
combos = list(itertools.product(GRID["standoff"], GRID["margin"], GRID["pull"], GRID["dom_erode"]))
ok = [c for c in combos if passes_all(c)]
print(f"\n  center set {CENTER}: {'PASS 4/4' if passes_all(CENTER) else 'FAIL'}")
print(f"  grid configurations tested : {len(combos)}")
print(f"  configurations passing 4/4 : {len(ok)}  ({100*len(ok)//len(combos)}%)")

# per-parameter: over how much of each axis does 4/4 survive (others at center)?
print("\n  single-axis sweeps (other params at center):")
for i, key in enumerate(["standoff", "margin", "pull", "dom_erode"]):
    surviving = []
    for v in GRID[key]:
        P = list(CENTER); P[i] = v
        if passes_all(tuple(P)):
            surviving.append(v)
    print(f"    {key:10}: passes at {surviving}  of {GRID[key]}")

print("\n" + "-" * 80)
if len(ok) >= max(2, len(combos) // 5) and passes_all(CENTER):
    print("  VERDICT: BASIN — the rule holds across a parameter band, not a single point.")
    print("  Safe to carry these dynamics into real-monad wiring (behind an opt-in flag).")
else:
    print("  VERDICT: FRAGILE — passes only near the center. Re-think the rule before wiring.")
print("=" * 80)
