"""
Observer - observer-relative reasoning (Phase 2, the differentiator).

UQRT's core claim is that truth is observer-relative. An Observer carries:
  - trust : how much this observer trusts each source_type or owner (default 1.0)
  - visible : which owners' monads it can see (None = sees everything)

The SAME knowledge base then yields different, contextually-correct answers for
different observers, because recall ranks by observer-effective truth
(ψ × trust) and only over what the observer can see. No vanilla vector-DB does
this.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class Observer:
    id: str = "observer-0"
    trust: Dict[str, float] = field(default_factory=dict)   # source_type or owner -> weight
    visible: Optional[Set[str]] = None                       # owner ids; None = see all

    def trust_for(self, monad) -> float:
        """Observer's trust in a monad: by source_type first, then by owner, else 1.0."""
        if monad.source_type in self.trust:
            return self.trust[monad.source_type]
        if monad.observer_id in self.trust:
            return self.trust[monad.observer_id]
        return 1.0

    def can_see(self, monad) -> bool:
        if self.visible is None:
            return True
        return (monad.observer_id == self.id
                or monad.observer_id in self.visible
                or monad.observer_id in ("global", "shared"))
