"""
Filesystem connector — incremental ingest of real documents into ACI.

Walks a real folder, monadises text / Word / PDF (chunked), and keeps a small
local sync-state so re-runs only process NEW or CHANGED files, re-ingest changed
ones cleanly (drop stale chunks first), and remove deleted files' monads.
No AI anywhere — just a data source.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.documents import SUPPORTED_EXT, load_text, chunk  # noqa: E402
from clients.connector import ACIClient  # noqa: E402


def _state_path(target: str) -> str:
    h = hashlib.md5(os.path.abspath(target).encode()).hexdigest()[:10]
    return os.path.join(os.path.dirname(__file__), f".sync_{h}.json")


def ingest_dir(client: ACIClient, path: str, full_resync: bool = False) -> dict:
    sf = _state_path(path)
    state = {}
    if os.path.exists(sf) and not full_resync:
        try:
            state = json.load(open(sf))
        except Exception:
            state = {}

    new = updated = skipped = chunks = 0
    seen = set()
    for root, _, files in os.walk(path):
        for f in files:
            if os.path.splitext(f)[1].lower() not in SUPPORTED_EXT:
                continue
            fp = os.path.abspath(os.path.join(root, f))
            seen.add(fp)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            fingerprint = f"{st.st_mtime_ns}:{st.st_size}"
            if state.get(fp) == fingerprint:          # unchanged
                skipped += 1
                continue
            text = load_text(fp)
            if not text.strip():
                continue
            if fp in state:                           # changed -> drop stale chunks
                try:
                    client.forget_by_source(fp)
                except Exception:
                    pass
                updated += 1
            else:
                new += 1
            for i, piece in enumerate(chunk(text)):
                client.monadise(piece, source_type="FILE",
                                metadata={"path": fp, "filename": f, "chunk": str(i)},
                                summary=f"{f}#{i}: {piece.strip()[:100]}")
                chunks += 1
            state[fp] = fingerprint

    for gone in [p for p in state if p not in seen]:  # deleted files
        try:
            client.forget_by_source(gone)
        except Exception:
            pass
        del state[gone]

    try:
        with open(sf, "w") as fh:
            json.dump(state, fh)
    except Exception:
        pass
    return {"files": new + updated, "new": new, "updated": updated,
            "skipped": skipped, "chunks": chunks}


if __name__ == "__main__":
    url = os.environ.get("ACI_URL", "http://127.0.0.1:7077")
    target = sys.argv[1] if len(sys.argv) > 1 else "sample_data"
    print(f"[filesystem] {ingest_dir(ACIClient(url), target)} from {target}")
