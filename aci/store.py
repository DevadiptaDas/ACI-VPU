"""
MonadStore - persistent monad storage (SQLite, stdlib).

Stores monads + their embeddings and relations. Recall ranks by a hybrid of
semantic similarity, truth, and recency. This is the persistent substrate that
gives ACI memory that survives restarts (unlike an LLM context window).
"""

from __future__ import annotations
import json
import os
import sqlite3
import time
from typing import List, Optional

from .monad import Monad
from .cryptobox import Cipher


class MonadStore:
    def __init__(self, db_path: str = ":memory:", check_same_thread: bool = True,
                 passphrase: Optional[str] = None):
        # check_same_thread=False lets the threaded server share one connection
        # (all access is serialized by a lock in the service layer).
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        try:                                       # crash-safety + concurrent reads
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        self._setup()
        # at-rest encryption: ACI_PASSPHRASE env, else the OS-keystore (DPAPI) key
        self.crypto: Optional[Cipher] = None
        if passphrase is None:
            passphrase = os.environ.get("ACI_PASSPHRASE")
        if passphrase is None:
            try:
                from .keystore import load_passphrase
                passphrase = load_passphrase()
            except Exception:
                passphrase = None
        if passphrase:
            self.crypto = Cipher(passphrase, self._get_or_make_salt())
            self._verify_passphrase()
        elif self.get_meta("enc_check") is not None:
            raise ValueError("ACI: this store is encrypted - set ACI_PASSPHRASE to open it.")

    # --- at-rest encryption helpers ---
    def _get_or_make_salt(self) -> bytes:
        s = self.get_meta("salt")
        if s:
            return bytes.fromhex(s)
        salt = os.urandom(16)
        self.set_meta("salt", salt.hex())
        return salt

    def _verify_passphrase(self) -> None:
        chk = self.get_meta("enc_check")
        if chk is None:
            self.set_meta("enc_check", self.crypto.enc("ACI-OK"))
            return
        try:
            ok = self.crypto.dec(chk) == "ACI-OK"
        except Exception:
            ok = False
        if not ok:
            raise ValueError("ACI: wrong ACI_PASSPHRASE for this encrypted store.")

    def _enc(self, s):
        return self.crypto.enc(s) if self.crypto else s

    def _dec(self, s):
        return self.crypto.dec(s) if self.crypto else s

    def _setup(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS monads (
                id TEXT PRIMARY KEY,
                source_type TEXT, summary TEXT, value TEXT,
                keywords TEXT, entities TEXT, links TEXT, metadata TEXT,
                truth_value REAL, entropy REAL, observer_id TEXT,
                spacetime TEXT, contextual_complexity REAL,
                object_weight REAL, concept_weight REAL,
                monad_weight REAL, event_weight REAL,
                temporal_past REAL, temporal_present REAL, temporal_future REAL,
                embedding TEXT, weight REAL,
                timestamp INTEGER, original_size INTEGER, monad_size INTEGER
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                source_id TEXT, target_id TEXT, relation_type TEXT, weight REAL
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                path TEXT PRIMARY KEY, fingerprint TEXT
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS watched (
                path TEXT PRIMARY KEY
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY, value TEXT
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS consent (
                scope TEXT PRIMARY KEY, allowed INTEGER, note TEXT, ts REAL
            )""")
        # memory compressor: lossless compressed originals (dedup by content hash)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS blobs (
                sha TEXT PRIMARY KEY, data BLOB, orig_size INTEGER, comp_size INTEGER
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                path TEXT PRIMARY KEY, sha TEXT, orig_size INTEGER,
                mtime_ns INTEGER, archived_at REAL
            )""")
        self.conn.commit()

    # --- serialization (content-bearing columns are encrypted when crypto is on) ---
    def _to_row(self, m: Monad) -> tuple:
        return (
            m.id, m.source_type, self._enc(m.summary), self._enc(m.value),
            self._enc(json.dumps(m.keywords)), self._enc(json.dumps(m.entities)),
            json.dumps(m.links), self._enc(json.dumps(m.metadata)),
            m.truth_value, m.entropy, m.observer_id,
            json.dumps(m.spacetime), m.contextual_complexity,
            m.object_weight, m.concept_weight, m.monad_weight, m.event_weight,
            m.temporal_past, m.temporal_present, m.temporal_future,
            json.dumps(m.embedding), m.weight,
            m.timestamp, m.original_size, m.monad_size,
        )

    def _from_row(self, r: sqlite3.Row) -> Monad:
        return Monad(
            id=r["id"], source_type=r["source_type"],
            summary=self._dec(r["summary"]), value=self._dec(r["value"]),
            keywords=json.loads(self._dec(r["keywords"])), entities=json.loads(self._dec(r["entities"])),
            links=json.loads(r["links"]), metadata=json.loads(self._dec(r["metadata"])),
            truth_value=r["truth_value"], entropy=r["entropy"], observer_id=r["observer_id"],
            spacetime=json.loads(r["spacetime"]), contextual_complexity=r["contextual_complexity"],
            object_weight=r["object_weight"], concept_weight=r["concept_weight"],
            monad_weight=r["monad_weight"], event_weight=r["event_weight"],
            temporal_past=r["temporal_past"], temporal_present=r["temporal_present"],
            temporal_future=r["temporal_future"], embedding=json.loads(r["embedding"]),
            weight=r["weight"], timestamp=r["timestamp"],
            original_size=r["original_size"], monad_size=r["monad_size"],
        )

    # --- ops ---
    def upsert(self, m: Monad) -> None:
        cols = ("id,source_type,summary,value,keywords,entities,links,metadata,"
                "truth_value,entropy,observer_id,spacetime,contextual_complexity,"
                "object_weight,concept_weight,monad_weight,event_weight,"
                "temporal_past,temporal_present,temporal_future,embedding,weight,"
                "timestamp,original_size,monad_size")
        ph = ",".join("?" * 25)
        self.conn.execute(f"INSERT OR REPLACE INTO monads ({cols}) VALUES ({ph})",
                          self._to_row(m))
        self.conn.commit()

    def get(self, monad_id: str) -> Optional[Monad]:
        r = self.conn.execute("SELECT * FROM monads WHERE id=?", (monad_id,)).fetchone()
        return self._from_row(r) if r else None

    def all(self) -> List[Monad]:
        return [self._from_row(r) for r in self.conn.execute("SELECT * FROM monads")]

    def recent(self, limit: int = 50, source_type: Optional[str] = None) -> List[Monad]:
        """Most-recent monads via a LIMIT query — does NOT load the whole store.
        Optionally filter by source_type at the SQL level (e.g. WORKLOG)."""
        if source_type:
            cur = self.conn.execute(
                "SELECT * FROM monads WHERE source_type=? ORDER BY rowid DESC LIMIT ?",
                (source_type, int(limit)))
        else:
            cur = self.conn.execute(
                "SELECT * FROM monads ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return [self._from_row(r) for r in cur]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM monads").fetchone()[0]

    def total_monad_bytes(self) -> int:
        r = self.conn.execute("SELECT COALESCE(SUM(monad_size),0) FROM monads").fetchone()
        return int(r[0])

    def delete(self, monad_id: str) -> None:
        self.conn.execute("DELETE FROM monads WHERE id=?", (monad_id,))
        self.conn.commit()

    # --- source sync-state (server-side incremental ingest) ---
    def get_source_fp(self, path: str):
        r = self.conn.execute("SELECT fingerprint FROM sources WHERE path=?", (path,)).fetchone()
        return r["fingerprint"] if r else None

    def set_source_fp(self, path: str, fingerprint: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO sources VALUES (?,?)", (path, fingerprint))
        self.conn.commit()

    def all_source_paths(self):
        return [r["path"] for r in self.conn.execute("SELECT path FROM sources")]

    def del_source(self, path: str) -> None:
        self.conn.execute("DELETE FROM sources WHERE path=?", (path,))
        self.conn.commit()

    # --- watched folders (autonomous background ingest) ---
    def add_watched(self, path: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO watched VALUES (?)", (path,))
        self.conn.commit()

    def remove_watched(self, path: str) -> None:
        self.conn.execute("DELETE FROM watched WHERE path=?", (path,))
        self.conn.commit()

    def all_watched(self):
        return [r["path"] for r in self.conn.execute("SELECT path FROM watched")]

    def monad_ids_by_path(self, path: str):
        """Monad ids whose metadata.path matches (for re-ingesting a changed file)."""
        if self.crypto is None:                 # metadata is plaintext -> fast SQL path
            try:
                rows = self.conn.execute(
                    "SELECT id FROM monads WHERE json_extract(metadata,'$.path')=?", (path,))
                return [r["id"] for r in rows]
            except Exception:                   # JSON1 unavailable -> scan fallback
                pass
        return [m.id for m in self.all() if m.metadata.get("path") == path]

    def monad_ids_by_fact_key(self, fact_key: str):
        """Monad ids whose metadata.fact_key matches — fast JSON-indexed query so
        assert_fact doesn't scan the whole store to find prior fact versions."""
        if self.crypto is None:
            try:
                rows = self.conn.execute(
                    "SELECT id FROM monads WHERE json_extract(metadata,'$.fact_key')=?",
                    (fact_key,))
                return [r["id"] for r in rows]
            except Exception:
                pass
        return [m.id for m in self.all() if (m.metadata or {}).get("fact_key") == fact_key]

    def all_relations(self):
        return [(r["source_id"], r["target_id"], r["relation_type"], r["weight"])
                for r in self.conn.execute("SELECT * FROM relations")]

    def add_relation(self, source_id: str, target_id: str,
                     relation_type: str = "ASSOCIATIVE", weight: float = 1.0) -> None:
        self.conn.execute(
            "INSERT INTO relations VALUES (?,?,?,?)",
            (source_id, target_id, relation_type, weight))
        self.conn.commit()

    # --- meta key/value (salt, enc-check, paused flag) ---
    def get_meta(self, key: str):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.conn.commit()

    # --- control: global pause (stops all autonomous capture, leaves serve up) ---
    def is_paused(self) -> bool:
        return self.get_meta("paused") == "1"

    def set_paused(self, paused: bool) -> None:
        self.set_meta("paused", "1" if paused else "0")

    # --- consent ledger: per kind (FILE/WEB/AI/...) or per specific source ---
    def consent_set(self, scope: str, allowed: bool, note: str = "") -> None:
        self.conn.execute("INSERT OR REPLACE INTO consent VALUES (?,?,?,?)",
                          (scope, 1 if allowed else 0, note, time.time()))
        self.conn.commit()

    def consent_get(self, scope: str):
        r = self.conn.execute("SELECT allowed FROM consent WHERE scope=?", (scope,)).fetchone()
        return None if r is None else bool(r["allowed"])

    def consent_all(self):
        return [{"scope": r["scope"], "allowed": bool(r["allowed"]), "note": r["note"]}
                for r in self.conn.execute("SELECT scope,allowed,note FROM consent ORDER BY scope")]

    def is_allowed(self, kind: str, source: Optional[str] = None) -> bool:
        """Capture decision: blocked if paused; a specific-source rule beats a
        kind rule; default is allow (capture is opt-out per the always-on vision)."""
        if self.is_paused():
            return False
        if source is not None:
            c = self.consent_get(source)
            if c is not None:
                return c
        c = self.consent_get(kind)
        if c is not None:
            return c
        return True

    # --- memory compressor: blobs (dedup by sha) + per-path archive index ---
    def has_blob(self, sha: str) -> bool:
        return self.conn.execute("SELECT 1 FROM blobs WHERE sha=?", (sha,)).fetchone() is not None

    def put_blob(self, sha: str, comp: bytes, orig_size: int, comp_size: int) -> None:
        data = self.crypto.enc_bytes(comp) if self.crypto else comp
        self.conn.execute("INSERT OR IGNORE INTO blobs VALUES (?,?,?,?)",
                          (sha, data, orig_size, comp_size))
        self.conn.commit()

    def get_blob(self, sha: str):
        r = self.conn.execute("SELECT data FROM blobs WHERE sha=?", (sha,)).fetchone()
        if not r:
            return None
        data = r["data"]
        return self.crypto.dec_bytes(data) if self.crypto else data

    def set_archive(self, path: str, sha: str, orig_size: int, mtime_ns: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO archive VALUES (?,?,?,?,?)",
                          (path, sha, orig_size, mtime_ns, time.time()))
        self.conn.commit()

    def get_archive(self, path: str):
        r = self.conn.execute("SELECT path,sha,orig_size,mtime_ns,archived_at "
                              "FROM archive WHERE path=?", (path,)).fetchone()
        return dict(r) if r else None

    def all_archives(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT path,sha,orig_size,mtime_ns,archived_at FROM archive ORDER BY archived_at DESC")]

    def del_archive(self, path: str) -> None:
        r = self.conn.execute("SELECT sha FROM archive WHERE path=?", (path,)).fetchone()
        self.conn.execute("DELETE FROM archive WHERE path=?", (path,))
        if r and self.conn.execute("SELECT 1 FROM archive WHERE sha=? LIMIT 1",
                                   (r["sha"],)).fetchone() is None:
            self.conn.execute("DELETE FROM blobs WHERE sha=?", (r["sha"],))  # GC orphan blob
        self.conn.commit()

    def archive_totals(self) -> dict:
        files = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(orig_size),0) FROM archive").fetchone()
        blobs = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(comp_size),0) FROM blobs").fetchone()
        return {"files": files[0], "logical_bytes": int(files[1]),
                "unique_blobs": blobs[0], "stored_bytes": int(blobs[1])}

    # --- hardening: integrity / backup / wipe / compaction (Phase 3) ---
    def _db_bytes(self) -> int:
        try:
            return os.path.getsize(self.db_path) if self.db_path != ":memory:" else 0
        except OSError:
            return 0

    def integrity_check(self) -> str:
        r = self.conn.execute("PRAGMA integrity_check").fetchone()
        return r[0] if r else "unknown"

    def backup(self, path: str) -> dict:
        dest = sqlite3.connect(path)
        try:
            with dest:
                self.conn.backup(dest)
        finally:
            dest.close()
        return {"backup": os.path.abspath(path), "bytes": os.path.getsize(path)}

    def wipe(self) -> dict:
        """Delete ALL stored data (monads, relations, sources, archive, consent),
        keep config (salt/enc-check/paused). Right-to-be-forgotten / uninstall hygiene."""
        n = self.count()
        for t in ("monads", "relations", "sources", "watched", "consent", "blobs", "archive"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
        self.conn.execute("VACUUM")
        return {"wiped_monads": n}

    def compact(self, purge_superseded: bool = False, older_than_days=None) -> dict:
        """Reclaim space: optionally purge superseded and/or old monads, then VACUUM.
        Scan-based so it works whether or not the store is encrypted."""
        before = self._db_bytes()
        to_del = []
        cutoff = (int((time.time() - older_than_days * 86400) * 1000)
                  if older_than_days is not None else None)
        if purge_superseded or cutoff is not None:
            for m in self.all():
                if purge_superseded and m.metadata.get("status") == "superseded":
                    to_del.append(m.id)
                elif cutoff is not None and m.timestamp < cutoff:
                    to_del.append(m.id)
        for mid in to_del:
            self.conn.execute("DELETE FROM monads WHERE id=?", (mid,))
            self.conn.execute("DELETE FROM relations WHERE source_id=? OR target_id=?", (mid, mid))
        self.conn.commit()
        self.conn.execute("VACUUM")
        return {"removed": len(to_del), "bytes_before": before, "bytes_after": self._db_bytes()}

    def close(self) -> None:
        self.conn.close()
