"""
VectorIndex - incremental top-k semantic search.

Default: a numpy cosine index maintained INCREMENTALLY - add/remove are O(d) (no
full-matrix rebuild), so ingest is O(n) not O(n^2) and forget is O(1)-ish, not O(n).
Pure-Python fallback if numpy is absent.

Optional ANN: if `hnswlib` is installed (and ACI_INDEX != "bruteforce"), an approximate
backend gives O(log n) search for very large stores. Any ANN failure degrades to the
numpy path, so it is always safe.
"""
from __future__ import annotations
import os
from typing import List, Tuple

try:
    import numpy as np
    _NUMPY = True
except Exception:
    _NUMPY = False


class _HnswBackend:
    """Thin, defensive hnswlib wrapper. Lazily sized on the first vector."""
    def __init__(self):
        import hnswlib  # raises if absent
        self._hnswlib = hnswlib
        self.index = None
        self.dim = None
        self.cap = 0
        self.count = 0
        self.id_of = {}     # label -> id
        self.label_of = {}  # id -> label
        self._next = 0

    def _ensure(self, dim, need):
        if self.index is None:
            self.dim = dim
            self.cap = max(1024, need)
            self.index = self._hnswlib.Index(space="cosine", dim=dim)
            self.index.init_index(max_elements=self.cap, ef_construction=200, M=16)
            self.index.set_ef(64)
        elif self.count + need > self.cap:
            self.cap = max(self.cap * 2, self.count + need)
            self.index.resize_index(self.cap)

    def add(self, id_, vec):
        self._ensure(len(vec), 1)
        if id_ in self.label_of:                 # update
            label = self.label_of[id_]
        else:
            label = self._next
            self._next += 1
            self.label_of[id_] = label
            self.id_of[label] = id_
            self.count += 1
        self.index.add_items(np.asarray([vec], dtype=np.float32), [label])

    def remove(self, id_):
        label = self.label_of.pop(id_, None)
        if label is not None:
            self.id_of.pop(label, None)
            try:
                self.index.mark_deleted(label)
            except Exception:
                pass

    def search(self, query, k):
        if not self.label_of:
            return []
        k = min(k, len(self.label_of))
        labels, dists = self.index.knn_query(np.asarray([query], dtype=np.float32), k=k)
        out = []
        for lab, dist in zip(labels[0], dists[0]):
            cid = self.id_of.get(int(lab))
            if cid is not None:
                out.append((cid, float(1.0 - dist)))   # cosine sim = 1 - cosine distance
        return out


class _UsearchBackend:
    """Thin usearch wrapper — ships PREBUILT wheels (no C++ compiler needed), so it is a
    safe ANN default for a local-first product, unlike hnswlib which must be built."""
    def __init__(self):
        from usearch.index import Index   # raises if absent
        self._Index = Index
        self.index = None
        self.dim = None
        self.id_of = {}     # label -> id
        self.label_of = {}  # id -> label
        self._next = 0

    def _ensure(self, dim):
        if self.index is None:
            self.dim = dim
            self.index = self._Index(ndim=dim, metric="cos")

    def add(self, id_, vec):
        self._ensure(len(vec))
        if id_ in self.label_of:
            label = self.label_of[id_]
        else:
            label = self._next
            self._next += 1
            self.label_of[id_] = label
            self.id_of[label] = id_
        self.index.add(label, np.asarray(vec, dtype=np.float32))

    def remove(self, id_):
        label = self.label_of.pop(id_, None)
        if label is not None:
            self.id_of.pop(label, None)
            try:
                self.index.remove(label)
            except Exception:
                pass

    def search(self, query, k):
        if not self.label_of:
            return []
        k = min(k, len(self.label_of))
        m = self.index.search(np.asarray(query, dtype=np.float32), k)
        out = []
        for key, dist in zip(m.keys, m.distances):
            cid = self.id_of.get(int(key))
            if cid is not None:
                out.append((cid, float(1.0 - dist)))   # cosine sim = 1 - cosine distance
        return out


class VectorIndex:
    def __init__(self):
        self.ids: List[str] = []          # row -> id
        self.pos = {}                     # id -> row
        self.vecs: List[list] = []        # row -> vector — ONLY used when numpy is absent
        self._mat = None                  # numpy capacity buffer (source of truth w/ numpy)
        self._n = 0
        self._ann = None
        if _NUMPY and os.environ.get("ACI_INDEX", "auto") != "bruteforce":
            for _backend in (_UsearchBackend, _HnswBackend):   # prefer usearch (prebuilt wheels)
                try:
                    self._ann = _backend()
                    break
                except Exception:
                    self._ann = None

    def __len__(self):
        return self._n

    def add(self, id_: str, vec) -> None:
        if not vec:
            return
        if self._ann is not None:
            try:
                self._ann.add(id_, vec)
            except Exception:
                self._ann = None          # degrade permanently to numpy on any ANN error
        if id_ in self.pos:               # update in place
            row = self.pos[id_]
            if _NUMPY:
                if self._mat is not None and row < len(self._mat):
                    self._mat[row] = np.asarray(vec, dtype=np.float32)
            else:
                self.vecs[row] = list(vec)
            return
        row = self._n
        self.pos[id_] = row
        if row < len(self.ids):
            self.ids[row] = id_
        else:
            self.ids.append(id_)
        if _NUMPY:
            v = np.asarray(vec, dtype=np.float32)
            if self._mat is None or row >= len(self._mat):
                cap = max(1024, (len(self._mat) * 2) if self._mat is not None else 1024)
                newmat = np.zeros((cap, len(vec)), dtype=np.float32)
                if self._mat is not None:
                    newmat[:self._n] = self._mat[:self._n]
                self._mat = newmat
            self._mat[row] = v
        else:                             # no-numpy fallback keeps the python-list store
            if row < len(self.vecs):
                self.vecs[row] = list(vec)
            else:
                self.vecs.append(list(vec))
        self._n += 1

    def remove(self, id_: str) -> None:
        """O(d) swap-delete - no full rebuild."""
        if self._ann is not None:
            try:
                self._ann.remove(id_)
            except Exception:
                pass
        row = self.pos.pop(id_, None)
        if row is None:
            return
        last = self._n - 1
        if row != last:
            moved = self.ids[last]
            self.ids[row] = moved
            self.pos[moved] = row
            if _NUMPY:
                if self._mat is not None:
                    self._mat[row] = self._mat[last]
            else:
                self.vecs[row] = self.vecs[last]
        # shrink active region
        self.ids.pop()
        if not _NUMPY:
            self.vecs.pop()
        self._n -= 1

    def search(self, query, k: int = 10) -> List[Tuple[str, float]]:
        if self._n == 0:
            return []
        if self._ann is not None:
            try:
                res = self._ann.search(query, k)
                if res:
                    return res
            except Exception:
                self._ann = None
        if _NUMPY:
            q = np.asarray(query, dtype=np.float32)
            mat = self._mat[:self._n]
            denom = (np.linalg.norm(mat, axis=1) * np.linalg.norm(q)) + 1e-9
            sims = (mat @ q) / denom
            k = min(k, self._n)
            top = np.argpartition(-sims, k - 1)[:k]
            top = top[np.argsort(-sims[top])]
            return [(self.ids[int(i)], float(sims[int(i)])) for i in top]
        from .embeddings import cosine
        scored = [(self.ids[i], cosine(query, self.vecs[i])) for i in range(self._n)]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
