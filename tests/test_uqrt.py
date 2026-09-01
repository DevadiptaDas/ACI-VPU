"""
UQRT-MCA validation tests (stdlib unittest).

Run:  py -m unittest discover -s tests   (from the ACI- VPU folder)
"""
import os
import sys
import unittest

# Tests use the deterministic, fast lexical embedder + heuristic extractor
# (semantic embeddings + spaCy are the product defaults).
os.environ.setdefault("ACI_EMBEDDER", "lexical")
os.environ.setdefault("ACI_EXTRACTOR", "heuristic")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aci import ACI               # noqa: E402
from aci import logic_gates as g  # noqa: E402


class TestLogicGates(unittest.TestCase):
    def test_not_is_reciprocal(self):
        self.assertAlmostEqual(g.NOT(0.5), 2.0, places=4)
        self.assertAlmostEqual(g.NOT(1.0), 1.0, places=4)   # fixed point
        self.assertAlmostEqual(g.NOT(2.0), 0.5, places=4)

    def test_and_is_harmonic(self):
        self.assertAlmostEqual(g.AND(1.0, 1.0), 0.5, places=3)
        self.assertAlmostEqual(g.AND(0.5, 0.5), 0.25, places=3)

    def test_xor_is_contradiction_distance(self):
        self.assertAlmostEqual(g.XOR(1.0, 1.0), 0.0, places=4)
        self.assertAlmostEqual(g.XOR(2.0, 0.1), 1.9, places=4)

    def test_sigmoid(self):
        self.assertAlmostEqual(g.sigmoid(0.0), 0.5, places=4)
        self.assertTrue(g.sigmoid(10) > 0.95)
        self.assertTrue(g.sigmoid(-10) < 0.05)

    def test_not_is_involution(self):
        for t in (0.2, 0.5, 1.0, 2.0, 5.0):
            self.assertAlmostEqual(g.NOT(g.NOT(t)), t, places=4)

    def test_demorgan_duality(self):
        # AND and OR are De Morgan duals under NOT (the canonical-set guarantee).
        for a, b in ((0.5, 2.0), (0.3, 0.7), (1.0, 4.0)):
            self.assertAlmostEqual(g.AND(a, b), g.NOT(g.OR(g.NOT(a), g.NOT(b))), places=3)
            self.assertAlmostEqual(g.OR(a, b), g.NOT(g.AND(g.NOT(a), g.NOT(b))), places=3)

    def test_implies_is_demorgan_consistent(self):
        a, b = 0.5, 2.0
        self.assertAlmostEqual(g.IMPLIES(a, b), g.NOT(a) + b, places=4)  # 1/a + b

    def test_liar_paradox_resolves_to_fixed_point(self):
        # "this statement is false" => psi = NOT(psi) = 1/psi => psi = 1.
        def resolve(p, a=0.5, n=25):
            for _ in range(n):
                p = (1 - a) * p + a * g.NOT(p)
            return p
        self.assertAlmostEqual(resolve(0.2), 1.0, places=2)   # from "mostly false"
        self.assertAlmostEqual(resolve(5.0), 1.0, places=2)   # from "mostly true"
        # binary negation oscillates (period 2): never a fixed point
        v = True
        seq = [(v := not v) for _ in range(4)]
        self.assertEqual(seq, [False, True, False, True])

    def test_maca_converges_to_one(self):
        from_high = g.refine_truth(2.0, alpha=0.2, iterations=30)
        from_low = g.refine_truth(0.2, alpha=0.2, iterations=30)
        self.assertAlmostEqual(from_high, 1.0, places=1)
        self.assertAlmostEqual(from_low, 1.0, places=1)

    def test_energy_is_positive_and_monotonic(self):
        e1 = g.energy_cost(1, 1, 1, speed_of_perception=3e8)
        e2 = g.energy_cost(10, 5, 100, speed_of_perception=3e8)
        self.assertTrue(e1 > 0)
        self.assertTrue(e2 > e1)


