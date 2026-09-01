# CANON_MATH — the UQRT-MCA equations ACI actually runs (Phase 0 spec)

This is the **single source of truth** for the math. The code in `aci/` is checked
against it by `tests/test_canon_math.py` (equations are assertions, so the build
cannot silently drift from the framework). Everything here is *extracted from the
current implementation* — nothing aspirational.

Items marked **⬜ SIGN-OFF** are free parameters/choices I picked defensibly; you
confirm or change them and the tests + code update to match.

---

## 1. Truth space
Truth value **ψ ∈ [0, ∞)**, continuous and observer-relative:
- ψ → 0 : false / unreliable
- ψ = 1 : **self-consistent fixed point** (equal pull of a claim and its negation)
- ψ → ∞ : absolutely true (a limit, never reached)

`normalized_truth(ψ) = σ(ψ)` maps to (0,1) for probability-style use.

## 2. Canonical gates (`aci/logic_gates.py`)
| Gate | Equation | Meaning |
|---|---|---|
| NOT | `NOT(ψ) = 1/ψ` | dialectical inversion; **involution**: NOT(NOT ψ)=ψ |
| AND | `AND(a,b) = a·b/(a+b) = 1/(1/a+1/b)` | conservative evidence fusion (harmonic) |
| OR  | `OR(a,b) = a+b` | cumulative evidence (unbounded; normalize for probability) |
| XOR | `XOR(a,b) = |a−b|` | contradiction distance (0 = agreement) |
| IMPLIES | `IMPLIES(a,b) = NOT(a) OR b = 1/a + b` | material implication, De Morgan-consistent |
| σ | `σ(ψ) = 1/(1+e^−ψ)` | probability view |
| log_compress | `log(1+ψ)` | tame huge ψ |

**De Morgan identity (enforced by test):** `NOT(AND(NOT a, NOT b)) = a+b = OR(a,b)`.

## 3. The Liar paradox / paradox resolution (the core claim)
The Liar ("this statement is false") is the fixed point of negation. With `NOT(ψ)=1/ψ`:
> ψ = NOT(ψ) = 1/ψ  ⟹  ψ² = 1  ⟹  **ψ = 1.**

So the Liar doesn't explode or oscillate — it **resolves to the stable value ψ = 1**
(held, not collapsed). The MACA refinement *dynamically* relaxes any ψ to this point:
```
refine(ψ): ψ_{n+1} = (1−α)·ψ_n + α·(1/ψ_n)        → converges to ψ = 1
```
(`refine_truth`, α default 0.2.) This is the operational form of "hold the paradox as
a bounded stable state." **⬜ SIGN-OFF:** default α = 0.2; convergence target ψ = 1.

## 4. MACA cycle — Model → Act → Check → Adjust (`aci/maca.py`)
- **Model:** copy the monad (hypothesis under test).
- **Act (dialectic):** `ψ ← AND(ψ, NOT(ψ))`; entropy += 0.05. (Confront claim with its inverse.)
- **Check (reality):** given `score = reality_check(m) ∈ [0,1]`:
  `ψ ← ψ · adj`, where **adj = 1.2 if score ≥ 0.7, 1.0 if score ≥ 0.3, else 0.8**;
  entropy ← max(entropy − 0.1·score, 0).
- **Adjust:** `ψ ← refine(ψ, α, iters=2)` with **α = 0.4 if ψ<0.5, 0.1 if ψ>1.5, else 0.2**;
  if ψ>10 then `ψ ← log_compress(ψ)`; entropy ×= 0.95.
- **Stop:** `run_until_stable` halts when |Δψ| < tol (0.01) or after max_cycles (5).

**⬜ SIGN-OFF:** reality thresholds (0.7 / 0.3), adj factors (1.2 / 1.0 / 0.8),
α schedule (0.4 / 0.1 / 0.2), log-compress trigger (ψ>10), entropy steps.

## 5. Entropy S (`ACI._entropy`)
Shannon entropy of the token distribution, normalized to [0,1]:
`S = H/H_max`, `H = −Σ p·log₂ p`, `H_max = log₂(#distinct)`. Empty → 0.5.
Interpretation: ambiguity / number of competing meanings.

## 6. Observer-relative truth (`aci/observer.py`)
- `trust_for(m)` = trust[source_type] if set, else trust[owner] if set, else **1.0**.
- `can_see(m)` = True if `visible is None`, or owner ∈ {self.id} ∪ visible ∪ {"global","shared"}.
- **Observer-effective truth: `ψ_eff = σ(ψ · trust)`** — the same KB yields different
  rankings per observer. **⬜ SIGN-OFF:** composition is *multiplicative* (ψ·trust)
  inside σ. (Alternative we could use: σ(ψ)·trust. Pick one.)

