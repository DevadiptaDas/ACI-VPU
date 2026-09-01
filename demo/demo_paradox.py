"""
HEAD-TO-HEAD: self-reference & contradiction.

    BINARY logic            vs            CIRCULAR NUMBER LINE  (UQRT-MCA)
    truth in {0, 1}                       truth psi in (0, inf),  NOT(psi)=1/psi

The distinctive prediction, made visible:
  - Binary logic OSCILLATES on self-reference (the Liar) and EXPLODES on
    contradiction (anything becomes derivable).
  - The circular reciprocal algebra RESOLVES self-reference to the fixed point
    psi=1 (NOT(1)=1), and HOLDS contradiction as a bounded, measured quantity -
    the system stays stable and usable.

This is the externally-checkable behavior standard logic cannot reproduce.

Run:  py demo/demo_paradox.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci import logic_gates as g  # the ACTUAL ACI gates: NOT(psi)=1/psi


def line(t=""):
    print("\n" + "=" * 70)
    if t:
        print(t)
        print("=" * 70)


# ---------- CASE 1: THE LIAR PARADOX  ("this statement is false") ----------
def liar_binary(steps=8):
    """Classical truth is binary; 'is false' = negation applied to itself."""
    v, seq = True, []
    for _ in range(steps):
        seq.append("T" if v else "F")
        v = not v
    return seq


def liar_circular(psi0, alpha=0.5, steps=8):
    """psi = NOT(psi) = 1/psi  ->  the Liar is a fixed-point equation. The MACA
    refinement (psi <- (1-a)psi + a/psi) converges to it."""
    psi, traj = psi0, [round(psi0, 4)]
    for _ in range(steps):
        psi = (1 - alpha) * psi + alpha * g.NOT(psi)   # g.NOT(psi) == 1/psi
        traj.append(round(psi, 4))
    return traj


# ---------- CASE 2: DIRECT CONTRADICTION  (assert P and NOT P) ----------
def contradiction_binary():
    # P = True and (NOT P) = True at once -> classical inconsistency.
    # Principle of explosion: from P and ~P, ANY Q and ~Q are derivable.
    return "P=True AND (NOT P)=True  ->  EXPLOSION: every Q and ~Q derivable (system trivialized)"


def contradiction_circular(psi_P=2.0, asserted_notP=2.0):
    consistent_notP = g.NOT(psi_P)                 # what NOT P *should* be = 1/2 = 0.5
    conflict = abs(asserted_notP - consistent_notP)  # bounded, finite measure
    fused = g.AND(psi_P, asserted_notP)            # harmonic AND stays bounded
    return consistent_notP, conflict, fused


def main():
    line("CASE 1 - THE LIAR PARADOX:  \"this statement is false\"")
    print("  BINARY LOGIC:")
    print(f"     {' -> '.join(liar_binary())} ...")
    print("     verdict: OSCILLATES, period 2 - NO stable truth value.\n")
    print("  CIRCULAR NUMBER LINE (UQRT-MCA):  psi = NOT(psi) = 1/psi")
    print(f"     from a 'mostly-false' belief (0.2): {liar_circular(0.2)}")
    print(f"     from a 'mostly-true'  belief (5.0): {liar_circular(5.0)}")
    print("     verdict: BOTH converge to psi = 1.0  - the self-consistent fixed")
    print("     point (NOT(1)=1). The paradox RESOLVES instead of oscillating.")

    line("CASE 2 - DIRECT CONTRADICTION:  assert P and (NOT P) together")
    print("  BINARY LOGIC:")
    print(f"     {contradiction_binary()}\n")
    print("  CIRCULAR NUMBER LINE (UQRT-MCA):")
    cn, conflict, fused = contradiction_circular()
    print(f"     consistent (NOT P) should be 1/psi_P = {cn}")
    print(f"     but (NOT P) is asserted at 2.0  ->  conflict measured = {conflict} (finite, bounded)")
    print(f"     fused truth (harmonic AND) = {round(fused, 4)}  (stays bounded)")
    print("     verdict: contradiction becomes a MEASURED, bounded quantity.")
    print("     System stays stable and usable - NO explosion.")

    line("THE POINT")
    print("  Standard binary logic cannot do either of these: it oscillates on")
    print("  self-reference and trivializes under contradiction. The circular")
    print("  reciprocal number line (NOT(psi)=1/psi) resolves self-reference to a")
    print("  fixed point and holds contradiction as a finite quantity.")
    print("  That is the distinctive, externally-checkable UQRT-MCA behavior.")


if __name__ == "__main__":
    main()
