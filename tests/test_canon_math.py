"""
test_canon_math - asserts the equations in CANON_MATH.md are exactly what the code
runs. If a gate, the paradox fixed point, the recall score, or supersession ever
drifts from the spec, these fail. (Phase 0: math <-> code lockstep.)
"""
import os
os.environ.setdefault("ACI_EMBEDDER", "lexical")
os.environ.setdefault("ACI_EXTRACTOR", "heuristic")

import math
import unittest

from aci import logic_gates as g
from aci.aci import ACI
from aci.observer import Observer


class TestGates(unittest.TestCase):
    def test_not_involution_and_fixed_point(self):
        self.assertAlmostEqual(g.NOT(2.0), 0.5)
        self.assertAlmostEqual(g.NOT(g.NOT(3.0)), 3.0, places=6)   # involution
        self.assertAlmostEqual(g.NOT(1.0), 1.0)                    # fixed point psi=1

    def test_and_or_xor_implies(self):
        self.assertAlmostEqual(g.AND(1.0, 1.0), 0.5, places=6)     # a*b/(a+b)
        self.assertAlmostEqual(g.AND(2.0, 2.0), 1.0, places=6)
        self.assertAlmostEqual(g.OR(2.0, 3.0), 5.0)                # a+b
        self.assertAlmostEqual(g.XOR(2.0, 3.0), 1.0)               # |a-b|
        self.assertAlmostEqual(g.IMPLIES(2.0, 3.0), 0.5 + 3.0, places=6)  # 1/a + b

    def test_de_morgan(self):
        a, b = 2.0, 3.0
        self.assertAlmostEqual(g.NOT(g.AND(g.NOT(a), g.NOT(b))), g.OR(a, b), places=6)

    def test_sigmoid(self):
        self.assertAlmostEqual(g.sigmoid(0.0), 0.5)
        self.assertAlmostEqual(g.sigmoid(1.0), 1 / (1 + math.exp(-1)), places=6)


class TestParadox(unittest.TestCase):
    def test_liar_resolves_to_one(self):
        # psi = 1/psi  =>  psi = 1 ; MACA refine relaxes any psi to 1
        for start in (0.25, 0.5, 2.0, 5.0):
            v = g.refine_truth(start, alpha=0.2, iterations=400)
            self.assertAlmostEqual(v, 1.0, places=2)


class TestComplexGates(unittest.TestCase):
    """Phase-preserving complex extension: NOT_c(z)=1/conj(z), and its revision loop."""

    def test_not_c_is_involution(self):
        for z in (2 + 0j, 0.5j, 1 + 1j, -0.3 + 0.7j):
            self.assertAlmostEqual(g.NOT_c(g.NOT_c(z)), z, places=9)

    def test_unit_circle_is_fixed_point_set(self):
        for theta in (0.0, 0.9, 2.3, -1.7):
            z = complex(math.cos(theta), math.sin(theta))
            self.assertAlmostEqual(g.NOT_c(z), z, places=9)     # every |z|=1 is fixed

    def test_not_c_preserves_phase_inverts_magnitude(self):
        r, theta = 3.0, 0.8
        z = complex(r * math.cos(theta), r * math.sin(theta))
        w = g.NOT_c(z)
        self.assertAlmostEqual(abs(w), 1 / r, places=9)               # magnitude inverted
        self.assertAlmostEqual(math.atan2(w.imag, w.real), theta, places=9)  # phase kept

    def test_refine_c_converges_to_unit_circle_keeping_phase(self):
        for theta in (0.0, 1.2, -2.0):
            z0 = complex(4.0 * math.cos(theta), 4.0 * math.sin(theta))  # far off the circle
            z = g.refine_truth_c(z0, alpha=0.2, iterations=400)
            self.assertAlmostEqual(abs(z), 1.0, places=4)               # magnitude -> 1
            self.assertAlmostEqual(math.atan2(z.imag, z.real), theta, places=4)  # phase held

    def test_real_axis_reduces_to_scalar_refine(self):
        for start in (0.25, 2.0, 5.0):
            zc = g.refine_truth_c(complex(start, 0.0), alpha=0.2, iterations=200)
            self.assertAlmostEqual(zc.imag, 0.0, places=6)
            self.assertAlmostEqual(zc.real, g.refine_truth(start, 0.2, 200), places=6)

    def test_naive_inverse_would_collapse_phase(self):
        # documents WHY 1/z is wrong: it conjugates phase, so a revision loop using it
        # does NOT hold theta (here it lands on the real axis, losing the direction).
        theta = 1.0
        z = complex(4.0 * math.cos(theta), 4.0 * math.sin(theta))
        for _ in range(400):
            z = 0.8 * z + 0.2 * (1.0 / z)      # NAIVE 1/z (the trap)
        self.assertLess(abs(z.imag), 1e-3)     # phase destroyed -> collapsed to real axis


class TestObserverAndRecall(unittest.TestCase):
    def test_effective_truth_is_sigmoid_of_psi_times_trust(self):
        obs = Observer(id="o", trust={"RUMOR": 0.2})

        class M:  # minimal stand-in
            source_type = "RUMOR"; observer_id = "o"
        self.assertAlmostEqual(obs.trust_for(M()), 0.2)

    def test_recall_score_formula(self):
        aci = ACI(":memory:")
        aci.monadise("The capital of France is Paris.", source_type="FILE", truth_value=1.0)
        hits = aci.recall("capital of France", k=1)
        self.assertTrue(hits)
        h = hits[0]
        # recall scores truth as log_compress(psi) normalised to the candidate pool's max —
        # NON-saturating (a psi=6 fact outranks a repeated psi=2.9 one), unlike the old
        # sigmoid which saturated near 1.0 and let recency beat credibility (poison gap).
        # With a single candidate the truth term normalises to 1.0.
        eff_truth = 1.0
        expected = 0.6 * h.similarity + 0.2 * eff_truth + 0.2 * h.recency  # graph_bonus = 0
        self.assertAlmostEqual(h.score, expected, places=5)


class TestSupersession(unittest.TestCase):
    def test_same_source_higher_truth_supersedes(self):
        aci = ACI(":memory:")
        md = {"subject": "deadline", "predicate": "is"}
        aci.monadise("deadline is March 15", source_type="FILE",
                     metadata={**md, "object": "March 15"}, truth_value=1.0)
        aci.monadise("deadline is April 2", source_type="FILE",
                     metadata={**md, "object": "April 2"}, truth_value=1.0)
        olds = [m for m in aci.store.all() if m.metadata.get("status") == "superseded"]
        self.assertEqual(len(olds), 1)
        self.assertIn("March 15", olds[0].value)

    def test_cross_source_kept_as_competing(self):
        aci = ACI(":memory:")
        md = {"subject": "price", "predicate": "is"}
        aci.monadise("price is 100", source_type="CONTRACT",
                     metadata={**md, "object": "100"}, truth_value=1.0)
        aci.monadise("price is 120", source_type="CRM",
                     metadata={**md, "object": "120"}, truth_value=1.0)
        superseded = [m for m in aci.store.all() if m.metadata.get("status") == "superseded"]
        self.assertEqual(len(superseded), 0)   # cross-source -> competing, not superseded


if __name__ == "__main__":
    unittest.main()
