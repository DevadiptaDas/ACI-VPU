"""
bench_contextualization.py — PHASE 7: bounded truth-contexts.

A "context" is a region of the field where truth holds coherently, isolated from
other contexts (per project / matter / session). Four checks:

  C1 ISOLATION         — the SAME fact_key with DIFFERENT values in two contexts must
                         coexist (no false cross-context contradiction/supersession).
  C2 SCOPED RECALL     — recall(context=X) returns ONLY X's monads; no bleed from Y.
  C3 NO STARVATION     — a tiny context buried among many unrelated monads is still
                         recalled correctly (global ANN filtering would starve it).
  C4 PER-CTX CONFLICT  — a contradicting update WITHIN a context supersedes the old
                         value there, while the OTHER context is untouched.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/bench_contextualization.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                       # noqa: E402
from aci.embeddings import get_default        # noqa: E402

a = ACI(db_path=":memory:", observer_id="p7", embedder=get_default())


def fact(text, subj, pred, obj, ctx, psi=2.0):
    return a.monadise(text, source_type="KNOWLEDGE", context=ctx,
                      metadata={"subject": subj, "predicate": pred, "object": obj}, truth_value=psi)


print("=" * 84)
print(" PHASE 7 — BOUNDED TRUTH-CONTEXTS")
print("=" * 84)

# C1: same fact, different value, two contexts -> must coexist (no false contradiction)
fact("In matter Alpha, the filing deadline is March 1.", "deadline", "is", "March 1", "matter-alpha")
fact("In matter Beta, the filing deadline is July 9.", "deadline", "is", "July 9", "matter-beta")
alpha_dl = [m for m in a.store.all()
            if a._context_of(m.metadata) == "matter-alpha" and m.metadata.get("status") != "superseded"]
beta_dl = [m for m in a.store.all()
           if a._context_of(m.metadata) == "matter-beta" and m.metadata.get("status") != "superseded"]
c1 = len(alpha_dl) == 1 and len(beta_dl) == 1 and "march" in alpha_dl[0].value.lower()
print(f"\n  C1 isolation: alpha deadline + beta deadline coexist (no false conflict): {c1}")

# fill both contexts with extra, plus a big pile of unrelated global monads
for i in range(6):
    fact(f"Alpha note {i}: the client retained counsel on item {i}.", "alpha", "note", str(i), "matter-alpha")
    fact(f"Beta note {i}: the opposing party filed motion {i}.", "beta", "note", str(i), "matter-beta")
_TOPICS = ["glaciers", "photosynthesis", "sourdough", "comets", "coral reefs", "tax law",
           "violins", "marathons", "honey", "solar panels", "volcanoes", "migration"]
for i in range(60):
    t = _TOPICS[i % len(_TOPICS)]
    a.monadise(f"Archived record {i}: a detailed note about {t} and its effects in year {2000 + i}.",
               source_type="KNOWLEDGE", dedup=False)   # distinct -> genuinely grows the store

# C2: scoped recall returns only the asked context
q = "what is the filing deadline"
alpha_hits = a.recall(q, k=5, context="matter-alpha")
beta_hits = a.recall(q, k=5, context="matter-beta")
a_ok = all(h.monad.metadata.get("context") == "matter-alpha" for h in alpha_hits)
b_ok = all(h.monad.metadata.get("context") == "matter-beta" for h in beta_hits)
a_dl = any("march" in h.monad.value.lower() for h in alpha_hits)
b_dl = any("july" in h.monad.value.lower() for h in beta_hits)
c2 = a_ok and b_ok and a_dl and b_dl
print(f"  C2 scoped recall: alpha->only alpha & finds March={a_dl}; beta->only beta & finds July={b_dl}: {c2}")

# C3: no starvation — the tiny alpha deadline is found despite 60+ unrelated globals
top = a.recall(q, k=1, context="matter-alpha")
c3 = bool(top) and "march" in top[0].monad.value.lower()
print(f"  C3 no starvation: tiny context recalled correctly among {len(a.store.all())} monads: {c3}")

# C4: a contradicting update WITHIN alpha supersedes there; beta untouched
fact("Correction: in matter Alpha the filing deadline is March 15.", "deadline", "is", "March 15",
     "matter-alpha", psi=2.0)
top_a = a.recall(q, k=1, context="matter-alpha")
top_b = a.recall(q, k=1, context="matter-beta")
a_new = bool(top_a) and "march 15" in top_a[0].monad.value.lower()
b_same = bool(top_b) and "july" in top_b[0].monad.value.lower()
c4 = a_new and b_same
print(f"  C4 per-context conflict: alpha updated to March 15={a_new}; beta still July={b_same}: {c4}")

print("\n" + "-" * 84)
ok = c1 and c2 and c3 and c4
print("  VERDICT: BOUNDED CONTEXTS WORK — isolation, scoped recall, no starvation, per-context"
      if ok else "  VERDICT: NEEDS DIAGNOSIS — see checks above.")
print("  conflict. The same memory holds many matters without bleed or false contradiction."
      if ok else "")
print("=" * 84)
