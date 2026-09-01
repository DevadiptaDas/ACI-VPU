"""
MeaningField - the monad graph.

Nodes = monads, edges = typed relations. Supports traversal and evidence
combination via the logic gates. Ported from aios_app meaning/MeaningField.kt.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from .monad import Monad
from . import logic_gates as gates


@dataclass
class RelationEdge:
    source_id: str
    target_id: str
    relation_type: str = "ASSOCIATIVE"
    weight: float = 1.0


class MeaningField:
    def __init__(self):
        self.nodes: Dict[str, Monad] = {}
        self.edges: List[RelationEdge] = []            # kept for graph serialization (viz)
        # G1: incremental adjacency index — node_id -> {neighbor_id: clamped_weight} (both
        # directions). Built as edges are added, so neighbors()/reach() are O(degree), not
        # O(E). Replaces the per-call flat-list scan (see benchmark/bench_graph_scaling.py).
        self._adj: Dict[str, Dict[str, float]] = {}

    def add(self, monad: Monad) -> Monad:
        self.nodes[monad.id] = monad
        return monad

    def _link(self, a: str, b: str, weight: float) -> None:
        w = min(max(weight, 0.0), 1.0) or 1.0          # clamp once, here (was per reach() call)
        bucket = self._adj.setdefault(a, {})
        if w > bucket.get(b, 0.0):                      # keep the strongest edge between a pair
            bucket[b] = w

    def relate(self, source_id: str, target_id: str,
               relation_type: str = "ASSOCIATIVE", weight: float = 1.0) -> None:
        self.edges.append(RelationEdge(source_id, target_id, relation_type, weight))
        self._link(source_id, target_id, weight)       # both directions -> O(1) lookups later
        self._link(target_id, source_id, weight)
        if source_id in self.nodes and target_id not in self.nodes[source_id].links:
            self.nodes[source_id].links.append(target_id)

    def neighbors(self, node_id: str) -> set:
        """All directly-related node ids (both directions). O(degree) via the adjacency index."""
        return set(self._adj.get(node_id, ()))

    def reach(self, seed_ids, max_hops: int = 2, decay: float = 0.5) -> Dict[str, float]:
        """Weighted multi-hop reachability from a set of seeds: returns {node_id: strength}
        in (0, 1]. Each hop multiplies by decay * edge_weight, keeping the strongest path.
        Uses the prebuilt adjacency index (O(reached), not O(E) per call).

        Seeds are propagation SOURCES, not self-credited: a node's strength reflects how
        well it is CONNECTED to the anchors (so a connected non-seed can outrank an
        isolated seed, whose own similarity already carries it)."""
        strength: Dict[str, float] = {}
        frontier = {s: 1.0 for s in seed_ids}
        for _ in range(max(max_hops, 0)):
            nxt: Dict[str, float] = {}
            for nid, st in frontier.items():
                for nb, w in self._adj.get(nid, {}).items():
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

    def traverse(self, start_id: str, max_depth: int = 3) -> List[Monad]:
        visited, out = set(), []

        def go(cur: str, depth: int):
            if depth > max_depth or cur in visited or cur not in self.nodes:
                return
            visited.add(cur)
            out.append(self.nodes[cur])
            for e in self.edges:
                if e.source_id == cur:
                    go(e.target_id, depth + 1)

        go(start_id, 0)
        return out

    def resolve(self, monad_ids: List[str]) -> dict:
        """Combine evidence from several monads via conservative AND."""
        nodes = [self.nodes[i] for i in monad_ids if i in self.nodes]
        if not nodes:
            return {"truth_value": 0.0, "entropy": 1.0, "confidence": 0.0, "contributing": []}
        truth = nodes[0].truth_value
        entropy = nodes[0].entropy
        for n in nodes[1:]:
            truth = gates.AND(truth, n.truth_value)
            entropy = (entropy + n.entropy) / 2
        return {
            "truth_value": truth,
            "entropy": entropy,
            "confidence": gates.sigmoid(truth),
            "contributing": [n.id for n in nodes],
        }
