"""
benchmark_graph_recall.py — the HARD, fair test of whether the meaning-field graph
beats plain vector search (ST), in the cases where it actually should:

  • TWO parallel chains with near-identical vocabulary (a real one + a decoy),
    so cosine alone CANNOT tell which fact connects to which — only the edges can.
  • a disambiguation query (answer is in chain A; chain B is a lexical twin)
  • an entity-anchor query with a lexical gap (upstream facts don't share words)

If the graph helps anywhere, it's here. If it doesn't beat ST even here, that's
the honest verdict.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/benchmark_graph_recall.py
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")
os.environ["ACI_DB"] = tempfile.mktemp(suffix=".db")

from aci.aci import ACI                                   # noqa: E402

aci = ACI(observer_id="test")

# Chain A (the TRUE chain) and Chain B (a DECOY with the same sentence shapes /
# vocabulary). Cosine sees A and B facts as near-identical; only edges disambiguate.
CHAIN_A = [
    ("a1", "Alice Romero manages Bob Tan."),
    ("a2", "Bob Tan leads the Helios program."),
    ("a3", "The Helios program uses the Aurora drive."),
    ("a4", "The Aurora drive was built by Priya Menon."),
]
CHAIN_B = [
    ("b1", "Carol Diaz manages Dan Park."),
    ("b2", "Dan Park leads the Vega program."),
    ("b3", "The Vega program uses the Comet drive."),
    ("b4", "The Comet drive was built by Sam Lee."),
]
DISTRACTORS = [
    "The recipe needs two cups of flour.", "Rainfall peaks in the wet season.",
    "Solar panels convert sunlight to electricity.", "The startup raised a seed round.",
    "Coral reefs support many marine species.", "The bakery sells sourdough daily.",
    "Honey never spoils when sealed.", "The chess opening was a queen's gambit.",
    "Glaciers store most fresh water.", "The museum opened an impressionist wing.",
    "A balanced diet includes protein.", "The committee approved the zoning.",
]

ids = {}
for key, text in CHAIN_A + CHAIN_B:
    ids[key] = aci.monadise(text, source_type="KNOWLEDGE").id
for text in DISTRACTORS:
    aci.monadise(text, source_type="KNOWLEDGE")

# edges = the relationships a usage/feedback loop would learn (chain-internal only)
def wire():
    for x, y in (("a1", "a2"), ("a2", "a3"), ("a3", "a4"),
                 ("b1", "b2"), ("b2", "b3"), ("b3", "b4")):
        aci.relate(ids[x], ids[y], "ASSOCIATIVE")


def topk(query, hops, k=5):
    return [(h.monad.value, round(h.score, 3)) for h in aci.recall(query, k=k, graph_hops=hops)]


def rank_of(query, hops, needle, k=8):
    res = [v for v, _ in topk(query, hops, k)]
    for i, v in enumerate(res):
        if needle.lower() in v.lower():
            return i + 1
    return None


print("=" * 86)
print(f" HARD GRAPH-RECALL TEST — 2 lexically-identical chains + {len(DISTRACTORS)} distractors")
print("=" * 86)

print("\n--- BEFORE edges (pure ST vector search) ---")
Q1 = "Who built the drive used by the program Bob leads?"
print(f"QUERY: {Q1!r}   (correct = Priya Menon; Sam Lee is the decoy)")
for v, s in topk(Q1, 0):
    print(f"    {s:>6}  {v}")
priya0, sam0 = rank_of(Q1, 0, "Priya"), rank_of(Q1, 0, "Sam Lee")
print(f"  ST-only ranks -> Priya(correct): {priya0}   Sam Lee(decoy): {sam0}")

print("\n--- AFTER edges (ST + meaning-field graph, hops=1) ---")
wire()
for v, s in topk(Q1, 1):
    print(f"    {s:>6}  {v}")
priya1, sam1 = rank_of(Q1, 1, "Priya"), rank_of(Q1, 1, "Sam Lee")
print(f"  graph ranks   -> Priya(correct): {priya1}   Sam Lee(decoy): {sam1}")

# entity-anchor query with a lexical gap
Q2 = "Priya Menon"
up0 = rank_of(Q2, 0, "Helios program uses", k=6)
up1 = rank_of(Q2, 1, "Helios program uses", k=6)
print(f"\nQUERY: {Q2!r}  (can it surface the upstream 'Helios uses Aurora' fact? no shared words)")
print(f"  ST-only rank of upstream fact: {up0}   |   graph rank: {up1}")

print("\n" + "-" * 86)
def better(correct, decoy):
    if correct is None: return "MISS"
    if decoy is None: return "win (decoy absent)"
    return "win" if correct < decoy else "tie/lose"
print(f"  Disambiguation (Priya over Sam Lee):  ST={better(priya0,sam0)}   graph={better(priya1,sam1)}")
print(f"  Lexical-gap upstream recall:          ST rank={up0}   graph rank={up1}")
print("=" * 86)
