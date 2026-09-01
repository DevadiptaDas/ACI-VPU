"""
benchmark_embedder.py — UQRT-MCA-native embedder vs sentence-transformers.

Honest semantic-retrieval test: each query is a PARAPHRASE of its target using
mostly DIFFERENT words, so it measures meaning-matching, not word overlap. We
embed a small corpus (targets + distractors) with each embedder, rank by cosine,
and report top-1 / top-3 accuracy and mean reciprocal rank (MRR).

Run:  py benchmark/benchmark_embedder.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.embeddings import UqrtMcaEmbedder, StableLexicalEmbedder, cosine, embed_many  # noqa: E402

# (id, text) — content in the user's actual domain
CORPUS = [
    ("truth", "Monad truth values are continuous probabilities ranging from zero to infinity, "
              "collapsing to a definite value only after observation."),
    ("optimize", "ACI keeps the device healthy by compressing stored memory and clearing "
                 "unused junk files so the machine stays fast."),
    ("4hww", "The Four-Hour Work Week argues you should outsource tasks and build passive "
             "income streams to escape the traditional nine-to-five job."),
    ("contagious", "Contagious explains why certain products and ideas spread — social "
                   "currency, triggers, and emotion make things go viral."),
    ("legal", "The petition was filed before the district court seeking an injunction "
              "against the respondent in the property dispute."),
    ("relativity", "In UQRT the geometry of spacetime is derived from observer-relative "
                   "events rather than a fixed background metric."),
    ("encrypt", "Data at rest is protected with a password-derived key and an authenticated "
                "cipher, so files on disk cannot be read without the passphrase."),
    ("recall", "Memory retrieval ranks stored items by a blend of similarity, trust-weighted "
               "truth, recency, and graph proximity."),
    ("paradox", "The liar sentence is resolved by iterating toward a fixed point where the "
                "truth value settles at one, dissolving the contradiction."),
    ("photo", "You can search your pictures by describing what is in them, because images are "
              "encoded into the same meaning space as text."),
    ("mcp", "Any connected assistant can read and write the shared memory through a standard "
            "tool protocol, so different AIs collaborate on the same knowledge."),
    ("entropy", "A monad's entropy measures its uncertainty, and information density is the "
                "ratio of its truth value to that entropy."),
]
# distractors (no query points here) — make retrieval non-trivial
DISTRACTORS = [
    ("d1", "The recipe calls for two cups of flour, a pinch of salt, and fresh basil leaves."),
    ("d2", "Trains depart the central station every fifteen minutes during rush hour."),
    ("d3", "The hiking trail climbs steeply through pine forest before reaching the ridge."),
    ("d4", "Quarterly revenue grew while operating margins stayed roughly flat year over year."),
    ("d5", "The orchestra tuned their instruments as the conductor walked onto the stage."),
    ("d6", "Photosynthesis converts sunlight, water, and carbon dioxide into glucose and oxygen."),
    ("d7", "He repainted the fence over the weekend and planted tomatoes along the back wall."),
    ("d8", "The museum's new wing features sculptures from the early twentieth century."),
]
# (query, target_id) — paraphrases with LOW word overlap vs the target
QUERIES = [
    ("how does the system decide whether a statement is correct", "truth"),
    ("make my laptop run faster and free up space", "optimize"),
    ("ideas to earn money without a regular job", "4hww"),
    ("why do some things become popular and spread", "contagious"),
    ("court case about a land disagreement", "legal"),
    ("keeping my saved documents private from prying eyes", "encrypt"),
    ("finding a picture by what it shows", "photo"),
    ("letting different AI assistants share what they know", "mcp"),
    ("resolving a self-referential contradiction", "paradox"),
    ("how relevant memories get picked when I ask something", "recall"),
]


def evaluate(embedder, corpus, queries):
    ids = [c[0] for c in corpus]
    vecs = embed_many(embedder, [c[1] for c in corpus])
    top1 = top3 = 0
    rr = 0.0
    for q, target in queries:
        qv = embedder.embed(q)
        ranked = sorted(ids, key=lambda i: cosine(qv, vecs[ids.index(i)]), reverse=True)
        rank = ranked.index(target) + 1
        top1 += (rank == 1)
        top3 += (rank <= 3)
        rr += 1.0 / rank
    n = len(queries)
    return {"top1": top1 / n, "top3": top3 / n, "mrr": rr / n}


def main():
    corpus = CORPUS + DISTRACTORS
    print("=" * 64)
    print(" EMBEDDER BENCHMARK — paraphrase retrieval (meaning, not overlap)")
    print(f" corpus: {len(corpus)} passages | queries: {len(QUERIES)} paraphrases")
    print("=" * 64)

    native = evaluate(UqrtMcaEmbedder(), corpus, QUERIES)
    lexical = evaluate(StableLexicalEmbedder(), corpus, QUERIES)
    results = [("UQRT-MCA-native", native), ("lexical-stable (baseline)", lexical)]
    try:
        from aci.embeddings import SentenceTransformerEmbedder
        st = evaluate(SentenceTransformerEmbedder(), corpus, QUERIES)
        results.append(("sentence-transformers", st))
    except Exception as e:
        print(f"(sentence-transformers unavailable: {e})")

    print(f"\n{'embedder':28} {'top-1':>7} {'top-3':>7} {'MRR':>7}")
    print("-" * 52)
    for name, r in results:
        print(f"{name:28} {r['top1']*100:6.0f}% {r['top3']*100:6.0f}% {r['mrr']:7.3f}")
    print("\n(top-1 = right answer ranked first; MRR = 1/rank averaged)")


if __name__ == "__main__":
    main()
