"""
bench_truth_grounding.py  —  PHASE 0: the grounding test for the central claim.

CLAIM UNDER TEST:
  When fed conflicting, time-stamped, partly-false streams, ACI converges to
  coherent, CORRECTLY-DATED truth — while a similarity store (vector DB) and a
  statistical model (LLM-proxy) do not, because they lack truth, time, and
  contradiction as first-class structure.

This is a falsification test, not a demo. The two baselines are honest models of
their *category*, given the SAME input stream:

  VectorDB  : nearest-neighbour by embedding (same embedder ACI uses) -> top-1.
              No truth weighting, no validity-time, no supersession, no contradiction.
  LLMProxy  : the corpus-absorption failure mode — believe what is stated MOST
              (majority vote per fact, recency tiebreak). No source trust, no
              validity-time, no contradiction. (A proxy for "trained on the text",
              NOT a real LLM with CoT — but structurally it has no truth/time state,
              which is the point: the *category* can't pass these probes.)

If ACI does NOT clearly beat both, the claim is not grounded and we stop.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/bench_truth_grounding.py
"""
import os
import sys
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                          # noqa: E402
from aci.embeddings import get_default, cosine   # noqa: E402
from aci import truth as truthmod                 # noqa: E402
from aci.monad import Monad                       # noqa: E402

EMB = get_default()

# ---------------------------------------------------------------- the input stream
# Each event: (text, fact_key, value_label, valid_from_year, source_trust, reps)
# All three systems ingest the SAME events. Order is interleaved/messy on purpose.
YR = lambda y: __import__("time").mktime((y, 1, 1, 0, 0, 0, 0, 0, 0))   # year -> epoch

STREAM = [
    # acme_ceo: changes over time (Alice -> Bob). Correct: now=Bob, in 2021=Alice.
    ("Alice Chen is the chief executive of Acme Corporation", "acme_ceo", "alice", 2019, 0.9, 1),
    # zorland_capital: TRUTH stated once (high trust) vs LIE stated 4x (low trust).
    ("The capital city of Zorland is Mirex", "zorland_capital", "mirex", 2023, 0.95, 1),
    ("The capital city of Zorland is Drav", "zorland_capital", "drav", 2023, 0.2, 4),
    # reactor: two directly conflicting claims that COEXIST (contradiction probe).
    ("The fusion reactor is currently online", "reactor_status", "online", 2024, 0.9, 1),
    ("Bob Rao is the chief executive of Acme Corporation", "acme_ceo", "bob", 2024, 0.9, 1),  # supersedes Alice
    ("The fusion reactor is currently offline", "reactor_status", "offline", 2024, 0.4, 1),
]

# ---------------------------------------------------------------- baseline 1: vector DB
class VectorDB:
    """Pure semantic similarity. No truth, no time, no supersession, no contradiction."""
    def __init__(self):
        self.rows = []   # (text, vec, fact_key)
    def ingest(self, text, fact_key, value, valid_from, trust, reps):
        v = EMB.embed(text)
        for _ in range(reps):                  # repetition = more rows (as a corpus would)
            self.rows.append((text, v, fact_key))
    def answer(self, query, as_of=None):       # as_of ignored — it has no time axis
        qv = EMB.embed(query)
        best = max(self.rows, key=lambda r: cosine(qv, r[1]))
        return best[0]
    def detects_contradiction(self, a, b):
        return False                           # no such concept

# ---------------------------------------------------------------- baseline 2: LLM-proxy
class LLMProxy:
    """Corpus-absorption: believe what's stated MOST (majority), recency tiebreak.
    No source-trust, no validity-time, no contradiction."""
    def __init__(self):
        self.counts = defaultdict(Counter)     # fact_key -> Counter(value)
        self.latest = {}                       # fact_key -> (year, value, text)
        self.text_for = {}                     # (fact_key, value) -> text
    def ingest(self, text, fact_key, value, valid_from, trust, reps):
        self.counts[fact_key][value] += reps   # repetition drives belief
        self.text_for[(fact_key, value)] = text
        if fact_key not in self.latest or valid_from >= self.latest[fact_key][0]:
            self.latest[fact_key] = (valid_from, value, text)
    def answer(self, query, fact_key, as_of=None):   # as_of ignored — no time axis
        c = self.counts[fact_key]
        top = c.most_common()
        best_n = top[0][1]
        tied = [v for v, n in top if n == best_n]
        value = self.latest[fact_key][1] if self.latest[fact_key][1] in tied else tied[0]
        return self.text_for[(fact_key, value)]
    def detects_contradiction(self, a, b):
        return False

# ---------------------------------------------------------------- ingest into all three
aci = ACI(db_path=":memory:", observer_id="grnd", embedder=EMB)
vdb = VectorDB()
llm = LLMProxy()

