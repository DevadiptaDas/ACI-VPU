"""
Optimization layer (Phase 3) - the USP-2 payoff of monadisation, MEASURABLE.

EnergyGovernor implements the UQRT focus/energy logic:
  - value(m)      = ψ / (1 + S)         information density / worth-computing score
  - Φ             = ΔS / ΔC             perception coefficient (FocusEngine)
  - energy        = κ·ΔC·ΔS·ds²/c²      UQRT energy cost
It lets the substrate process high-value monads first and SUPPRESS low-value,
high-entropy noise (entropy-gated computation).
"""
from __future__ import annotations
from typing import List, Tuple

from . import logic_gates as gates


class EnergyGovernor:
    @staticmethod
    def value(monad) -> float:
        """Worth-computing score: high truth + low entropy = high value."""
        return monad.truth_value / (1.0 + max(monad.entropy, 0.0))

    @staticmethod
    def perception_coefficient(delta_s: float, delta_c: float) -> float:
        return delta_s / max(delta_c, 1e-9)            # Φ = ΔS / ΔC

    @staticmethod
    def energy(delta_c: float, delta_s: float, durance_squared: float = 1.0,
               speed: float = 1.0, kappa: float = 1.0) -> float:
        return gates.energy_cost(delta_c, delta_s, durance_squared, speed, kappa)

    @classmethod
    def prioritize(cls, monads: List) -> List:
        return sorted(monads, key=lambda m: -cls.value(m))

    @classmethod
    def gate(cls, monads: List, min_value: float) -> Tuple[List, List]:
        """Split into (process, suppress) by value threshold - entropy gating."""
        process = [m for m in monads if cls.value(m) >= min_value]
        suppress = [m for m in monads if cls.value(m) < min_value]
        return process, suppress
