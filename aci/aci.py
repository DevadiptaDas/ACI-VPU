"""
ACI facade - the universal cognition primitives.

These are the "syscalls" any consumer (file system, OS, app, sensor, AI) calls:
    monadise   - turn raw information into a structured monad (+ dedup, compress)
    recall     - retrieve by meaning (semantic + truth + recency)
    relate     - link monads in the meaning field
    validate   - check a statement against memory (contradiction + confidence + trace)
    compress   - storage/compression stats (the optimization payoff of monadising)
    route      - decide where work/data goes (local now; mesh later)

Cognition and optimization are NOT separate systems here: optimisation
(dedup + compression) falls out of the single monadise operation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import math
import os
import time

from .monad import Monad
from .store import MonadStore
from .meaning_field import MeaningField
from .embeddings import get_default, cosine
from .extract import get_extractor
from . import signing
from .index import VectorIndex
from . import logic_gates as gates
from . import truth as truthmod
from . import tense as tensemod

_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "at", "for", "with", "my", "your", "i", "you", "it", "this",
    "that", "as", "by", "from", "me", "we", "our", "do", "did", "will",
}


@dataclass
class RecallHit:
    monad: Monad
    score: float
    similarity: float
    recency: float

    def __repr__(self) -> str:
        return (f"RecallHit(score={self.score:.3f}, sim={self.similarity:.3f}, "
                f"'{self.monad.summary[:60]}')")


@dataclass
class ValidationResult:
    statement: str
    is_consistent: bool
    confidence: float
    entropy: float
    contradictions: List[dict] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)
    # Unambiguous conflict signalling so a consumer never sees is_consistent=true
    # sitting next to a listed contradiction without knowing why. verdict is one of:
    #   "consistent"          — no conflict found at all
    #   "undermined"          — conflicts with an EQUAL/HIGHER-truth stored claim (your statement is suspect)
    #   "conflict_lower_truth"— conflicts only with a LOWER-truth stored claim (the OTHER claim is suspect)
    has_contradiction: bool = False
    verdict: str = "consistent"

    def explain(self) -> str:
        _v = {"consistent": "CONSISTENT", "undermined": "CONTRADICTION FOUND (statement undermined)",
              "conflict_lower_truth": "CONFLICT FOUND (with a lower-truth claim — the stored claim is suspect)"}
        lines = [f"Statement: {self.statement}",
                 f"Verdict:   {_v.get(self.verdict, 'CONSISTENT')}",
                 f"Confidence: {self.confidence:.2f}   Entropy: {self.entropy:.2f}"]
        if self.contradictions:
            lines.append("Contradictions:")
            lines += [f"  - {c['explanation']}" for c in self.contradictions]
        if self.trace:
            lines.append("Reasoning trace:")
            lines += [f"  {t}" for t in self.trace]
        return "\n".join(lines)


class ACI:
    def __init__(self, db_path: str = ":memory:", observer_id: str = "observer-0",
                 embedder=None, dedup_threshold: float = 0.93,
                 check_same_thread: bool = True, extractor=None,
                 resolve_contradictions: bool = False,
                 entropy_admission: bool = False):
        self.store = MonadStore(db_path, check_same_thread=check_same_thread)
        self.field = MeaningField()
        self._embedder = embedder        # lazy-loaded on first use (instant startup)
        self._extractor = extractor      # lazy-loaded on first use
        self.index = VectorIndex()
        self.image_index = VectorIndex()     # CLIP space (images) - separate from text
        self._clip = None
        self._clip_tried = False
        self.observer_id = observer_id
        self.dedup_threshold = dedup_threshold
        # OPT-IN (default OFF): soft, evidence-driven resolution of CROSS-source competing
        # claims via the UQRT-MCA algebra (validated in bench_contradiction_resolution.py
        # + bench_resolution_robustness.py). OFF until proven on the real store — a misfire
        # would mutate truth_values, so it must never touch a production DB unvetted.
        self.resolve_contradictions = resolve_contradictions
        # OPT-IN (default OFF): anti-rot. Input that contradicts established HIGHER-truth
        # knowledge is admitted on probation — discounted ψ + raised entropy — so a
        # confident lie can't enter strong and pollute the field. Genuine revisions start
        # weak too but earn truth via corroboration (Phase 1). Default off until vetted.
        self.entropy_admission = entropy_admission
        self._dedup_bytes_saved = 0
        self._dedup_count = 0
        self._infer_total = 0
        self._infer_hits = 0
        self._rehydrate()

    def _rehydrate(self) -> None:
        """(Re)build the in-memory graph + vector index from the store on disk.
        Used at startup and after wipe/compact."""
        from .meaning_field import MeaningField
        from .index import VectorIndex
        self.field = MeaningField()
        self.index = VectorIndex()
        self.image_index = VectorIndex()
        self._fact_index = {}                 # "context::subject::predicate" -> set(monad_id)
        self._context_index = {}              # context -> set(monad_id)  (bounded truth-contexts)
        for m in self.store.all():
            self.field.add(m)
            if m.embedding:
                (self.image_index if m.source_type == "IMAGE" else self.index).add(m.id, m.embedding)
            self._fact_register(m)
            self._context_register(m)
        for s, t, typ, w in self.store.all_relations():
            self.field.relate(s, t, typ, w)

    @staticmethod
    def _context_of(metadata) -> str:
        """The bounded truth-context a monad belongs to ('' = the global/default context)."""
        return (metadata.get("context") or "").strip().lower()

    @staticmethod
    def _fact_key(metadata) -> Optional[str]:
        subj, pred = metadata.get("subject"), metadata.get("predicate")
        if not (subj and pred):
            return None
        # Context is part of the key, so the SAME fact in different contexts (e.g. two
        # client matters) never collides — contradiction/supersession become per-context.
        ctx = (metadata.get("context") or "").strip().lower()
        return f"{ctx}::{subj.strip().lower()}::{pred.strip().lower()}"

    def _fact_register(self, m: Monad) -> None:
        if m.metadata.get("status") == "superseded":
            return
        key = self._fact_key(m.metadata)
        if key:
            self._fact_index.setdefault(key, set()).add(m.id)

    def _fact_unregister(self, monad_id: str, metadata) -> None:
        key = self._fact_key(metadata)
        if key and key in self._fact_index:
            self._fact_index[key].discard(monad_id)
            if not self._fact_index[key]:
                del self._fact_index[key]

    def _context_register(self, m: Monad) -> None:
        self._context_index.setdefault(self._context_of(m.metadata), set()).add(m.id)

    # ---------- hardening ops (Phase 3) ----------
    def integrity(self) -> dict:
        return {"integrity": self.store.integrity_check()}

    def backup(self, path: str) -> dict:
        return self.store.backup(path)

    def wipe(self) -> dict:
        out = self.store.wipe()
        self._rehydrate()
        return out

    def compact(self, purge_superseded: bool = False, older_than_days=None) -> dict:
        out = self.store.compact(purge_superseded, older_than_days)
        self._rehydrate()
        return out

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_default()       # loads the model on first real use
        return self._embedder

    @property
    def extractor(self):
        if self._extractor is None:
            self._extractor = get_extractor()
        return self._extractor

    @property
    def clip(self):
        """Lazy CLIP image/text embedder (None if Pillow/CLIP unavailable)."""
        if self._clip is None and not self._clip_tried:
            self._clip_tried = True
            from .imageembed import get_clip
            self._clip = get_clip()
        return self._clip

    # ---------- multimodal: semantic image search (CLIP) ----------
    def ingest_image(self, path: str) -> dict:
        if self.clip is None:
            return {"skipped": "no-clip-backend (pip install pillow)", "path": path}
        emb = self.clip.embed_image(path)
        if not emb:
            return {"skipped": "unreadable", "path": path}
        import time as _t
        m = Monad(source_type="IMAGE", summary=os.path.basename(path), value=path,
                  metadata={"path": path, "kind": "image", "filename": os.path.basename(path)},
                  embedding=emb, timestamp=int(_t.time() * 1000),
                  original_size=(os.path.getsize(path) if os.path.exists(path) else 0))
        self.store.upsert(m)
        self.image_index.add(m.id, emb)
        return {"image": path, "id": m.id}

    def recall_images(self, query: str, k: int = 8):
        """Text query -> matching images (CLIP shared space)."""
        if self.clip is None:
            return []
        q = self.clip.embed_text(query)
        out = []
        for cid, sim in self.image_index.search(q, k):
            m = self.store.get(cid)
            if m is not None:
                out.append((m, sim))
        return out

    # ---------- helpers ----------
    def _keywords(self, text: str) -> List[str]:
        from .embeddings import tokenize
        freq: Dict[str, int] = {}
        for t in tokenize(text):
            if t not in _STOP:
                freq[t] = freq.get(t, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])][:12]

    def _entropy(self, text: str) -> float:
        from .embeddings import tokenize
        toks = tokenize(text)
        if not toks:
            return 0.5
        freq: Dict[str, int] = {}
        for t in toks:
            freq[t] = freq.get(t, 0) + 1
        n = len(toks)
        h = -sum((c / n) * math.log2(c / n) for c in freq.values())
        hmax = math.log2(len(freq)) if len(freq) > 1 else 1.0
        return round(h / hmax, 4) if hmax > 0 else 0.0

    @staticmethod
    def _semantic_bytes(summary: str, value: str, keywords, metadata) -> int:
        return len((summary + value + " ".join(keywords) +
                    json.dumps(metadata)).encode("utf-8"))

    # ---------- PRIMITIVE 1: monadise ----------
    def monadise(self, content: str, source_type: str = "DERIVED",
                 observer_id: Optional[str] = None,
                 metadata: Optional[Dict[str, str]] = None,
                 truth_value: float = 1.0, summary: Optional[str] = None,
                 dedup: bool = True, embedding: Optional[List[float]] = None,
                 context: Optional[str] = None) -> Monad:
        observer_id = observer_id or self.observer_id
        metadata = dict(metadata or {})
        if context is not None:                # bounded truth-context (project / matter / session)
            metadata["context"] = context
        # Auto-extract subject/predicate/object from RAW text if not provided,
        # so contradiction/supersession work with no manual tagging.
        entities: List[str] = []
        if not (metadata.get("subject") and metadata.get("predicate")):
            tri = self.extractor.extract(content)
            entities = tri.get("entities", [])
            if tri.get("subject") and tri.get("predicate"):
                metadata.setdefault("subject", tri["subject"])
                metadata.setdefault("predicate", tri["predicate"])
                if tri.get("object"):
                    metadata.setdefault("object", tri["object"])
        summary = summary or (content[:240])
        emb = embedding if embedding is not None else self.embedder.embed(content)
        keywords = self._keywords(content)
        entropy = self._entropy(content)
        original_size = len(content.encode("utf-8"))
        monad_size = self._semantic_bytes(summary, content, keywords, metadata)

        # 3D-time is a real dimension: a past-oriented and a future-oriented statement about
        # the same topic are DIFFERENT facts in time, not duplicates — don't let dedup merge
        # them (this is the "dedup eats temporal updates" fix).
        new_past, new_present, new_future = tensemod.content_tense_weights(content)
        new_tense = ("future" if new_future >= new_past and new_future >= new_present
                     else "past" if new_past >= new_present else "present")
        if dedup:
            dup = self._find_duplicate(emb, observer_id, metadata)
            if (dup is not None and tensemod.dominant(dup) == new_tense
                    and self._context_of(dup.metadata) == self._context_of(metadata)):
                # Merge: repeated evidence reinforces, does not re-store. (Same context only —
                # an identical fact in a different matter is a separate fact.)
                dup.weight += 1.0
                reinforce = 0.1 * truth_value
                if self.entropy_admission and self._contradicted_by_truth(dup) > 0:
                    reinforce *= self._ADMIT_DISCOUNT   # anti-rot: a contradicted claim gains little
                dup.truth_value = min(dup.truth_value + reinforce, 50.0)
                dup.entropy = max(dup.entropy * 0.9, 0.0)
                dup.timestamp = int(time.time() * 1000)
                self.store.upsert(dup)
                self.field.add(dup)
                self._dedup_bytes_saved += original_size
                self._dedup_count += 1
                if self.resolve_contradictions:      # corroboration re-challenges rivals
                    self._resolve_competing(dup)
                return dup

        m = Monad(
            source_type=source_type, summary=summary, value=content,
            keywords=keywords, entities=entities, metadata=metadata,
            truth_value=truth_value, entropy=entropy, observer_id=observer_id,
            embedding=emb, original_size=original_size, monad_size=monad_size,
        )
        # 3D-time: populate the temporal orientation weights from the fact's content tense
        # (computed above) — a different axis from valid_from / recency.
        m.temporal_past, m.temporal_present, m.temporal_future = new_past, new_present, new_future
        m.enforce_complementarity()
        if self.entropy_admission:               # anti-rot: incoherent input enters on probation
            self._admission_gate(m)
        superseded = self._supersede(m)          # newer fact demotes stale ones
        # Cryptographic provenance: sign the monad (content-hash + fact + observer +
        # timestamp) with this node's Ed25519 key. Makes "who said what" verifiable and
        # forged high-truth claims detectable. Additive; unsigned legacy monads unaffected.
        if os.environ.get("ACI_SIGN", "1") != "0":
            cid, s_id, sig = signing.sign(m.value, m.metadata, m.observer_id, m.timestamp)
            m.metadata = {**m.metadata, "cid": cid, "signer": s_id, "sig": sig}
        self.store.upsert(m)
        self._fact_register(m)
        self._context_register(m)
        self.field.add(m)
        self.index.add(m.id, emb)
        for old in superseded:
            self.relate(m.id, old.id, "SUPERSEDES")
        if self.resolve_contradictions:              # soft-resolve cross-source competitors
            self._resolve_competing(m)
        return m

    def _supersede(self, m: Monad) -> List[Monad]:
        """If m is a fact (subject+predicate) that conflicts with an existing
        non-superseded fact (same subject::predicate, different object), demote
        the old one and mark it superseded. This is a UQRT-layer behavior a plain
        vector store has no notion of."""
        key = self._fact_key(m.metadata)
        if not key:
            return []
        new_obj = (m.metadata.get("object") or m.value).strip().lower()
        out = []
        for oid in list(self._fact_index.get(key, ())):   # only same-key candidates, O(matches)
            if oid == m.id:
                continue
            other = self.store.get(oid)
            if other is None or other.metadata.get("status") == "superseded":
                continue
            old_obj = (other.metadata.get("object") or other.value).strip().lower()
            if old_obj and new_obj and old_obj != new_obj:
                # Supersede ONLY a same-source correction by an equal/higher-truth
                # update. Conflicts ACROSS sources (or from a less-credible claim)
                # are kept as competing claims and resolved per-observer at query
                # time (observer-relative truth). Also fixes a latent bug where a
                # low-truth rumor could supersede a verified fact.
                same_source = (m.source_type == other.source_type)
                more_credible = (m.truth_value + 1e-9 >= other.truth_value)
                if same_source and more_credible:
                    other.truth_value *= 0.3
                    other.metadata = {**other.metadata, "status": "superseded",
                                      "superseded_by": m.id}
                    self.store.upsert(other)
                    self._fact_unregister(other.id, other.metadata)   # no longer an active fact
                    out.append(other)
        return out

    # ---- entropy-weighted admission (opt-in; the Phase-6 anti-rot gate) ---------
    _ADMIT_DISCOUNT = 0.30    # truth multiplier for input that contradicts established truth
    _ADMIT_ENTROPY = 0.50     # entropy added (energy cost of admitting incoherent input)

    def _contradicted_by_truth(self, m: Monad) -> float:
        """Max truth_value of an ESTABLISHED monad that contradicts m and is at least as
        strong as m. >0 means m conflicts with equal-or-higher-truth knowledge already held."""
        related = []
        key = self._fact_key(m.metadata)
        if key:
            for oid in self._fact_index.get(key, ()):
                if oid == m.id:
                    continue
                r = self.store.get(oid)
                if r is not None and r.metadata.get("status") != "superseded":
                    related.append(r)
        mctx = self._context_of(m.metadata)
        if m.embedding:
            for cid, sim in self.index.search(m.embedding, 6):
                if sim < 0.5:
                    break
                if cid == m.id:
                    continue
                r = self.store.get(cid)
                if (r is not None and r.metadata.get("status") != "superseded"
                        and r not in related and self._context_of(r.metadata) == mctx):
                    related.append(r)   # same context only — contradictions don't cross matters
        worst = 0.0
        for r in related:
            if truthmod.detect_contradiction(m, r) and r.truth_value >= m.truth_value - 1e-9:
                worst = max(worst, r.truth_value)
        return worst

    def _admission_gate(self, m: Monad) -> None:
        """Admit incoherent input on probation: discount its truth, raise its entropy."""
        if self._contradicted_by_truth(m) > 0:
            m.truth_value *= self._ADMIT_DISCOUNT
            m.entropy = min(m.entropy + self._ADMIT_ENTROPY, 5.0)

    # ---- soft contradiction resolution (opt-in; the Phase-1 dynamics) ----------
    # The single validated parameter set (basin-tested across 144 configs, 97% pass).
    _RES_STANDOFF = 0.15      # log-space gap under which two claims are a genuine standoff
    _RES_MARGIN = 0.40        # log-space gap needed to mark the dominated claim superseded
    _RES_PULL = 0.55          # rate the weaker claim is undermined
    _RES_DOM_ERODE = 0.55     # incumbent erosion, scaled by challenger strength

    def _resolve_competing(self, m: Monad) -> None:
        """Soft, evidence-driven resolution of CROSS-source competing claims (same
        subject::predicate, DIFFERENT object) that _supersede deliberately leaves alive.
        Each ingest/corroboration is one 'contradiction event'; over accumulating
        evidence the field converges — the weaker claim is undermined, an entrenched
        incumbent resists weak noise but yields to sustained strong evidence, and a
        claim is marked superseded once driven clearly below the winner. Never deletes."""
        key = self._fact_key(m.metadata)
        if not key:
            return
        new_obj = (m.metadata.get("object") or m.value).strip().lower()
        for oid in list(self._fact_index.get(key, ())):
            if oid == m.id:
                continue
            other = self.store.get(oid)
            if other is None or other.metadata.get("status") == "superseded":
                continue
            old_obj = (other.metadata.get("object") or other.value).strip().lower()
            if old_obj and new_obj and old_obj != new_obj:
                self._truth_competition(m, other)

    def _truth_competition(self, a: Monad, b: Monad) -> None:
        """One competition event between two contradicting claims, in the truth algebra:
        log_compress (non-saturating comparison), distance_decay (contradiction pressure),
        coupling kappa (entrenchment resists). Mutates truth_value/entropy and may mark
        the dominated claim superseded. Persists both."""
        gap = abs(gates.log_compress(a.truth_value) - gates.log_compress(b.truth_value))
        if gap < self._RES_STANDOFF:
            return                                  # genuine standoff: keep both competing
        dom, sub = (a, b) if a.truth_value >= b.truth_value else (b, a)
        pressure = 1.0 - gates.distance_decay(gap, 1.0)
        ratio = (gates.log_compress(sub.truth_value)
                 / max(gates.log_compress(dom.truth_value), gates.EPS))   # challenger strength
        k_sub = gates.coupling_constant(sub.contextual_complexity, sub.entropy)
        k_dom = gates.coupling_constant(dom.contextual_complexity, dom.entropy)
        sub.truth_value = max(sub.truth_value * (1.0 - self._RES_PULL * pressure / k_sub), gates.EPS)
        dom.truth_value = max(dom.truth_value
                              * (1.0 - self._RES_DOM_ERODE * pressure * ratio / k_dom), gates.EPS)
        sub.entropy = min(sub.entropy + 0.05, 2.0)
        dom.entropy = min(dom.entropy + 0.03, 2.0)
        hi, lo = (a, b) if a.truth_value >= b.truth_value else (b, a)
        if gates.log_compress(hi.truth_value) - gates.log_compress(lo.truth_value) > self._RES_MARGIN:
            lo.metadata = {**lo.metadata, "status": "superseded", "superseded_by": hi.id}
            self._fact_unregister(lo.id, lo.metadata)
            self.relate(hi.id, lo.id, "SUPERSEDES")
        self.store.upsert(a)
        self.store.upsert(b)

    def _find_duplicate(self, emb: List[float], observer_id: str,
                        metadata: Dict[str, str]) -> Optional[Monad]:
        # A factual UPDATE (same subject::predicate, different object) is NOT a
        # duplicate even if its embedding is near-identical - it must flow to
        # supersession. Only true repeats are deduped.
        subj, pred = metadata.get("subject"), metadata.get("predicate")
        new_key = (f"{subj.strip().lower()}::{pred.strip().lower()}"
                   if (subj and pred) else None)
        new_obj = (metadata.get("object") or "").strip().lower()
        for cid, sim in self.index.search(emb, 10):
            if sim < self.dedup_threshold:
                break                                # sorted desc -> nothing else qualifies
            m = self.store.get(cid)
            if m is None or m.observer_id != observer_id or not m.embedding:
                continue
            if new_key:
                ms, mp = m.metadata.get("subject"), m.metadata.get("predicate")
                if ms and mp and f"{ms.strip().lower()}::{mp.strip().lower()}" == new_key:
                    if (m.metadata.get("object") or "").strip().lower() != new_obj:
                        continue                     # conflict -> supersession, not dedup
            return m
        return None

    # ---------- PRIMITIVE 2: recall ----------
    def recall(self, query: str, k: int = 5, half_life_days: float = 30.0,
               include_superseded: bool = False, graph_hops: int = 1,
               observer=None, as_of: Optional[float] = None,
               tense_aware: bool = True, field_primary: bool = False,
               context: Optional[str] = None) -> List[RecallHit]:
        # Temporal validity: as_of reconstructs the value that was valid AT a past
        # time. For that we must consider superseded versions too.
        if as_of is not None:
            include_superseded = True
        q = self.embedder.embed(query)
        now = time.time() * 1000
        # 3D-time: only when the QUERY has a clear tense intent (else None -> no effect,
        # so neutral queries are never perturbed). A modest tiebreaker, not an override.
        qtense = tensemod.query_tense(query) if tense_aware else None
        # field-primary widens the sieve: the embedder only needs to seed candidates;
        # the meaning-field does the precise ranking.
        pool = max(k * 10, 80) if field_primary else max(k * 6, 40)
        ranked = self.index.search(q, pool)              # vectorized top-k by similarity (coarse sieve)
        sim_map = {cid: s for cid, s in ranked}
        candidates = set(sim_map)
        # Graph expansion: pull 1-hop neighbours of the strongest hits so related-
        # but-lexically-different monads surface (meaning-field traversal).
        neighbor_ids = set()
        if graph_hops > 0:
            for cid, _ in ranked[:max(3, k)]:
                neighbor_ids |= self.field.neighbors(cid)
            # add neighbours the vector missed (coverage) AND keep the full neighbour
            # set so the graph bonus also RE-RANKS connected facts that were retrieved
            # but ranked too low (disambiguation) — not just brand-new far monads.
            candidates |= neighbor_ids
        # field-primary: weighted multi-hop reach from the strongest seeds. Pulls in
        # connected-but-lexically-different monads the vector sieve ranks low/misses.
        reach_map: Dict[str, float] = {}
        if field_primary:
            seeds = [cid for cid, _ in ranked[:5]]   # small fixed anchor (top lexical matches)
            reach_map = self.field.reach(seeds, max_hops=2, decay=0.7)
            candidates |= set(reach_map)
        # Bounded truth-context: restrict to one context. A small context is scored in FULL
        # (its monads may sit outside the global ANN pool) — so scoping never starves recall.
        if context is not None:
            ctx_ids = self._context_index.get(context.strip().lower(), set())
            candidates = (set(ctx_ids) if len(ctx_ids) <= 3000
                          else set(ctx_ids) & candidates)
        # First pass: gather each candidate's signals. Truth is compressed with log(1+psi)
        # (the canonical log_compress), NOT sigmoid — sigmoid SATURATES (psi=6 and psi=2.9
        # both map to ~0.95), so a repeated low-credibility claim, whose psi the anti-rot
        # correctly caps low, could not be told apart from a high-credibility fact, and
        # recency then broke the tie toward the noise (the poison-resistance ranking gap).
        raw = []
        for cid in candidates:
            m = self.store.get(cid)
            if m is None:
                continue
            if not include_superseded and m.metadata.get("status") == "superseded":
                continue
            if observer is not None and not observer.can_see(m):
                continue                                  # observer-relative visibility
            sim = sim_map.get(cid)
            if sim is None:
                sim = cosine(q, m.embedding) if m.embedding else 0.0
            age_days = max(0.0, (now - m.timestamp) / 86_400_000.0)
            recency = math.exp(-age_days / max(half_life_days, 0.1))
            # 3D-time as a GRADED dimension: reward a monad in proportion to how strongly
            # its content is oriented to the tense the query asks about — not a flat match.
            # A strongly-past fact (temporal_past≈0.7) outweighs a barely-past one for a
            # "what happened" query; neutral queries (qtense=None) are untouched.
            tense_bonus = 0.35 * getattr(m, f"temporal_{qtense}", 0.0) if qtense else 0.0
            trust = observer.trust_for(m) if observer is not None else 1.0
            truth_c = gates.log_compress(max(m.truth_value * trust, 0.0))   # non-saturating
            raw.append((cid, m, sim, recency, tense_bonus, truth_c))
        # Normalise truth RELATIVE to this candidate pool: the most-credible candidate anchors
        # 1.0, so credibility genuinely discriminates (a psi=6 fact clearly outranks a psi=2.9
        # one) instead of everything saturating near 1.0.
        max_truth = max((r[5] for r in raw), default=0.0) or 1.0
        hits: List[RecallHit] = []
        for cid, m, sim, recency, tense_bonus, truth_c in raw:
            eff_truth = truth_c / max_truth                # observer-relative, non-saturating
            if field_primary:
                # meaning-field PRIMARY: graph reach + truth + coherence lead; similarity is
                # demoted to a coarse component. The field, not the embedder, decides ranking.
                graph_strength = reach_map.get(cid, 0.0)
                coherence = 1.0 / (1.0 + max(m.entropy, 0.0))   # low entropy = coherent
                score = (0.20 * sim + 0.40 * graph_strength + 0.20 * eff_truth
                         + 0.10 * coherence + 0.10 * recency + tense_bonus)
            else:
                graph_bonus = 0.3 if cid in neighbor_ids else 0.0  # explicit link = strong signal
                score = 0.6 * sim + 0.2 * eff_truth + 0.2 * recency + graph_bonus + tense_bonus
            hits.append(RecallHit(m, score, sim, recency))
        hits.sort(key=lambda h: -h.score)
        # Temporal collapse: for facts that change over time (same fact_key), keep the
        # single version VALID at `as_of` — latest valid_from <= as_of. Non-temporal
        # hits (no fact_key) pass through untouched.
        if as_of is not None:
            groups: Dict[str, RecallHit] = {}
            passthrough: List[RecallHit] = []
            for h in hits:
                fk = (h.monad.metadata or {}).get("fact_key")
                if not fk:
                    passthrough.append(h)
                    continue
                vf = float(h.monad.metadata.get("valid_from", h.monad.timestamp))
                if vf <= as_of:
                    cur = groups.get(fk)
                    if cur is None or vf > float(cur.monad.metadata.get(
                            "valid_from", cur.monad.timestamp)):
                        groups[fk] = h
            hits = passthrough + list(groups.values())
            hits.sort(key=lambda h: -h.score)
        return hits[:k]

    def assert_fact(self, content: str, fact_key: str, valid_from: Optional[float] = None,
                    source_type: str = "KNOWLEDGE", observer_id: Optional[str] = None,
                    metadata: Optional[Dict] = None, truth_value: float = 1.0):
        """Record a NEW value for a fact that changes over time. Prior values are
        SUPERSEDED (not dedup-merged), so 'current' recall returns the latest while
        as_of recall can still reconstruct older values. `fact_key` identifies the
        fact (e.g. 'helios::deadline'); `valid_from` is when this value took effect."""
        vf = valid_from if valid_from is not None else time.time()
        md = dict(metadata or {})
        md["fact_key"] = fact_key
        md["valid_from"] = vf
        # prior, still-current versions of the same fact — fast indexed lookup, NOT a
        # full-store scan (which times out on a large store).
        prior_ids = self.store.monad_ids_by_fact_key(fact_key)
        priors = [m for i in prior_ids
                  if (m := self.store.get(i)) is not None
                  and (m.metadata or {}).get("status") != "superseded"]
        new = self.monadise(content, source_type=source_type, observer_id=observer_id,
                            metadata=md, truth_value=truth_value, dedup=False)
        for p in priors:
            if p.id != new.id:
                self.supersede(p.id, new_id=new.id, reason="temporal update")
        return new

    # ---------- PRIMITIVE 3: relate ----------
    def relate(self, source_id: str, target_id: str,
               relation_type: str = "ASSOCIATIVE", weight: float = 1.0) -> None:
        self.field.relate(source_id, target_id, relation_type, weight)
        self.store.add_relation(source_id, target_id, relation_type, weight)

    # ---------- PRIMITIVE 4: validate ----------
    @staticmethod
    def _same_fact(a: Monad, b: Monad) -> bool:
        sa, pa = a.metadata.get("subject"), a.metadata.get("predicate")
        sb, pb = b.metadata.get("subject"), b.metadata.get("predicate")
        if not (sa and pa and sb and pb):
            return False
        if (sa.lower(), pa.lower()) != (sb.lower(), pb.lower()):
            return False
        oa = (a.metadata.get("object") or a.value).strip().lower()
        ob = (b.metadata.get("object") or b.value).strip().lower()
        return oa == ob

    def validate(self, statement: str, metadata: Optional[Dict[str, str]] = None,
                 truth_value: Optional[float] = None, top_n: int = 8,
                 observer=None) -> ValidationResult:
        """Check a statement against memory. Truth-aware: a contradiction only
        UNDERMINES the statement if it comes from equal-or-higher-truth evidence.
        A conflict with a lower-truth claim means the *other* one is the suspect."""
        metadata = dict(metadata or {})
        # Auto-extract so contradiction works when validating RAW text.
        if not (metadata.get("subject") and metadata.get("predicate")):
            tri = self.extractor.extract(statement)
            if tri.get("subject") and tri.get("predicate"):
                metadata.setdefault("subject", tri["subject"])
                metadata.setdefault("predicate", tri["predicate"])
                if tri.get("object"):
                    metadata.setdefault("object", tri["object"])
        candidate = Monad(
            summary=statement[:240], value=statement,
            keywords=self._keywords(statement), metadata=metadata,
            embedding=self.embedder.embed(statement),
            entropy=self._entropy(statement), observer_id=self.observer_id,
            truth_value=truth_value if truth_value is not None else 1.0,
        )
        related = [h.monad for h in self.recall(statement, k=top_n, include_superseded=True,
                                                 observer=observer)]

        cand_truth = candidate.truth_value
        if truth_value is None:                       # infer from a stored match
            for r in related:
                if self._same_fact(candidate, r):
                    cand_truth = r.truth_value
                    break

        trace = [f"Recalled {len(related)} related monad(s) (candidate psi={cand_truth:.2f})."]
        undermining, subordinate = [], []
        for r in related:
            if observer is not None and not observer.can_see(r):
                continue
            c = truthmod.detect_contradiction(candidate, r)
            if not c:
                continue
            r_eff = r.truth_value * (observer.trust_for(r) if observer is not None else 1.0)
            c.update(against_id=r.id, against=r.summary, against_truth=round(r_eff, 2))
            if r_eff >= cand_truth - 1e-9:
                undermining.append(c)
                trace.append(f"UNDERMINED by equal/higher-truth: '{r.summary[:48]}' (psi_eff={r_eff:.2f})")
            else:
                subordinate.append(c)
                trace.append(f"Conflicts with lower-truth claim: '{r.summary[:48]}' (psi_eff={r_eff:.2f})")

        is_consistent = len(undermining) == 0
        confidence = (min(1.0, 0.5 + 0.1 * cand_truth) if is_consistent
                      else max(0.0, 0.3 - 0.1 * len(undermining)))
        verdict = ("undermined" if undermining
                   else "conflict_lower_truth" if subordinate else "consistent")
        return ValidationResult(
            statement=statement,
            is_consistent=is_consistent,
            confidence=confidence,
            entropy=candidate.entropy,
            contradictions=undermining + subordinate,
            evidence=[r.summary for r in related[:3]],
            trace=trace,
            has_contradiction=bool(undermining or subordinate),
            verdict=verdict,
        )

    # ---------- PROVENANCE: cryptographic signature verification ----------
    def verify_monad(self, m) -> Optional[bool]:
        """True = Ed25519 signature valid; False = FORGED/tampered (content or claimed
        author altered after signing — do NOT trust it whatever its truth_value); None =
        unsigned (legacy monad written before signing, or signing disabled)."""
        md = getattr(m, "metadata", None) or {}
        return signing.verify(m.value, md, m.observer_id, m.timestamp,
                              md.get("signer"), md.get("sig"))

    def verify_by_id(self, monad_id: str) -> dict:
        m = self.store.get(monad_id)
        if m is None:
            return {"found": False}
        v = self.verify_monad(m)
        md = m.metadata or {}
        return {"found": True, "verified": v,
                "status": ("valid" if v is True else "FORGED" if v is False else "unsigned"),
                "signer": md.get("signer", ""), "cid": md.get("cid", "")}

    # ---------- PRIMITIVE 5: compress (the optimization payoff) ----------
    def compress(self) -> dict:
        monads = self.store.all()
        original = sum(m.original_size for m in monads) + self._dedup_bytes_saved
        stored = self.store.total_monad_bytes()
        ratio = (original / stored) if stored else 0.0
        return {
            "monads_stored": len(monads),
            "duplicates_merged": self._dedup_count,
            "original_bytes": original,
            "stored_bytes": stored,
            "dedup_bytes_saved": self._dedup_bytes_saved,
            "compression_ratio": round(ratio, 2),
        }

    # ---------- OPTIMIZATION (USP-2): reasoning cache, context, routing ----------
    def cached_compute(self, content: str, compute_fn, source_type: str = "INFERENCE",
                       threshold: float = 0.97):
        """Avoid repeated expensive inference: if a semantically-equivalent prior
        result exists, return it instead of recomputing. Returns (result, was_hit)."""
        self._infer_total += 1
        emb = self.embedder.embed(content)
        for cid, sim in self.index.search(emb, 10):
            if sim < threshold:
                break
            m = self.store.get(cid)
            if m is not None and m.metadata.get("kind") == "inference":
                self._infer_hits += 1
                return m.metadata.get("result", ""), True
        result = compute_fn(content)
        self.monadise(content, source_type=source_type,
                      metadata={"kind": "inference", "result": str(result)}, dedup=False)
        return result, False

    def cache_stats(self) -> dict:
        total, hits = self._infer_total, self._infer_hits
        return {"requests": total, "cache_hits": hits, "compute_calls": total - hits,
                "inference_avoided_pct": round(100.0 * hits / total, 1) if total else 0.0}

    def build_context(self, query: str, k: int = 5, observer=None):
        """Compressed context for an LLM: top-k monad summaries instead of raw docs.
        Returns (context_string, num_monads)."""
        hits = self.recall(query, k=k, observer=observer)
        return "\n".join(f"- {h.monad.summary}" for h in hits), len(hits)

    def route(self, query: str, sim_threshold: float = 0.5,
              truth_threshold: float = 0.6) -> dict:
        """Local-vs-cloud decision: serve locally if a confident local monad exists,
        else defer to cloud/mesh. (Avoids a remote call when ACI already knows.)"""
        hits = self.recall(query, k=1)
        if hits and hits[0].similarity >= sim_threshold and \
                hits[0].monad.normalized_truth() >= truth_threshold:
            return {"target": "local", "confidence": round(hits[0].score, 3),
                    "monad_id": hits[0].monad.id}
        return {"target": "cloud", "confidence": round(hits[0].score, 3) if hits else 0.0,
                "monad_id": None}

    # ---------- ADMIN / PRIVACY (Phase 4) ----------
    def list_monads(self, limit: int = 50, include_superseded: bool = True,
                    source_type: Optional[str] = None) -> List[Monad]:
        # LIMIT query (store.recent) — no longer loads the entire store to slice it.
        fetch = limit if include_superseded else max(limit * 3, limit)
        monads = self.store.recent(fetch, source_type=source_type)   # most-recent first
        if not include_superseded:
            monads = [m for m in monads if m.metadata.get("status") != "superseded"]
        return monads[:limit]

    def _rebuild_index(self) -> None:
        self.index = VectorIndex()
        for mm in self.store.all():
            if mm.embedding:
                self.index.add(mm.id, mm.embedding)

    def forget(self, monad_id: str) -> bool:
        """Right-to-be-forgotten: delete a monad (incremental index removal, O(d))."""
        m = self.store.get(monad_id)
        if m is None:
            return False
        self.store.delete(monad_id)
        self.field.nodes.pop(monad_id, None)
        self.index.remove(monad_id)
        self.image_index.remove(monad_id)
        self._fact_unregister(monad_id, m.metadata)
        return True

    def forget_by_source(self, path: str) -> int:
        """Delete all monads from a source path (used when re-ingesting a changed file)."""
        ids = self.store.monad_ids_by_path(path)
        for mid in ids:
            m = self.store.get(mid)
            self.store.delete(mid)
            self.field.nodes.pop(mid, None)
            self.index.remove(mid)
            self.image_index.remove(mid)
            if m is not None:
                self._fact_unregister(mid, m.metadata)
        return len(ids)

    def supersede(self, old_id: str, new_id: Optional[str] = None,
                  reason: str = "") -> bool:
        """Retire a stale fact WITHOUT deleting it: mark it superseded (so it drops out
        of normal recall/listing) and, if a replacement is given, record the link. This
        is how the self-learning KB replaces outdated knowledge with newer/higher-trust
        knowledge while keeping an auditable trail."""
        m = self.store.get(old_id)
        if m is None:
            return False
        m.metadata["status"] = "superseded"
        if new_id:
            m.metadata["superseded_by"] = new_id
        if reason:
            m.metadata["superseded_reason"] = reason[:200]
        # halve its truth so it can never out-rank a live fact even if recalled raw
        m.truth_value = min(m.truth_value, 0.2)
        self.store.upsert(m)
        if new_id:
            try:
                self.relate(new_id, old_id, "SUPERSEDES")
            except Exception:
                pass
        return True

    def close(self) -> None:
        self.store.close()
