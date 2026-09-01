"""
Monad - the universal cognition primitive.

A monad is a structured information unit:  M = <C, psi, S, x6d, weights, mu>
  C       observer/context id
  psi     continuous truth value [0, inf)
  S       entropy (ambiguity = number of possible meanings)
  x6d     6D spacetime coords (3 space + 3 time: past/present/future)
  weights 4-weight matrix (Object / Concept / Monad / Event)
  mu      metadata + relations

Ported from aios_app core/models/Monad.kt.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math
import time
import uuid

from . import logic_gates as gates


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Monad:
    # identity / content
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str = "DERIVED"
    summary: str = ""
    value: str = ""
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    # UQRT-MCA formal fields
    truth_value: float = 1.0          # psi
    entropy: float = 0.0              # S
    observer_id: Optional[str] = None
    spacetime: List[float] = field(default_factory=lambda: [0.0] * 6)
    contextual_complexity: float = 1.0

    # 4-weight matrix
    object_weight: float = 0.5
    concept_weight: float = 0.5
    monad_weight: float = 1.0
    event_weight: float = 0.0

    # temporal dimensions
    temporal_past: float = 0.3
    temporal_present: float = 0.4
    temporal_future: float = 0.3

    # semantics + learning
    embedding: List[float] = field(default_factory=list)
    weight: float = 1.0              # dynamic learning weight (reinforcement)

    # bookkeeping
    timestamp: int = field(default_factory=_now_ms)
    original_size: int = 0
    monad_size: int = 0

    # ---- derived quantities ----
    def normalized_truth(self) -> float:
        """psi -> [0,1] via sigmoid."""
        return gates.sigmoid(self.truth_value)

    def information_density(self) -> float:
        return self.truth_value / self.entropy if self.entropy > 0 else self.truth_value

    def energy_cost(self) -> float:
        kB, ln2 = 1.38e-23, 0.693
        return kB * ln2 * self.entropy * self.truth_value

    def compression_ratio(self) -> float:
        return (self.original_size / self.monad_size) if self.monad_size > 0 else 0.0

    def enforce_complementarity(self) -> None:
        """W_M + W_E = 1 ; normalize W_O + W_C."""
        self.monad_weight = min(max(self.monad_weight, 0.0), 1.0)
        self.event_weight = 1.0 - self.monad_weight
        s = self.object_weight + self.concept_weight
        if s > 0:
            self.object_weight /= s
            self.concept_weight /= s
