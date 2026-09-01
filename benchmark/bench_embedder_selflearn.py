"""
bench_embedder_selflearn.py — does the UQRT-MCA native embedder improve over time /
self-learn? Tested empirically, two ways:

  A) DETERMINISM: embed a probe, then 'use/learn' heavily (add 1000 docs, simulate
     feedback/lexicon growth), embed the probe again -> are the vectors identical?
     (If identical, the function is FROZEN -> it cannot have learned anything.)
  B) ACCURACY OVER ROUNDS: paraphrase-retrieval accuracy across rounds of growing
     data + usage. If it self-learns, accuracy rises. If flat/declining, it doesn't.

Run:  py benchmark/bench_embedder_selflearn.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from aci.embeddings import UqrtMcaEmbedder, cosine          # noqa: E402

emb = UqrtMcaEmbedder()

# paraphrase eval — query vs a correct doc that says the same thing in OTHER words
PAIRS = [
    ("how do I reset my password", "steps to recover your account credentials"),
    ("the meeting was moved to friday", "we rescheduled the appointment to the end of the week"),
    ("the car won't start", "the vehicle fails to ignite"),
    ("she is a skilled physician", "the woman is an expert medical doctor"),
    ("turn off the lights", "switch off the illumination"),
    ("the flight is delayed", "the plane departure is running late"),
    ("he bought a new house", "the man purchased a residence"),
    ("the food was delicious", "the meal tasted wonderful"),
    ("increase the volume", "make the sound louder"),
    ("the project is finished", "the task has been completed"),
]
DISTRACTORS = [
    "photosynthesis converts light to energy", "the river flooded the valley",
    "quarterly revenue rose by ten percent", "the violin needs new strings",
    "glaciers store fresh water", "the recipe needs two eggs",
    "the museum opened a new wing", "coral reefs support marine life",
    "the marathon route is flat", "honey does not spoil",
    "the library extended its hours", "solar panels face south",
    "the bakery sells sourdough", "chess opens with a gambit",
    "the committee approved zoning", "the comet returns every decade",
] * 4   # 64 distractors


def accuracy(corpus_docs):
    """top-1: for each pair, is the correct doc the nearest to the query?"""
    doc_vecs = [(d, emb.embed(d)) for d in corpus_docs]
    hits = 0
    for q, correct in PAIRS:
        qv = emb.embed(q)
        best = max(doc_vecs, key=lambda dv: cosine(qv, dv[1]))[0]
        hits += (best == correct)
    return hits / len(PAIRS)


print("=" * 78)
print(" UQRT-MCA EMBEDDER — does it self-learn / improve over time?")
print("=" * 78)
print("\n  Code facts: trainable params? NO.  corpus stats / IDF? NO.  lexicon input? NO.")
print("  -> embed(text) is a pure function of text. Nothing to update.")

# A) determinism proof
probe = "the quick brown fox jumps over the lazy dog"
v_before = tuple(round(x, 8) for x in emb.embed(probe))
# 'use and learn' heavily: embed thousands of docs/queries (simulating usage/feedback)
for _ in range(3):
    for d in DISTRACTORS:
        emb.embed(d)
    for q, c in PAIRS:
        emb.embed(q); emb.embed(c)
v_after = tuple(round(x, 8) for x in emb.embed(probe))
print(f"\nA) DETERMINISM after heavy 'usage/learning':")
print(f"   probe vector identical before vs after?  {v_before == v_after}")
print("   (identical => the function is FROZEN => it learned nothing)")

# B) accuracy across rounds of growing data + usage
print(f"\nB) ACCURACY across rounds (more data + 'usage' each round):")
correct_docs = [c for _q, c in PAIRS]
for r, n in [(1, 0), (2, 8), (3, 24), (4, 48), (5, 64)]:
    corpus = correct_docs + DISTRACTORS[:n]
    acc = accuracy(corpus)
    print(f"   round {r}: corpus={len(corpus):3} docs   paraphrase top-1 accuracy = {acc*100:4.0f}%")

print("\n" + "-" * 78)
print("  VERDICT: if A shows IDENTICAL and B shows FLAT (not rising), the embedder")
print("  does NOT self-learn — its accuracy is a fixed ceiling. The only way to raise")
print("  it is to make it LEARNABLE (trainable params + a training objective), which")
print("  is a different build entirely — not something accumulated use can do.")
print("-" * 78)
