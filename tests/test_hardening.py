"""test_hardening - Phase 3: integrity, backup, compact (purge), wipe."""
import os
os.environ.setdefault("ACI_EMBEDDER", "lexical")
os.environ.setdefault("ACI_EXTRACTOR", "heuristic")

import tempfile
import unittest

from aci.aci import ACI


def _seed(a):
    md = {"subject": "x", "predicate": "is"}
    a.monadise("x is one", metadata={**md, "object": "one"})
    a.monadise("x is two", metadata={**md, "object": "two"})   # supersedes 'one'


class TestHardening(unittest.TestCase):
    def test_integrity_ok(self):
        a = ACI(":memory:")
        _seed(a)
        self.assertEqual(a.integrity()["integrity"], "ok")

    def test_compact_purges_superseded_and_recall_survives(self):
        a = ACI(":memory:")
        _seed(a)
        self.assertEqual(a.store.count(), 2)
        out = a.compact(purge_superseded=True)
        self.assertEqual(out["removed"], 1)
        self.assertEqual(a.store.count(), 1)
        self.assertTrue(a.recall("x", k=3))          # index rebuilt, recall still works

    def test_wipe_clears_all(self):
        a = ACI(":memory:")
        _seed(a)
        a.wipe()
        self.assertEqual(a.store.count(), 0)
        self.assertEqual(a.recall("x", k=3), [])

    def test_backup_roundtrip(self):
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "s.db"), os.path.join(d, "b.db")
        a = ACI(src)
        _seed(a)
        a.backup(dst)
        a.store.close()
        b = ACI(dst)                                 # reopen the backup
        self.assertGreaterEqual(b.store.count(), 1)
        b.store.close()


if __name__ == "__main__":
    unittest.main()
