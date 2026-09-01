"""
bench_contradiction_resolution.py  —  PHASE 1: does the field RESOLVE contradiction
by its own dynamics, not just detect it?

Phase 0 proved ACI DETECTS conflict. It does not yet self-heal: a refuted claim
stays live until someone calls supersede() by hand. Phase 1 asks whether the
UQRT-MCA truth algebra can drive resolution on its own — and stay STABLE:
  - converge to the better-supported claim (truth wins),
  - RESIST noise (a few weak lies can't topple an entrenched truth),
  - ALLOW revision (sustained strong new evidence CAN overturn an old truth),
  - HOLD a genuine standoff (equal evidence -> keep both, flagged; no fake winner).

Resolution = SUPERSEDE + MARK, never delete (faithful to ACI's "never delete; keep
the audit trail"). The loser's psi is driven clearly below the winner's and it is
flagged superseded — recall won't surface it, but it survives as history.

The dynamic uses ONLY aci.logic_gates (truth-native, not stats):
  OR (a+b)          : corroboration = cumulative evidence; the ONLY source of psi
  log_compress      : compare truths without sigmoid saturation (gaps stay visible)
  distance_decay    : contradiction distance -> resolution pressure (1 - e^-gap)
  coupling kappa    : entrenchment (low entropy -> high kappa) RESISTS being moved
  challenger ratio  : the incumbent erodes only in proportion to the challenger's
                      OWN strength -> weak noise barely moves it; strong sustained
                      evidence eventually overturns it.

BASELINE = detect-only (today): corroboration accrues psi, but contradiction applies
no pressure and nothing is ever marked -> refuted claims stay live forever.

Run:  py benchmark/bench_contradiction_resolution.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from aci import logic_gates as g          # noqa: E402  (the real algebra under test)

STANDOFF = 0.15      # |log(1+a)-log(1+b)| under this -> genuine standoff, hold both
MARGIN = 0.40        # log-space gap needed to call a claim clearly superseded
PULL = 0.55          # base resolution rate on the weaker claim
DOM_ERODE = 0.55     # incumbent erosion rate, scaled by challenger strength


def norm(psi):
    """Compare truths in a NON-saturating space. sigmoid flattens above psi~3, so
    gaps between well-supported claims vanish; log_compress (log(1+psi)) does not."""
    return g.log_compress(psi)


class Claim:
    __slots__ = ("label", "psi", "S", "superseded", "flagged")
    def __init__(self, label, psi, S):
        self.label, self.psi, self.S = label, psi, S
        self.superseded, self.flagged = False, False
    def kappa(self):                      # entrenchment: low entropy -> high kappa -> resists
        return g.coupling_constant(1.0, self.S)


def corroborate(c, evidence_psi):
    """Supporting evidence accrues: OR (a+b) is cumulative evidence; bounded; lowers entropy."""
    c.psi = min(g.OR(c.psi, evidence_psi * 0.5), 50.0)
    c.S = max(c.S * 0.92, 0.05)


def resolve(a, b, dynamic=True):
    """One contradiction event between claims a,b. Mutates psi/entropy/flags."""
    if not dynamic:
        return                                          # detect-only: no pressure, no marking
    gap = abs(norm(a.psi) - norm(b.psi))                 # contradiction distance, log space
    if gap < STANDOFF:                                  # genuine standoff -> hold both
        a.flagged = b.flagged = True
        a.superseded = b.superseded = False
        return
    dom, sub = (a, b) if a.psi >= b.psi else (b, a)
    pressure = 1.0 - g.distance_decay(gap, scale=1.0)    # 0..1, grows with contradiction distance
    ratio = norm(sub.psi) / max(norm(dom.psi), g.EPS)    # challenger strength: weak noise ~0, strong ~1
    # weaker claim is undermined, gated by its entrenchment (kappa)
    sub.psi = max(sub.psi * (1.0 - PULL * pressure / sub.kappa()), g.EPS)
    # incumbent erodes ONLY in proportion to how strong the challenger is -> noise barely moves it,
    # sustained strong evidence eventually overturns it.
    dom.psi = max(dom.psi * (1.0 - DOM_ERODE * pressure * ratio / dom.kappa()), g.EPS)
    sub.S = min(sub.S + 0.05, 2.0)
    dom.S = min(dom.S + 0.03, 2.0)
    # mark current standing (supersede the dominated one; never delete)
    hi, lo = (a, b) if a.psi >= b.psi else (b, a)
    hi.superseded = hi.flagged = False
    lo.superseded, lo.flagged = True, False


def run(stream, dynamic=True):
    A, B = Claim("A", 1.0, 1.0), Claim("B", 1.0, 1.0)
    claims = [A, B]
    traj = []
    for op in stream:
        if op[0] == "corro":
            corroborate(claims[op[1]], op[2])
        else:
            resolve(claims[op[1]], claims[op[2]], dynamic)
        traj.append((A.psi, B.psi))
    return claims, traj


def winner(claims):
    return max(claims, key=lambda c: c.psi)


# ---------------------------------------------------------------- scenarios (fixed params, one rule)
def underdog():
    s = [("corro", 1, 0.8)] * 3                       # lie B entrenches first
    for _ in range(6):
        s += [("corro", 0, 1.2), ("conflict", 0, 1)]  # truth A corroborated, stronger
    return s, "truth starts behind, accrues real support -> A wins, B superseded"

def noise():
    s = [("corro", 0, 1.5)] * 6                       # truth A heavily entrenched
    s += [("corro", 1, 0.4), ("conflict", 0, 1)] * 3  # 3 weak low-trust lies attack
    return s, "entrenched truth must NOT be toppled by repeated weak lies"

def revision():
    s = [("corro", 0, 1.2)] * 5                       # old fact A well-supported
    for _ in range(9):
        s += [("corro", 1, 1.5), ("conflict", 0, 1)]  # world changed: strong, sustained new evidence
    return s, "legit revision: sustained strong new evidence overturns the old fact"

def standoff():
    s = []
    for _ in range(8):
        s += [("corro", 0, 1.0), ("corro", 1, 1.0), ("conflict", 0, 1)]
    return s, "equal evidence -> hold BOTH, flagged, no fake winner"


print("=" * 88)
print(" PHASE 1 — CONTRADICTION RESOLUTION  (does the field self-heal, stably?)")
print("=" * 88)

SCN = [("S1 underdog", underdog, "A"), ("S2 noise", noise, "A"),
       ("S3 revision", revision, "B"), ("S4 standoff", standoff, "STANDOFF")]
passed = 0
for name, fn, expect in SCN:
    stream, desc = fn()
    claims, traj = run(stream, dynamic=True)
    _, traj0 = run(stream, dynamic=False)
    A, B = claims
    tail = traj[-max(3, len(traj) // 4):]
    converged = len({("A" if a >= b else "B") for a, b in tail}) == 1
    gap = abs(norm(A.psi) - norm(B.psi))

    if expect == "STANDOFF":
        ok = (A.flagged and B.flagged and not A.superseded and not B.superseded and gap < STANDOFF)
        got = f"both held A={A.psi:.2f} B={B.psi:.2f} flagged (no fake winner)"
    elif name.startswith("S2"):
        ok = converged and winner(claims).label == "A" and A.psi > 3.0
        got = f"truth A intact psi={A.psi:.2f}; attacker B={B.psi:.2f} superseded={B.superseded}"
    else:
        w = winner(claims).label
        loser = B if expect == "A" else A
        win = A if expect == "A" else B
        ok = converged and w == expect and loser.superseded and (norm(win.psi) - norm(loser.psi)) > MARGIN
        got = (f"winner={w}, loser '{loser.label}' superseded={loser.superseded} "
               f"(A={A.psi:.2f} B={B.psi:.2f})")

    passed += ok
    a0, b0 = traj0[-1]
    print(f"\n  {name}: {desc}")
    print(f"    dynamic : {got}")
    print(f"    converged={converged}  ->  {'PASS' if ok else 'FAIL'}")
    print(f"    detect-only: A={a0:.2f} B={b0:.2f}, marked=none  (refuted claim never leaves the field)")

print("\n" + "=" * 88)
print(f"  RESULT: resolution dynamic passed {passed}/{len(SCN)} scenarios (one fixed parameter set).")
if passed == len(SCN):
    print("  GROUNDED — the field converges to coherent truth, resists noise, allows legit revision,")
    print("  and HOLDS a genuine standoff without collapse — by its own dynamics. Worth wiring.")
else:
    print("  NOT READY — a scenario above failed. Diagnose before wiring.")
print("=" * 88)