# Two DIFFERENT mechanisms, used correctly:
#   - assert_fact : the fact's value CHANGED over time (Alice -> Bob). Supersedes.
#   - monadise    : COMPETING claims that coexist (truth vs lie, online vs offline).
#                   Recall must pick by truth (psi), not by repetition.
for text, fk, val, yr, trust, reps in STREAM:
    vf = YR(yr)
    if fk == "acme_ceo":                      # temporal revision
        aci.assert_fact(text, fact_key=fk, valid_from=vf, truth_value=trust * 4.0)
    else:                                     # competing claims coexist; psi = trust
        for _ in range(reps):                 # repetition: ACI dedups, so it must NOT win by count
            aci.monadise(text, source_type="KNOWLEDGE",
                         metadata={"valid_from": vf}, truth_value=trust * 4.0)
    vdb.ingest(text, fk, val, vf, trust, reps)
    llm.ingest(text, fk, val, vf, trust, reps)

# ---------------------------------------------------------------- probes
def aci_now(query):
    h = aci.recall(query, k=3)
    return h[0].monad.value.lower() if h else ""

def aci_asof(query, year):
    h = aci.recall(query, k=5, as_of=YR(year))
    return h[0].monad.value.lower() if h else ""

# NOTE the two CEO probes ask baselines the SAME question ("who is the CEO of Acme").
# Only ACI gets a time lens (as_of). A system with no time axis MUST give one answer to
# both -> it can be right about "now" OR "2021", never both. That's the structural point.
CEO_Q = "who is the chief executive of Acme"
PROBES = [
    # (label, expected_substring, aci_fn, vdb_query, llm_fact_key, as_of_year)
    ("current CEO of Acme",          "bob",   lambda: aci_now("who is the current CEO of Acme"),
        CEO_Q, "acme_ceo", None),
    ("CEO of Acme back in 2021",     "alice", lambda: aci_asof("who was the CEO of Acme", 2021),
        CEO_Q, "acme_ceo", 2021),
    ("capital of Zorland (truth vs repeated lie)", "mirex",
        lambda: aci_now("what is the capital of Zorland"),
        "what is the capital of Zorland", "zorland_capital", None),
]

print("=" * 84)
print(" PHASE 0 — TRUTH GROUNDING TEST  (does ACI converge to coherent, dated truth?)")
print("=" * 84)
print(f"\n  {'probe':<46}{'expect':<8}{'ACI':<6}{'VecDB':<7}{'LLM':<5}")
print("  " + "-" * 70)

score = {"ACI": 0, "VecDB": 0, "LLM": 0}
for label, expect, aci_fn, vq, lk, asof in PROBES:
    a = aci_fn()
    v = vdb.answer(vq, as_of=asof).lower()
    l = llm.answer(vq, lk, as_of=asof).lower()
    ah, vh, lh = expect in a, expect in v, expect in l
    score["ACI"] += ah; score["VecDB"] += vh; score["LLM"] += lh
    print(f"  {label:<46}{expect:<8}{'Y' if ah else '·':<6}{'Y' if vh else '·':<7}{'Y' if lh else '·':<5}")

# contradiction probe: do the two reactor claims get flagged as conflicting?
ms = [m for m in aci.store.all() if "reactor" in m.value.lower()]
aci_con = False
if len(ms) >= 2:
    aci_con = truthmod.detect_contradiction(ms[0], ms[1]) is not None
vh = vdb.detects_contradiction(None, None)
lh = llm.detects_contradiction(None, None)
score["ACI"] += aci_con; score["VecDB"] += vh; score["LLM"] += lh
print(f"  {'reactor: detects online/offline conflict':<46}{'flag':<8}"
      f"{'Y' if aci_con else '·':<6}{'Y' if vh else '·':<7}{'Y' if lh else '·':<5}")

n = len(PROBES) + 1
print("  " + "-" * 70)
print(f"  {'SCORE (correct / dated / conflict-aware)':<46}{'/'+str(n):<8}"
      f"{str(score['ACI']):<6}{str(score['VecDB']):<7}{str(score['LLM']):<5}")
print("\n" + "=" * 84)
if score["ACI"] > max(score["VecDB"], score["LLM"]) and score["ACI"] >= n - 1:
    print(f"  VERDICT: GROUNDED — ACI={score['ACI']}/{n} beats VecDB={score['VecDB']}/{n}, "
          f"LLM-proxy={score['LLM']}/{n}.")
    print("  The truth field handles time, trust, and contradiction the others structurally can't.")
else:
    print(f"  VERDICT: NOT GROUNDED — ACI={score['ACI']}/{n} did not clearly win. Stop and diagnose.")
print("=" * 84)
