# Canonical Monad Logic Gates (authoritative)

Phase 0 fixed an inconsistency: the gate definitions disagreed across the source
documents. This file is the **single authoritative algebra**. The ACI code
(`aci/logic_gates.py`) implements exactly this, and the theory docs should be
reconciled to it.

## The canonical set

Truth values are continuous, observer-relative: `ψ ∈ (0, ∞)`, with `ψ = 1` the
self-consistent fixed point.

| Gate | Definition | Notes |
|------|------------|-------|
| `NOT(t)` | `1 / t` | involution: `NOT(NOT(t)) = t`; fixed point at `t = 1` |
| `AND(a,b)` | `a·b / (a+b)` = `1/(1/a + 1/b)` | conservative fusion (parallel-resistor / half-harmonic) |
| `OR(a,b)` | `a + b` | cumulative evidence; **unbounded** — normalize with σ/log for [0,1] |
| `XOR(a,b)` | `|a − b|` | contradiction distance (0 = agreement) |
| `IMPLIES(a,b)` | `NOT(a) OR b` = `1/a + b` | material implication |
| `σ(t)` | `1 / (1 + e^−t)` | probability view |
| `log_compress(t)` | `log(1 + t)` | density control |

## Why this set (the consistency proof)

Pick `NOT(t) = 1/t` (forced — it's the only simple involution with fixed point 1)
and `AND(a,b) = ab/(a+b)`. Then **OR is forced by De Morgan**:

```
OR(a,b) = NOT( AND( NOT a, NOT b ) )
        = NOT( (1/a · 1/b) / (1/a + 1/b) )
        = NOT( 1 / (a+b) )
        = a + b
```

So `OR = a + b` is not a free choice — it is the De Morgan dual of the harmonic
AND. This is why we reject the other variants found in the docs.

## Reconciliation — what to change in the theory docs

| Document | Currently says | Change to |
|----------|----------------|-----------|
| `Formal Monad Logic.docx` | OR = `t1 + t2` ✅, AND = `t1t2/(t1+t2)` ✅ | already canonical — keep |
| Patent `form 2.docx` | OR = `max(t1,t2)` ❌ | OR = `t1 + t2` |
| `Logic Gates.pdf` | OR = `(t1+t2)/2` ❌ | OR = `t1 + t2` |
| `Codes.docx` / `Sample Codes.docx` | AND = `2/(1/t1+1/t2)` ❌ (factor 2), OR = add/max | AND = `t1t2/(t1+t2)`, OR = `t1 + t2` |

`NOT` and `XOR` are already consistent everywhere.

## Note on bounds
`OR` (and therefore `IMPLIES`) is intentionally unbounded — it represents
accumulating evidence. Use `σ(ψ)` for a [0,1] probability or `log_compress(ψ)`
to keep magnitudes controlled, exactly as the Formal Monad Logic doc specifies.

## Phase-preserving complex extension (`NOT_c`, `refine_truth_c`)

When a belief carries a **direction** — a phase `θ` for its qualitative stance, not
just a magnitude — the negation that keeps the direction and only inverts the
magnitude is:

```
NOT_c(z) = 1 / conj(z)          for z = r·e^{iθ}  ⇒  (1/r)·e^{iθ}
```

- Fixed-point **set** = the whole unit circle `|z| = 1` (every fully-consistent
  stance), generalizing the scalar fixed point `ψ = 1`.
- Involution: `NOT_c(NOT_c(z)) = z`. Restricting to the real axis (`θ = 0`)
  reproduces `NOT` and `refine_truth` exactly.
- Revision loop: `z_{n+1} = (1−α)·z_n + α·(1/conj(z_n))` relaxes the magnitude to 1
  while **preserving the phase** — confidence self-corrects, content is not erased.

**Trap (do not use `1/z`):** the naive `1/z = (1/r)·e^{−iθ}` conjugates the phase, so
iterating a revision loop with it flips `θ` each step and collapses every belief onto
the real axis (±1), destroying direction. Only `1/conj(z)` has the unit circle as its
fixed set. (Locked in `tests/test_canon_math.py::TestComplexGates`.)
