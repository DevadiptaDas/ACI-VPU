"""
Monad Logic Gates - formal UQRT-MCA truth algebra.

Truth values psi are continuous and observer-relative: psi in [0, inf).
  - psi -> 0   : false / unreliable
  - psi  = 1   : self-consistent fixed point
  - psi -> inf : absolutely true (limit, never reached)

CANONICAL ALGEBRA (the single authoritative set — see CANON_GATES.md).
It is internally consistent: NOT is an involution and AND/OR are De Morgan duals.
    NOT(t)      = 1/t
    AND(a,b)    = a*b / (a+b)        = 1 / (1/a + 1/b)
    OR(a,b)     = a + b              (De Morgan dual of AND under NOT; unbounded
                                      = cumulative evidence; normalize for [0,1])
    XOR(a,b)    = |a - b|            (contradiction distance)
    IMPLIES(a,b)= NOT(a) OR b        = 1/a + b
    sigma(t)    = 1/(1+e^-t)         (probability view)
Check: NOT(AND(NOT a, NOT b)) = NOT(1/(a+b)) = a+b = OR(a,b).  De Morgan holds.
"""

from __future__ import annotations
import math

EPS = 1e-9


def NOT(psi: float) -> float:
    """Dialectical inversion: NOT(psi) = 1/psi. Fixed point at psi=1."""
    return 1.0 / max(psi, EPS)


def AND(psi1: float, psi2: float) -> float:
    """Conservative conjunction (evidence fusion): (psi1*psi2)/(psi1+psi2).
    Two weak beliefs do not make a strong one. AND(1,1)=0.5, AND(0.5,0.5)=0.25."""
    return (psi1 * psi2) / (psi1 + psi2 + EPS)


def OR(psi1: float, psi2: float) -> float:
    """Disjunctive support (cumulative evidence): psi1 + psi2.
    Must be normalized (sigmoid/log) before probabilistic use."""
    return psi1 + psi2


def XOR(psi1: float, psi2: float) -> float:
    """Contradiction / difference operator: |psi1 - psi2|.
    0 = perfect agreement; large = strong conflict."""
    return abs(psi1 - psi2)


def IMPLIES(psi1: float, psi2: float) -> float:
    """Material implication P->Q = NOT(P) OR Q = (1/psi1) + psi2.
    De Morgan-consistent with NOT=1/t and OR=sum (was max(); corrected in Phase 0)."""
    return OR(NOT(psi1), psi2)


def sigmoid(psi: float) -> float:
    """Probability interpretation: sigma(psi) = 1/(1+e^-psi) in (0,1)."""
    if psi >= 0:
        return 1.0 / (1.0 + math.exp(-psi))
    z = math.exp(psi)
    return z / (1.0 + z)


def log_compress(psi: float) -> float:
    """Meaning-density control: log(1+psi). Prevents dominance of huge psi."""
    return math.log(1.0 + max(psi, 0.0))


def refine_truth(psi: float, alpha: float = 0.2, iterations: int = 1) -> float:
    """Observer feedback loop (the MACA convergence step):
        psi_{n+1} = (1-alpha)*psi_n + alpha*(1/psi_n)
    Converges to psi = 1, the equilibrium of self-consistent truth."""
    refined = max(psi, EPS)
    for _ in range(max(iterations, 1)):
        refined = (1.0 - alpha) * refined + alpha * (1.0 / refined)
    return max(refined, 0.0)


def NOT_c(z: complex) -> complex:
    """Phase-preserving complex negation: NOT(z) = 1 / conj(z)  (NOT 1/z).

    The scalar gates above collapse every belief onto one axis (psi -> 1). When a
    belief also carries a DIRECTION — a phase theta encoding its qualitative stance,
    not just its magnitude — the right involution keeps that direction and only
    inverts the magnitude:  for z = r*e^{i.theta},  1/conj(z) = (1/r)*e^{i.theta}.
    Its fixed-point set is the whole unit circle |z|=1 (every fully-consistent stance),
    and NOT_c(NOT_c(z)) = z (involution).

    TRAP (the exact error to avoid): the naive 1/z = (1/r)*e^{-i.theta} CONJUGATES the
    phase, so iterating a revision loop with it flips theta each step and collapses all
    beliefs back onto the real axis (+-1), destroying direction. Only 1/conj(z) works."""
    if z == 0:
        z = complex(EPS, 0.0)
    return 1.0 / z.conjugate()


def refine_truth_c(z: complex, alpha: float = 0.2, iterations: int = 1) -> complex:
    """Complex belief-revision loop (phase-preserving generalization of refine_truth):
        z_{n+1} = (1-alpha)*z_n + alpha*(1/conj(z_n))
    Converges to the unit circle e^{i.theta}: the MAGNITUDE relaxes to 1 (self-consistent
    confidence) while the PHASE theta (the belief's direction/content) is preserved. The
    real restriction theta=0 reproduces refine_truth exactly (fixed point psi=1)."""
    refined = z if z != 0 else complex(EPS, 0.0)
    for _ in range(max(iterations, 1)):
        refined = (1.0 - alpha) * refined + alpha * (1.0 / refined.conjugate())
    return refined


def distance_decay(distance: float, scale: float = 1.0) -> float:
    """Spatial/contextual truth decay: exp(-distance/scale)."""
    return math.exp(-(distance / max(scale, EPS)))


def coupling_constant(contextual_complexity: float, entropy: float) -> float:
    """kappa = (1 + xi) / (1 + S), simplified contextual coupling."""
    return (1.0 + contextual_complexity) / (1.0 + max(entropy, 0.0))


def energy_cost(delta_c: float, delta_s: float, durance_squared: float,
                speed_of_perception: float = 1.0, kappa: float = 1.0) -> float:
    """UQRT energy: dE = kappa * dC * dS * (ds^2 / c^2).
    Every cognitive operation has an energetic cost."""
    c = max(speed_of_perception, EPS)
    return kappa * abs(delta_c) * abs(delta_s) * abs(durance_squared) / (c * c)
