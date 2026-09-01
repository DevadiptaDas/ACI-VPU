"""
Server-side incremental directory ingest — operates directly on an ACI instance.

Sync-state lives in the store's `sources` table (travels with the DB), so the
Console can re-ingest a folder and only new/changed files are processed; changed
files are re-ingested cleanly; deleted files (under the same folder) are removed.
Self-contained: no AI, no network.
"""
from __future__ import annotations
import hashlib
import os

from .documents import SUPPORTED_EXT, IMAGE_EXT, load_text, chunk
from .embeddings import embed_many

WEB_MIN_CHARS = 200
MAX_TEXT_BYTES = 8 * 1024 * 1024        # skip huge files (a 500 MB log isn't "a document")

# Directories that are never the user's content — pruned so a whole-drive / whole-home
# watch stays fast and doesn't pollute recall with app caches, build junk, or system files.
_EXCLUDE_DIRS = {
    "appdata", "node_modules", ".git", ".svn", ".hg", "$recycle.bin", "recycle.bin",
    "system volume information", "windows", "winsxs", "program files", "program files (x86)",
    "programdata", "__pycache__", ".venv", "venv", "env", ".env", ".cache", "cache", "caches",
    ".npm", ".gradle", ".m2", ".cargo", ".conda", "anaconda3", "miniconda3", "site-packages",
    "temp", "tmp", ".tmp", ".next", ".nuxt", "dist", "build", "obj", "bin", "target",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "onedrivetemp", "microsoft", "packages",
}


def ingest_directory(aci, path: str, full_resync: bool = False, lock=None) -> dict:
    """Incrementally ingest a folder. When `lock` is given (the service's global
    lock, used by the background watcher), the SLOW per-file embedding runs OUTSIDE
    the lock and only the brief store writes are held under it — so foreground
    queries (recall/validate) interleave instead of blocking for the whole folder.
    NOTE: the caller must NOT already hold `lock` (threading.Lock isn't reentrant)."""
    import contextlib
    base = os.path.abspath(path)
    store = aci.store
    new = updated = skipped = chunks = 0
    seen = set()

    def held():
        return lock if lock is not None else contextlib.nullcontext()

    for root, dirs, files in os.walk(base):
        # prune junk/system/hidden dirs IN PLACE so os.walk never descends into them
        dirs[:] = [d for d in dirs if d.lower() not in _EXCLUDE_DIRS and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in SUPPORTED_EXT and ext not in IMAGE_EXT:
                continue
            fp = os.path.abspath(os.path.join(root, f))
            seen.add(fp)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            if ext in SUPPORTED_EXT and st.st_size > MAX_TEXT_BYTES:   # skip oversized text/logs
                skipped += 1
                continue
            fingerprint = f"{st.st_mtime_ns}:{st.st_size}"
            if not full_resync and store.get_source_fp(fp) == fingerprint:
                skipped += 1
                continue
            if ext in IMAGE_EXT:                       # multimodal: CLIP-embed the photo
                with held():
                    r = aci.ingest_image(fp)
                    if r.get("id"):
                        new += (store.get_source_fp(fp) is None)
                        store.set_source_fp(fp, fingerprint)
                        chunks += 1
                continue
            text = load_text(fp)                       # I/O - outside the lock
            if not text.strip():
                continue
            pieces = chunk(text)                       # CPU - outside the lock
            embs = embed_many(aci.embedder, pieces)    # SLOW embed - OUTSIDE the lock
            with held():                               # brief: only the store writes
                if store.get_source_fp(fp) is not None:    # changed -> drop stale chunks
                    aci.forget_by_source(fp)
                    updated += 1
                else:
                    new += 1
                for i, piece in enumerate(pieces):
                    aci.monadise(piece, source_type="FILE",
                                 metadata={"path": fp, "filename": f, "chunk": str(i)},
                                 summary=f"{f}#{i}: {piece.strip()[:100]}",
                                 embedding=embs[i])
                    chunks += 1
                store.set_source_fp(fp, fingerprint)

    # remove monads for files under this folder that no longer exist.
    # NOTE: match on `base + os.sep` (or base itself), never a bare prefix — a bare
    # `startswith(base)` also matches SIBLING folders that share a name prefix
    # (re-ingesting "Notes" would delete every monad under "Notes_backup"). DATA LOSS.
    prefix = base + os.sep
    with held():
        for gone in [p for p in store.all_source_paths()
                     if (p == base or p.startswith(prefix)) and p not in seen]:
            aci.forget_by_source(gone)
            store.del_source(gone)

    return {"files": new + updated, "new": new, "updated": updated,
            "skipped": skipped, "chunks": chunks}


def ingest_web(aci, url: str, title: str = "", text: str = "",
               full_resync: bool = False) -> dict:
    """Ingest one web page (URL-keyed, content-fingerprinted) into ACI.

    Used by the browser extension's /capture. Revisiting an unchanged page is a
    no-op; a changed page cleanly supersedes its old chunks. Stays on-device.
    """
    url = (url or "").strip()
    text = (text or "").strip()
    if not url or len(text) < WEB_MIN_CHARS:
        return {"skipped": "too-short", "url": url, "chunks": 0}
    store = aci.store
    fingerprint = "web:" + hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]
    prev = store.get_source_fp(url)
    if not full_resync and prev == fingerprint:
        return {"skipped": "unchanged", "url": url, "chunks": 0}
    if prev is not None:
        aci.forget_by_source(url)
        status = "updated"
    else:
        status = "new"
    label = (title or url)[:80]
    n = 0
    pieces = chunk(text)
    embs = embed_many(aci.embedder, pieces)
    for i, piece in enumerate(pieces):
        aci.monadise(piece, source_type="WEB",
                     metadata={"path": url, "title": title, "kind": "web", "chunk": str(i)},
                     summary=f"{label}#{i}: {piece.strip()[:100]}",
                     embedding=embs[i])
        n += 1
    store.set_source_fp(url, fingerprint)
    return {"url": url, "title": title, "status": status, "chunks": n}