class TestACI(unittest.TestCase):
    def setUp(self):
        self.aci = ACI(db_path=":memory:", observer_id="test")

    def tearDown(self):
        self.aci.close()

    def test_monadise_and_recall(self):
        self.aci.monadise("My accountant is Sarah Chen.", source_type="USER_INPUT",
                          metadata={"subject": "accountant", "predicate": "is",
                                    "object": "Sarah Chen"})
        hits = self.aci.recall("who is my accountant", k=1)
        self.assertTrue(hits)
        self.assertIn("sarah", hits[0].monad.value.lower())

    def test_contradiction_detected(self):
        self.aci.monadise("Project Apollo deadline is March 15.",
                          metadata={"subject": "project apollo", "predicate": "deadline",
                                    "object": "March 15"}, truth_value=2.0)
        v = self.aci.validate("Project Apollo deadline is April 2.",
                              metadata={"subject": "project apollo", "predicate": "deadline",
                                        "object": "April 2"})
        self.assertFalse(v.is_consistent)
        self.assertTrue(len(v.contradictions) >= 1)

    def test_no_false_contradiction(self):
        self.aci.monadise("My accountant is Sarah Chen.",
                          metadata={"subject": "accountant", "predicate": "is",
                                    "object": "Sarah Chen"}, truth_value=2.0)
        v = self.aci.validate("I prefer morning meetings.",
                              metadata={"subject": "meeting preference", "predicate": "is",
                                        "object": "morning"})
        self.assertTrue(v.is_consistent)

    def test_supersession_returns_current(self):
        meta = {"subject": "project apollo", "predicate": "deadline"}
        self.aci.monadise("Project Apollo deadline is March 15.",
                          metadata={**meta, "object": "March 15"}, truth_value=2.0)
        self.aci.monadise("Project Apollo deadline is April 2.",
                          metadata={**meta, "object": "April 2"}, truth_value=2.0)
        ans = self.aci.recall("apollo deadline", k=1)[0].monad.value
        self.assertIn("april", ans.lower())   # current, not stale March

    def test_truth_aware_validation(self):
        # A low-truth rumor must NOT undermine a verified fact (and vice versa).
        meta = {"subject": "ceo", "predicate": "is"}
        self.aci.monadise("The CEO is Maria Lopez.",
                          metadata={**meta, "object": "Maria Lopez"}, truth_value=2.0)
        self.aci.monadise("The CEO is John Smith.",
                          metadata={**meta, "object": "John Smith"}, truth_value=0.2)
        v_fact = self.aci.validate("The CEO is Maria Lopez.", truth_value=2.0,
                                   metadata={**meta, "object": "Maria Lopez"})
        v_rumor = self.aci.validate("The CEO is John Smith.", truth_value=0.2,
                                    metadata={**meta, "object": "John Smith"})
        self.assertTrue(v_fact.is_consistent)    # verified fact stands
        self.assertFalse(v_rumor.is_consistent)  # rumor flagged vs higher-truth fact

    def test_auto_extraction_untagged(self):
        # No metadata passed - subject/predicate/object auto-extracted from raw text.
        self.aci.monadise("The project deadline is March 15.", truth_value=2.0)
        self.aci.monadise("The project deadline is April 2.", truth_value=2.0)
        ans = self.aci.recall("project deadline", k=1)[0].monad.value
        self.assertIn("april", ans.lower())   # supersession worked with ZERO tagging

    def test_index_backed_recall(self):
        self.aci.monadise("My accountant is Sarah Chen.", truth_value=2.0)
        self.aci.monadise("The Apollo mission launches next year.", truth_value=2.0)
        hits = self.aci.recall("accountant", k=2)
        self.assertTrue(hits)
        self.assertIn("sarah", hits[0].monad.value.lower())

    def test_graph_aware_recall(self):
        for i in range(45):                    # fillers so the sim-pool excludes B
            self.aci.monadise(f"Apollo status update number {i}.",
                              source_type="LOG", dedup=False)
        a = self.aci.monadise("The Apollo mission deadline is April 2.", truth_value=2.0)
        b = self.aci.monadise("Contact Rita Gomez about scheduling.", truth_value=2.0)
        self.aci.relate(a.id, b.id, "ASSOCIATIVE")
        no_graph = {h.monad.id for h in self.aci.recall("apollo mission deadline", k=5, graph_hops=0)}
        with_graph = {h.monad.id for h in self.aci.recall("apollo mission deadline", k=5, graph_hops=1)}
        self.assertNotIn(b.id, no_graph)       # B is lexically unrelated -> not in sim-pool
        self.assertIn(b.id, with_graph)        # B surfaces ONLY via the graph neighbour

    def test_observer_relative_trust(self):
        # Same KB, two observers, opposite answers - driven purely by trust frame.
        from aci import Observer
        self.aci.monadise("Acme deal price is 12000 dollars.", source_type="CRM",
                          observer_id="global",
                          metadata={"subject": "acme deal", "predicate": "price",
                                    "object": "12000 dollars"}, truth_value=2.0)
        self.aci.monadise("Acme deal price is 9500 dollars.", source_type="CONTRACT",
                          observer_id="global",
                          metadata={"subject": "acme deal", "predicate": "price",
                                    "object": "9500 dollars"}, truth_value=2.0)
        legal = Observer(id="legal", trust={"CONTRACT": 3.0, "CRM": 0.3})
        sales = Observer(id="sales", trust={"CRM": 3.0, "CONTRACT": 0.3})
        q = "acme deal price"
        self.assertIn("9500", self.aci.recall(q, k=1, observer=legal)[0].monad.value)
        self.assertIn("12000", self.aci.recall(q, k=1, observer=sales)[0].monad.value)

    def test_observer_relative_visibility(self):
        # Private belief is invisible to an observer scoped to global only.
        from aci import Observer
        self.aci.monadise("The Earth is round.", source_type="SCIENCE", observer_id="global",
                          metadata={"subject": "earth", "predicate": "shape", "object": "round"},
                          truth_value=3.0)
        self.aci.monadise("The Earth is flat.", source_type="BELIEF", observer_id="alice",
                          metadata={"subject": "earth", "predicate": "shape", "object": "flat"},
                          truth_value=2.0)
        alice = Observer(id="alice", visible={"alice", "global"},
                         trust={"BELIEF": 3.0, "SCIENCE": 0.5})
        public = Observer(id="public", visible={"global"})
        self.assertIn("flat", self.aci.recall("shape of the earth", k=1, observer=alice)[0].monad.value.lower())
        self.assertIn("round", self.aci.recall("shape of the earth", k=1, observer=public)[0].monad.value.lower())

    def test_reasoning_cache(self):
        calls = {"n": 0}

        def fn(c):
            calls["n"] += 1
            return "R:" + c

        r1, h1 = self.aci.cached_compute("translate the contract into french", fn)
        r2, h2 = self.aci.cached_compute("translate the contract into french", fn)
        self.assertFalse(h1)
        self.assertTrue(h2)               # second identical request is served from cache
        self.assertEqual(calls["n"], 1)   # expensive fn ran only once
        self.assertEqual(r1, r2)

    def test_energy_gate(self):
        from aci.optimize import EnergyGovernor
        from aci.monad import Monad
        signal = Monad(summary="signal", truth_value=2.0, entropy=0.1)
        noise = Monad(summary="noise", truth_value=0.3, entropy=3.0)
        process, suppress = EnergyGovernor.gate([signal, noise], min_value=0.5)
        self.assertIn(signal, process)
        self.assertIn(noise, suppress)

    def test_route_local_vs_cloud(self):
        self.aci.monadise("The office wifi password is sunrise42.", truth_value=2.0)
        self.assertEqual(self.aci.route("office wifi password")["target"], "local")
        self.assertEqual(self.aci.route("the capital of mongolia")["target"], "cloud")

    def test_forget_and_list(self):
        m = self.aci.monadise("Temporary secret note about something.", truth_value=1.0)
        self.assertTrue(any(x.id == m.id for x in self.aci.list_monads()))
        self.assertTrue(self.aci.forget(m.id))                 # right to be forgotten
        self.assertFalse(any(x.id == m.id for x in self.aci.list_monads()))
        self.assertEqual(len(self.aci.recall("temporary secret", k=5)), 0)  # gone from index too

    def test_forget_by_source(self):
        self.aci.monadise("Document A, part one.", metadata={"path": "/docs/a.txt"})
        self.aci.monadise("Document A, part two.", metadata={"path": "/docs/a.txt"})
        self.aci.monadise("Document B.", metadata={"path": "/docs/b.txt"})
        removed = self.aci.forget_by_source("/docs/a.txt")
        self.assertEqual(removed, 2)
        paths = [m.metadata.get("path") for m in self.aci.list_monads()]
        self.assertNotIn("/docs/a.txt", paths)
        self.assertIn("/docs/b.txt", paths)

    def test_dedup_compression(self):
        doc = "Revenue grew across all regions this quarter. " * 50
        for _ in range(3):
            self.aci.monadise(doc, source_type="FILE", summary="Q3 revenue")
        stats = self.aci.compress()
        self.assertEqual(stats["duplicates_merged"], 2)   # 1 stored, 2 merged
        self.assertEqual(stats["monads_stored"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
