"""
Skill Memory (S0–S2) tests — declarative shared skill library on ACI.
Fast/deterministic: lexical embedder + :memory: store (and a temp file for cross-agent).
"""
import os
import tempfile
import unittest

os.environ.setdefault("ACI_EMBEDDER", "lexical")
os.environ.setdefault("UQRT_MCA_NLP_EXTRACTOR", "heuristic")

from aci.aci import ACI                          # noqa: E402
from aci import skills                           # noqa: E402
import aci.mcp_server as mcp                      # noqa: E402

ARB_BODY = ("Draft an arbitration notice: state the arbitration clause, the dispute, "
            "the relief sought, and a 30 day cure period.")
ARB_BODY_V2 = ARB_BODY + " Also nominate an arbitrator and the seat of arbitration."


class TestSkillCore(unittest.TestCase):
    def setUp(self):
        self.a = ACI(db_path=":memory:", observer_id="agent-A")

    def test_save_and_find(self):
        v = skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        self.assertEqual(v["name"], "arb_notice")
        self.assertIn("confidence", v)
        found = skills.find_skills(self.a, "draft arbitration notice")
        self.assertTrue(found, "skill should be discoverable by intent")
        self.assertEqual(found[0]["name"], "arb_notice")

    def test_find_excludes_non_skills(self):
        self.a.monadise("The arbitration hearing room is on the third floor.",
                        source_type="USER")
        skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        found = skills.find_skills(self.a, "arbitration notice")
        self.assertTrue(all(f["name"] for f in found))
        self.assertTrue(any(f["name"] == "arb_notice" for f in found))

    def test_outcome_success_raises_confidence(self):
        v = skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        before = v["confidence"]
        after = skills.skill_outcome(self.a, v["id"], success=True)
        self.assertGreater(after["confidence"], before)

    def test_outcome_failure_lowers_confidence(self):
        v = skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        before = v["confidence"]
        after = skills.skill_outcome(self.a, v["id"], success=False)
        self.assertLess(after["confidence"], before)

    def test_outcome_unknown_id(self):
        self.assertIsNone(skills.skill_outcome(self.a, "does-not-exist", success=True))

    def test_better_version_supersedes(self):
        skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY_V2)
        found = skills.find_skills(self.a, "draft arbitration notice")
        self.assertTrue(found)
        # the live (non-superseded) version is the v2 body (mentions the arbitrator/seat)
        self.assertIn("seat of arbitration", found[0]["body"])

    def test_reuse_corroborates(self):
        r1 = skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        r2 = skills.save_skill(self.a, "arb_notice", "draft an arbitration notice", ARB_BODY)
        self.assertGreater(r2["uses"], r1["uses"])          # repeated publish reinforces

    def test_cross_agent_shared_access(self):
        fd, dbf = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        aA = aB = None
        try:
            aA = ACI(db_path=dbf, observer_id="agent-A")
            skills.save_skill(aA, "contract_summary",
                              "summarize a contract into three bullets", ARB_BODY)
            aB = ACI(db_path=dbf, observer_id="agent-B")     # different agent, same store
            found = skills.find_skills(aB, "summarize a contract")
            self.assertTrue(any(f["name"] == "contract_summary" for f in found))
        finally:
            for inst in (aA, aB):                              # release sqlite handles (Windows)
                try:
                    inst.store.conn.close()
                except Exception:
                    pass
            try:
                os.remove(dbf)
            except OSError:
                pass                                          # temp file; harmless if it lingers


class TestSkillSelfCuration(unittest.TestCase):
    """S3 — the library curates itself: proven skills outrank failed ones, and every
    result carries provenance (author / confidence / uses)."""
    def setUp(self):
        self.a = ACI(db_path=":memory:", observer_id="agent-A")

    def test_proven_skill_outranks_failed_one(self):
        good = skills.save_skill(self.a, "filing_good", "format a court filing",
                                 "Court filing format guide: INDEX page, Times New Roman 14, 1.5 spacing.")
        bad = skills.save_skill(self.a, "filing_bad", "format a court filing",
                                "Court filing format notes: index, font, spacing, margins.")
        for _ in range(5):
            skills.skill_outcome(self.a, good["id"], success=True)    # this one works
        for _ in range(3):
            skills.skill_outcome(self.a, bad["id"], success=False)    # this one fails
        names = [f["name"] for f in skills.find_skills(self.a, "format a court filing", k=5)]
        self.assertIn("filing_good", names)
        self.assertIn("filing_bad", names)
        self.assertLess(names.index("filing_good"), names.index("filing_bad"),
                        "the proven skill must rank above the failed one")

    def test_provenance_surfaced(self):
        skills.save_skill(self.a, "thing_skill", "do a useful thing",
                          "Steps to do the useful thing properly and well.",
                          author="agent-Z", tags=["alpha"])
        found = skills.find_skills(self.a, "do a useful thing")
        self.assertTrue(found)
        s = found[0]
        for key in ("id", "author", "confidence", "uses"):
            self.assertIn(key, s)
        self.assertEqual(s["author"], "agent-Z")


class _StubClient:
    """Stands in for ACIClient so MCP dispatch is testable with no running service."""
    def save_skill(self, name, intent, body, tags=None, author=None):
        return {"id": "abc12345", "name": name, "confidence": 1.0}

    def find_skills(self, intent, k=5):
        return [{"id": "abc12345", "name": "arb_notice", "intent": "draft a notice",
                 "body": "steps", "confidence": 1.4, "uses": 3, "author": "agent-A"}]

    def skill_outcome(self, skill_id, success):
        return {"id": skill_id, "name": "arb_notice", "confidence": 1.5 if success else 0.6}


class TestSkillMCP(unittest.TestCase):
    def test_tools_listed(self):
        resp = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, None)
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertTrue({"aci_find_skills", "aci_save_skill", "aci_skill_outcome"} <= names)

    def _call(self, name, arguments):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}}, _StubClient())

    def test_dispatch_find(self):
        r = self._call("aci_find_skills", {"intent": "draft a notice"})
        text = r["result"]["content"][0]["text"]
        self.assertFalse(r["result"].get("isError"))
        self.assertIn("arb_notice", text)

    def test_dispatch_save(self):
        r = self._call("aci_save_skill",
                       {"name": "arb_notice", "intent": "draft a notice", "body": "steps"})
        self.assertFalse(r["result"].get("isError"))
        self.assertIn("arb_notice", r["result"]["content"][0]["text"])

    def test_dispatch_outcome(self):
        r = self._call("aci_skill_outcome", {"skill_id": "abc12345", "success": False})
        text = r["result"]["content"][0]["text"]
        self.assertFalse(r["result"].get("isError"))
        self.assertIn("downgraded", text)


if __name__ == "__main__":
    unittest.main()
