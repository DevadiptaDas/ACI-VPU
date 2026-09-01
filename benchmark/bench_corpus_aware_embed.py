"""
bench_corpus_aware_embed.py — does an embedder that USES ACI's accumulated knowledge
improve retrieval over time? Tests the user's hypothesis directly.

BASELINE   = the fixed UqrtMcaEmbedder (context-free hash; ignores the corpus).
CANDIDATE  = same embedder + a synonym/co-occurrence layer LEARNED from the corpus
             (distributional semantics): two terms are 'related' if they appear in
             similar contexts across accumulated docs. As the corpus grows, the
             learned associations get richer -> synonym bridging improves.

Eval = paraphrase pairs where query and the correct doc use DIFFERENT words
(synonyms) -> the fixed embedder fails them. Includes invented DOMAIN jargon a
pretrained model could never know, to isolate the 'learn from YOUR corpus' edge.

We measure top-1 accuracy as the corpus grows. If the candidate RISES while the
baseline stays FLAT, the hypothesis holds.

Run:  py benchmark/bench_corpus_aware_embed.py
"""
import math
import re
import sys
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding="utf-8")
from aci.embeddings import UqrtMcaEmbedder, cosine          # noqa: E402

emb = UqrtMcaEmbedder()
STOP = set("the a an of to in on for and or but is was were be it its this that with as at by "
           "would will not she he they her his at would felt".split())


def content(text):
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2]


# eval: (query, correct_doc) — synonyms, LOW direct overlap
PAIRS = [
    ("the physician examined the patient", "the doctor checked the sick individual"),
    ("the automobile would not start", "the car failed to ignite the engine"),
    ("she felt joyful at the event", "the woman was happy at the celebration"),
    ("the zentar is unstable", "the quorak is fluctuating badly"),          # domain jargon
    ("activate the flummox", "switch on the gribble unit"),                 # domain jargon
]
DISTRACTORS = ["photosynthesis converts light to energy", "glaciers store fresh water",
               "the bakery sells fresh bread", "the river flooded the plain",
               "quarterly revenue increased sharply", "the orchestra tuned up",
               "coral reefs host many fish", "the comet passed near earth"]

# background corpus that TEACHES the synonyms via shared context (grows over rounds)
BACKGROUND = [
    # physician <-> doctor (shared context: patient, hospital, treated, examined)
    "the doctor treated the patient", "the physician treated the patient",
    "the doctor examined the patient at the hospital", "the physician examined the patient at the hospital",
    "the doctor works in the hospital", "the physician works in the hospital",
    # automobile <-> car (shared: engine, road, drove)
    "the car has a powerful engine", "the automobile has a powerful engine",
    "the car drove down the road", "the automobile drove down the road",
    # joyful <-> happy (shared: celebration, smiled)
    "she was happy at the celebration", "she was joyful at the celebration",
    "they smiled because they were happy", "they smiled because they were joyful",
    # zentar <-> quorak (domain: reactor, core, powers)
    "the zentar powers the reactor core", "the quorak powers the reactor core",
    "the zentar sits inside the core", "the quorak sits inside the core",
    # flummox <-> gribble (domain: unit, switch, activate)
    "the flummox unit was switched on", "the gribble unit was switched on",
    "operators activate the flummox daily", "operators activate the gribble daily",
]


def build_assoc(corpus):
    """learn term context vectors from the corpus (distributional semantics)."""
    ctx = defaultdict(Counter)
    for doc in corpus:
        terms = content(doc)
        for i, a in enumerate(terms):
            for j, b in enumerate(terms):
                if i != j:
                    ctx[a][b] += 1
    return ctx


def relatedness(ctx, a, b):
    if a == b:
        return 1.0
    va, vb = ctx.get(a), ctx.get(b)
    if not va or not vb:
        return 0.0
    keys = set(va) | set(vb)
    dot = sum(va[k] * vb[k] for k in keys)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def baseline_score(q, d):
    return cosine(emb.embed(q), emb.embed(d))


def candidate_score(q, d, ctx):
    base = baseline_score(q, d)
    qc, dc = content(q), content(d)
    if not qc or not dc:
        return base
    # synonym bridge: each query term's best corpus-learned relatedness to a doc term
    bridge = sum(max((relatedness(ctx, a, b) for b in dc), default=0.0) for a in qc) / len(qc)
    return base + 0.6 * bridge


def accuracy(scorer, ctx=None):
    docs = [d for _q, d in PAIRS] + DISTRACTORS
    hits = 0
    for q, correct in PAIRS:
        best = max(docs, key=lambda d: (scorer(q, d) if ctx is None else scorer(q, d, ctx)))
        hits += (best == correct)
    return hits / len(PAIRS)


print("=" * 80)
print(" CORPUS-AWARE EMBEDDER — does using accumulated knowledge improve over time?")
print("=" * 80)
base_acc = accuracy(baseline_score)
print(f"\n  BASELINE (fixed embedder, ignores corpus): {base_acc*100:.0f}%  (constant — corpus-blind)")
print("\n  CANDIDATE (learns synonyms from the growing corpus):")
for r, n in [(1, 0), (2, 4), (3, 8), (4, 14), (5, len(BACKGROUND))]:
    ctx = build_assoc(BACKGROUND[:n])
    acc = accuracy(candidate_score, ctx)
    print(f"    round {r}: corpus={n:2} background docs   paraphrase accuracy = {acc*100:4.0f}%")
print("\n" + "-" * 80)
print("  If the candidate RISES with corpus size while baseline stays flat, then YES —")
print("  an embedder that uses accumulated knowledge improves over time (esp. on the")
print("  DOMAIN-JARGON pairs a pretrained model could never know).")
print("-" * 80)
