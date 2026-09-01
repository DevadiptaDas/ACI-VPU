"""
Memory Compressor - delete-safe, compressed file archive + semantic index.

Each file is stored TWO ways:
  * lossless: LZMA-compressed original bytes (dedup by SHA-256, encrypted at rest
    if a passphrase is set) -> you can DELETE the original and `restore` it
    byte-for-byte later.
  * semantic: monadised text (via the normal ingest path) -> searchable by meaning,
    survives even after the file is gone.

Honest scope: the lossless side is what reconstructs the file (monads alone are
lossy - they keep meaning, not exact bytes). The win is storage: LZMA + dedup
shrink the archive well below the originals, which then become deletable.
"""
from __future__ import annotations
import hashlib
import lzma
import os

from .ingest import ingest_directory
from .documents import load_text, chunk, SUPPORTED_EXT

MAX_ARCHIVE_BYTES = int(os.environ.get("ACI_ARCHIVE_MAX", str(100 * 1024 * 1024)))


def _archive_blob(aci, fp: str) -> dict:
    """Store the lossless compressed bytes of one file (dedup by content hash)."""
    st = os.stat(fp)
    if st.st_size > MAX_ARCHIVE_BYTES:
        return {"skipped": "too-large", "size": st.st_size}
    with open(fp, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    store = aci.store
    new_blob = False
    if not store.has_blob(sha):
        comp = lzma.compress(data, preset=6)
        store.put_blob(sha, comp, len(data), len(comp))
        new_blob = True
    store.set_archive(fp, sha, st.st_size, st.st_mtime_ns)
    return {"sha": sha, "orig_size": st.st_size, "new_blob": new_blob}


def archive_file(aci, path: str, monadise: bool = True) -> dict:
    fp = os.path.abspath(path)
    if not os.path.isfile(fp):
        return {"error": "not a file", "path": fp}
    r = _archive_blob(aci, fp)
    r["path"] = fp
    if monadise and os.path.splitext(fp)[1].lower() in SUPPORTED_EXT:
        text = load_text(fp)
        if text.strip():
            n = 0
            for i, piece in enumerate(chunk(text)):
                aci.monadise(piece, source_type="FILE",
                             metadata={"path": fp, "filename": os.path.basename(fp), "chunk": str(i)},
                             summary=f"{os.path.basename(fp)}#{i}: {piece.strip()[:100]}")
                n += 1
            aci.store.set_source_fp(fp, f"{os.stat(fp).st_mtime_ns}:{os.stat(fp).st_size}")
            r["chunks"] = n
    return r


def archive_directory(aci, path: str) -> dict:
    """Archive every file under `path` (lossless blobs) + monadise the readable ones."""
    base = os.path.abspath(path)
    files = new_blobs = logical = skipped = 0
    for root, _, names in os.walk(base):
        for f in names:
            fp = os.path.join(root, f)
            try:
                b = _archive_blob(aci, fp)
            except OSError:
                continue
            if b.get("skipped"):
                skipped += 1
                continue
            files += 1
            logical += b["orig_size"]
            if b["new_blob"]:
                new_blobs += 1
    ing = ingest_directory(aci, base)          # cognition layer (semantic index)
    tot = aci.store.archive_totals()
    saved = tot["logical_bytes"] - tot["stored_bytes"]
    ratio = round(tot["logical_bytes"] / tot["stored_bytes"], 2) if tot["stored_bytes"] else 0
    return {"archived_path": base, "files_archived": files, "new_blobs": new_blobs,
            "skipped_large": skipped, "monad_chunks": ing.get("chunks", 0),
            "logical_bytes": tot["logical_bytes"], "stored_bytes": tot["stored_bytes"],
            "saved_bytes": saved, "compression_ratio": ratio}


def restore_file(aci, path: str, dest: str = None) -> dict:
    """Reconstruct an archived file byte-for-byte (verifies SHA-256)."""
    fp = os.path.abspath(path)
    rec = aci.store.get_archive(fp)
    if not rec:
        return {"error": "not in archive", "path": fp}
    comp = aci.store.get_blob(rec["sha"])
    if comp is None:
        return {"error": "blob missing", "path": fp}
    data = lzma.decompress(comp)
    if hashlib.sha256(data).hexdigest() != rec["sha"]:
        return {"error": "integrity check FAILED", "path": fp}
    out = os.path.abspath(dest) if dest else fp
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    return {"restored": out, "bytes": len(data), "verified": True}


def archive_stats(aci) -> dict:
    tot = aci.store.archive_totals()
    saved = tot["logical_bytes"] - tot["stored_bytes"]
    tot["saved_bytes"] = saved
    tot["compression_ratio"] = (round(tot["logical_bytes"] / tot["stored_bytes"], 2)
                                if tot["stored_bytes"] else 0)
    tot["archives"] = aci.store.all_archives()
    return tot
