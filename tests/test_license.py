"""Tier + 3-AI connection cap."""
import unittest
from aci.license import resolve_tier, cap_for, ConnectionGate


class TestTier(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(resolve_tier(""), "free")
        self.assertEqual(resolve_tier("free"), "free")
        self.assertEqual(resolve_tier("PRO-abc123"), "pro")
        self.assertEqual(resolve_tier("team-5-seat"), "team")
        self.assertEqual(resolve_tier("some-issued-key"), "pro")

    def test_cap(self):
        self.assertEqual(cap_for("free"), 3)
        self.assertIsNone(cap_for("pro"))
        self.assertIsNone(cap_for("team"))


class TestGate(unittest.TestCase):
    def test_free_caps_at_three_distinct_ais(self):
        g = ConnectionGate("free")
        for a in ["Claude", "GPT", "Cursor"]:
            self.assertTrue(g.check(a)["allowed"])
        r = g.check("Gemini")                      # the 4th distinct AI
        self.assertFalse(r["allowed"])
        self.assertIn("upgrade", r)

    def test_known_ai_always_allowed(self):
        g = ConnectionGate("free", known=["claude", "gpt", "cursor"])
        self.assertTrue(g.check("Claude")["allowed"])     # already connected -> fine, not re-counted
        self.assertFalse(g.check("new-ai")["allowed"])    # a 4th NEW one -> capped

    def test_unidentified_caller_never_capped(self):
        g = ConnectionGate("free", known=["a", "b", "c"])
        r = g.check(None)                          # user's own device / console / SDK
        self.assertTrue(r["allowed"])
        self.assertFalse(r["counted"])

    def test_pro_is_unlimited(self):
        g = ConnectionGate("pro")
        for i in range(10):
            self.assertTrue(g.check(f"ai-{i}")["allowed"])


if __name__ == "__main__":
    unittest.main()
