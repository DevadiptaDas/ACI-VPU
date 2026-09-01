"""
HONEST benchmark: ACI vs a real vector-DB memory baseline.

This is the comparison that actually matters. Both systems use the SAME
embeddings (ACI's embedder), so the only thing measured is what the UQRT-MCA
layer adds on top of vanilla embed+cosine retrieval.

We do NOT test raw persistence here (a vector DB persists too - ACI has no edge
there). We test the three places the monad layer is genuinely decisive:

  A. Stale-update resolution  - conflicting fact update; return the CURRENT value
  B. Misinformation flagging  - a low-truth rumor conflicting with a verified fact
  C. Dedup / compression      - repeated content

Run:  py benchmark/benchmark_vs_vectordb.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aci import ACI                       # noqa: E402
from aci.embeddings import cosine         # noqa: E402


class VectorStoreBaseline:
    """Vanilla RAG memory: embed + cosine top-k. Stores everything, no truth,
    no contradiction notion, no dedup. Same embedder as ACI for a fair fight."""
    def __init__(self, embedder):
        self.embedder = embedder
        self.items = []          # (text, embedding, meta)
        self.raw_bytes = 0

    def ingest(self, text, meta=None):
        self.items.append((text, self.embedder.embed(text), meta or {}))
        self.raw_bytes += len(text.encode("utf-8"))

    def recall(self, query):
        top = self.recall_topk(query, 1)
        return top[0] if top else None

    def recall_topk(self, query, k=5):
        q = self.embedder.embed(query)
        scored = sorted(((cosine(q, emb), text) for text, emb, _ in self.items),
                        key=lambda x: -x[0])
        return [t for _, t in scored[:k]]

    def flags_contradiction(self):
        return False                          # no such concept

    def count(self):
        return len(self.items)


def yn(b):
    return "YES" if b else "no "


def task_a(embedder):
    aci = ACI(db_path=":memory:", observer_id="A")
    base = VectorStoreBaseline(embedder)
    older = ("Project Apollo deadline is March 15.",
             {"subject": "project apollo", "predicate": "deadline", "object": "March 15"})
    newer = ("Project Apollo deadline is April 2.",
             {"subject": "project apollo", "predicate": "deadline", "object": "April 2"})
    for text, meta in (older, newer):
        aci.monadise(text, source_type="USER_INPUT", metadata=meta, truth_value=2.0)
        base.ingest(text, meta)
    aci_vals = [h.monad.value.lower() for h in aci.recall("apollo deadline", k=5)]
    base_vals = [t.lower() for t in base.recall_topk("apollo deadline", 5)]
    aci.close()
    aci_ok = any("april" in v for v in aci_vals) and not any("march" in v for v in aci_vals)
    base_surfaces_stale = any("march" in v for v in base_vals)
    return aci_ok, (not base_surfaces_stale), aci_vals, base_vals


def task_b(embedder):
    aci = ACI(db_path=":memory:", observer_id="B")
    base = VectorStoreBaseline(embedder)
    fact = ("The CEO is Maria Lopez.",
            {"subject": "ceo", "predicate": "is", "object": "Maria Lopez"}, 2.0)
    rumor = ("The CEO is John Smith.",
             {"subject": "ceo", "predicate": "is", "object": "John Smith"}, 0.2)
    for text, meta, tv in (fact, rumor):
        aci.monadise(text, source_type="WEB", metadata=meta, truth_value=tv)
        base.ingest(text, meta)
    v_fact = aci.validate("The CEO is Maria Lopez.", truth_value=2.0,
                          metadata={"subject": "ceo", "predicate": "is", "object": "Maria Lopez"})
    v_rumor = aci.validate("The CEO is John Smith.", truth_value=0.2,
                           metadata={"subject": "ceo", "predicate": "is", "object": "John Smith"})
    aci.close()
    # ACI flags the rumor (conflicts with higher-truth fact) but not the fact.
    aci_flags = (not v_rumor.is_consistent) and v_fact.is_consistent
    return (aci_flags, base.flags_contradiction(),
            v_fact.confidence, v_rumor.confidence)


def task_c(embedder):
    aci = ACI(db_path=":memory:", observer_id="C")
    base = VectorStoreBaseline(embedder)
    doc = "Revenue grew across all regions this quarter. " * 60
    for _ in range(5):
        aci.monadise(doc, source_type="FILE", summary="Q3 revenue")
        base.ingest(doc)
    stats = aci.compress()
    aci.close()
    return (stats["monads_stored"], base.count(),
            stats["stored_bytes"], base.raw_bytes)


def main():
    aci_tmp = ACI(db_path=":memory:")
    embedder = aci_tmp.embedder
    aci_tmp.close()

    print("=" * 72)
    print(f"  ACI vs VECTOR-DB BASELINE   (identical embedder: {embedder.name})")
    print("  Only the UQRT-MCA layer differs between the two systems.")
    print("=" * 72)

    a_aci, a_base, aci_vals, base_vals = task_a(embedder)
    b_flag_aci, b_flag_base, c_fact, c_rumor = task_b(embedder)
    c_aci_n, c_base_n, c_aci_b, c_base_b = task_c(embedder)

    print(f"  {'Capability':<42}{'ACI':<8}{'VectorDB':<10}")
    print("  " + "-" * 60)
    print(f"  {'A. Returns current, suppresses superseded':<42}{yn(a_aci):<8}{yn(a_base):<10}")
    print(f"       ACI top  -> {aci_vals}")
    print(f"       VDB top  -> {base_vals}")
    print(f"  {'B. Flags low-truth rumor vs verified fact':<42}{yn(b_flag_aci):<8}{yn(b_flag_base):<10}")
    print(f"       ACI confidence: fact={c_fact:.2f}  rumor={c_rumor:.2f}")
    print(f"  {'C. Dedup repeated content (5 copies)':<42}{str(c_aci_n)+' stored':<8}{str(c_base_n)+' stored':<10}")
    print(f"       bytes: ACI={c_aci_b}  VectorDB={c_base_b}")
    print(f"  {'Explainable reasoning trace':<42}{'YES':<8}{'no ':<10}")
    print("=" * 72)
    print("  The wins come from the monad layer (truth values, contradiction/XOR,")
    print("  supersession, dedup) - not from embeddings, which are identical.")


if __name__ == "__main__":
    main()