## 7. Recall score (`ACI.recall`)
For each candidate over what the observer `can_see`:
```
recency   = exp(−age_days / half_life)              # half_life = 30 days
ψ_eff     = σ(ψ · trust)
score     = 0.6·sim + 0.2·ψ_eff + 0.2·recency + graph_bonus
graph_bonus = 0.3 if the monad is a 1-hop meaning-field neighbour of a top hit
```
Superseded monads excluded unless `include_superseded`. **⬜ SIGN-OFF:** weights
**0.6 / 0.2 / 0.2**, graph_bonus **0.3**, half_life **30 d**, candidate pool = max(6k, 40).

## 8. Deduplication (`ACI._find_duplicate`, monadise merge)
A new monad merges into an existing one iff `cosine ≥ dedup_threshold` **and** it is
**not** a same-`subject::predicate`/different-`object` factual update (those must flow to
§9, not be merged). On merge: `weight += 1`, `ψ ← min(ψ + 0.1·ψ_new, 50)`, `entropy ×= 0.9`.
**⬜ SIGN-OFF:** dedup_threshold **0.93**, ψ reinforcement **+0.1·ψ_new**, cap **50**.

## 9. Supersession (`ACI._supersede`)
Same `subject::predicate`, different `object`, **and** `same_source` **and**
`more_credible (ψ_new ≥ ψ_old)` ⟹ demote the old: `ψ_old ×= 0.3`, mark `status=superseded`,
link `SUPERSEDES`. **Cross-source or less-credible conflicts are NOT superseded** — they
are kept as **competing claims**, resolved per-observer at query time (§6). **⬜ SIGN-OFF:**
demotion factor **0.3**; the same-source + ≥-truth gate.

## 10. Contradiction detection (`aci/truth.py`)
- **Fact-level:** same `subject::predicate`, different `object` → contradiction, interference = 1.0.
- **Semantic-level:** `topical = max(cosine(emb), jaccard(keywords))`; if `topical ≥ 0.35`
  **and** opposing polarity (one side has a negation word: not/no/never/false) **and**
  `topical ≥ 0.5` → contradiction via `XOR(ψ_a, ψ_b)`. **⬜ SIGN-OFF:** thresholds **0.35 / 0.5**.

## 11. Validate — truth-aware (`ACI.validate`)
Recall related monads; a contradiction **undermines** the statement only if the
conflicting evidence is **equal-or-higher effective truth**: `ψ_eff(r) ≥ ψ_cand`. A
conflict with a *lower*-truth claim makes the **other** one the suspect (subordinate,
non-undermining). `is_consistent = (no undermining conflicts)`.
`confidence = min(1, 0.5 + 0.1·ψ_cand)` if consistent, else `max(0, 0.3 − 0.1·#undermining)`.
**⬜ SIGN-OFF:** the confidence formula constants.

## 12. Information-thermodynamics (`logic_gates.energy_cost`, `Monad.energy_cost`)
- Operation energy: **dE = κ · dC · dS · (ds²/c²)** (generalized Landauer), with
  coupling `κ = (1+ξ)/(1+S)` (ξ = contextual complexity).
- Monad energy: `E = k_B · ln2 · S · ψ`. (Landauer-anchored; used for entropy-gated compute.)

---

## Free-parameter summary (the sign-off list)
| # | Parameter | Current value |
|---|---|---|
| 3 | refine α (paradox relax) | 0.2 |
| 4 | MACA reality thresholds / adj | 0.7,0.3 / 1.2,1.0,0.8 |
| 4 | MACA adjust α schedule | 0.4 / 0.1 / 0.2 |
| 6 | observer composition | σ(ψ·trust) |
| 7 | recall weights | 0.6 sim / 0.2 truth / 0.2 recency |
| 7 | graph_bonus / half_life | 0.3 / 30 d |
| 8 | dedup_threshold / ψ reinforce / cap | 0.93 / +0.1·ψ / 50 |
| 9 | supersession demotion | ×0.3 (same-source, ≥-truth) |
| 10 | contradiction thresholds | 0.35 / 0.5 |
| 11 | validate confidence | 0.5+0.1ψ / 0.3−0.1n |

Change any value here → update the matching constant in code + the assertion in
`tests/test_canon_math.py`. That keeps math, code, and spec provably in lockstep.
