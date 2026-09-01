# ACI-VPU — Artificial Cognition Infrastructure · Virtual Processing Unit

[![CI](https://github.com/DevadiptaDas/ACI-VPU/actions/workflows/ci.yml/badge.svg)](https://github.com/DevadiptaDas/ACI-VPU/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

**A virtual processing unit for cognition.** The way a GPU is a processing unit for graphics, ACI-VPU is one for *memory and understanding* — a layer any AI or program calls to remember, reconcile, and retrieve. It gives an AI private, persistent, provenance-aware memory, so a grounded fact beats a lie repeated five times, and repeated context, inference and cloud calls get reused instead of re-paid.

```bash
pip install aci-vpu
aci-demo
```

Runs offline. No GPU, no API keys. Base install is just `numpy` + `pypdf`.

> ACI-VPU is a **memory and reasoning layer**, not an LLM and not a replacement for one. It's the unit that makes an LLM remember, keep its facts straight, and cost less to run.

---

## The 30-second proof

`aci-demo` stores **one** true fact from a trusted file, then the **same lie five times** from untrusted chats, and asks the memory to check both:

```
MEMORY HOLDS   1 grounded truth  (15 March, from roadmap.pdf)
               the SAME lie x5    (20 April, from unverified chats)

check the LIE  (repeated 5x):   CONTRADICTED   <- caught, despite the repetition
check the TRUTH (grounded 1x):  consistent     <- the grounded fact stands
```

The lie was **newer and five times more frequent** — and ACI-VPU still refuses it, because it weighs claims by **trust and provenance**, not by loudness or recency. A small local model reading this memory answers "15 March" correctly, for free, offline — because the memory did the reconciling the model can't.

A plain vector database (and an LLM reading one) does the opposite: it tends to surface whatever is most recent or most repeated.

---

## Why not just a vector DB / ordinary RAG?

Same embedder, measured side by side (`benchmark/benchmark_vs_vectordb.py`) — so the only thing being compared is the ACI-VPU layer, not the embeddings. Verified with both lexical and real sentence-transformer embeddings, same result:

| Capability | Vector DB | ACI-VPU |
|---|:--:|:--:|
| Semantic retrieval | ✓ | ✓ |
| Returns the **current** value, suppresses a superseded one | — | ✓ |
| Flags a **low-trust rumor** vs a verified fact | — | ✓ (conf 0.70 vs 0.20) |
| Detects **contradiction** between claims | — | ✓ |
| **Provenance weighting** (who said it, how much you trust them) | — | ✓ |
| **Deduplicates** repeated content (5 copies → 1 stored) | — | ✓ (2.8 KB vs 13.8 KB) |
| **Explainable trace** for every answer | — | ✓ |

The wins come from truth values (ψ), contradiction detection, truth-aware supersession, and dedup — not from a better embedder.

---

## What ACI-VPU is NOT

- **not an LLM** and not a replacement for one
- **not a vector database** (it uses one for coarse recall, then reconciles on top)
- **not a perfect document-to-knowledge-graph extractor** — auto-extraction is high-precision on cleanly-stated facts, ~50% on messy/OCR'd docs (see [Limitations](#limitations))
- **not lossless compression through embeddings** — stored meaning is lossy; byte-exact restore comes from a separate compressed blob
- **not an autonomous agent** — it's a memory and validation layer that agents call

---

## Privacy — the default, not a setting

**Your memory stays on your device.** ACI-VPU is a local service; nothing leaves your machine unless you wire it to. On top of that: at-rest encryption (`ACI_PASSPHRASE`, stdlib cipher out of the box, AES with `[secure]`), a **global pause** for all capture, a **consent ledger** to block any source, one-click **forget**, an **audit trail**, and **secret redaction** — credentials, API keys and tokens are masked or skipped before they can ever be stored.

---

## How it works

Everything is a **monad**: a unit of information carrying a graded truth value (ψ), provenance, entropy, and links to other monads. Six primitives operate on it (`aci/aci.py`):

| Primitive | What it does |
|---|---|
| `monadise` | turn raw info into a structured monad (+ dedup + compression) |
| `recall` | retrieve by meaning (semantic + truth + recency + graph neighbours) |
| `relate` | link monads in the meaning field |
| `validate` | check a statement vs memory → contradiction + confidence + explainable trace |
| `compress` | storage/compression stats |
| `route` | decide where a task should run (local vs cloud) |

The truth algebra is a small canonical gate set (`NOT = 1/ψ`, `AND`, `OR`, `XOR = contradiction distance`, `IMPLIES`), internally consistent and test-enforced (see `CANON_GATES.md`). A refinement loop settles beliefs toward self-consistency (`ψ → 1`).

**Observer-relative truth.** `recall` and `validate` can rank by *observer-effective truth* — ψ × the observer's trust in the source — over only what an observer is allowed to see, keeping cross-source conflicts as competing claims rather than silently overwriting them. This is the mechanism that lets one shared knowledge base serve different roles differently. By default semantic similarity leads the ranking; strengthening trust so it re-orders results (a legal view vs a sales view of the same KB) is a configurable weighting.

---

## What you get

The full engine, from `pip install aci-vpu`:

1. **Persistent memory** — `monadise`, on-device SQLite store, dedup, encryption.
2. **Truth / provenance engine** — contradiction detection, supersession, confidence, explainable traces.
3. **Semantic retrieval** — vectorized top-k + meaning-graph neighbours; lexical by default, add `[semantic]` for embeddings.
4. **Optimization** — reuse of context, inference and storage, from the same `monadise` op (see below).
5. **MCP + SDK** — give it to any AI.

```bash
aci monadise "My accountant is Sarah Chen."
aci recall  "accountant"
aci validate "Helios ships on 20 April."   # -> contradiction + trace
aci stats                                    # health + compression
aci forget <id>                              # right to be forgotten
```

---

## Give it to any AI (MCP)

`aci-mcp` is a **zero-dependency** MCP server (newline-delimited JSON-RPC over stdio) that exposes your ACI-VPU to any MCP-capable AI — Claude, Claude Code, Cursor. It needs no extra installs.

```bash
aci-mcp            # the stdio server — point your AI client's config at this
aci-mcp-setup      # one-shot: register ACI-VPU with Claude Desktop / Cursor
aci-doctor         # health check: install + MCP import + protocol handshake
```

Nine tools: `aci_recall`, `aci_remember`, `aci_validate`, `aci_ingest`, `aci_post_work`, `aci_team_activity`, `aci_find_skills`, `aci_save_skill`, `aci_skill_outcome`. The AI reads and writes *your* memory every session instead of starting blank, and states when it did (`✦ via ACI-VPU`), so you can see why an answer is trustworthy.

**SDK / HTTP:** Python `from aci.client import ACIClient`; JavaScript `clients/aci.js`; or plain HTTP/JSON against the local service (`GET /openapi.json`). Set `ACI_API_KEY` to gate it.

---

## Optimization — real, but workload-dependent (read the qualifier)

Because storing a monad already deduplicates and compresses, the same engine cuts cost. `benchmark/benchmark_optimization.py` reports these on a **redundant / known workload**:

| Lever | Reduction *(on redundant/known workloads)* |
|---|--:|
| Stored representation | ~98% |
| Repeated inference (cached) | ~90% |
| Context tokens (grounded build) | ~92% |
| Compute gating (entropy-value) | ~80% |
| Cloud calls (local routing) | ~60% |

> **Read this before quoting the numbers.** These are best cases on **repetitive / known** data. On **fully novel** workloads the savings trend to **~0%** — there's nothing to reuse. And stored monads are **lossy** (they keep meaning, not exact bytes). The honest claim is: *ACI-VPU reduces repeated context, inference and storage on workloads that contain real redundancy* — which most production AI workloads do — not "98% off everything."

---

## Extensions (optional)

All on-device, all opt-in — thin layers over the same memory:

- **Browser capture** — a Chromium extension folds the pages you actually read into the same searchable memory (`clients/browser-extension/`).
- **Device optimization** — read-only device health + a duplicate-file finder with reclaimable-space report (`aci device`, `aci dupes`).
- **Memory Compressor** — keep a losslessly LZMA-compressed, dedup'd copy of a folder's originals *and* a semantic index; delete the originals, restore byte-exact later (`aci archive` / `aci restore`, SHA-256 verified).
- **Shared skills** — reusable declarative know-how stored as `SKILL` monads; confidence earned from outcomes, better versions supersede once proven. One AI writes a skill, another finds it (`aci_find_skills` / `aci_save_skill` / `aci_skill_outcome`).
- **Always-on autonomy** — point it at a folder once; it re-syncs itself and runs on login (`aci watch`, `aci autostart`).
- **Observation (off by default)** — active-window / clipboard / OCR / email connectors, all consent-gated, pausable, encrypted, with secret redaction.

Extras: `pip install "aci-vpu[semantic]"` (embeddings), `[nlp]`, `[secure]` (AES), `[scale]` (ANN index), or `[full]`.

---

## Limitations

Stated plainly, because they decide whether ACI-VPU fits your use:

- **Auto-extraction is best-effort.** Turning raw prose or PDFs into clean subject-predicate-object facts is high-precision on cleanly-stated sentences but ~50% on messy/OCR'd documents. Contradiction and supersession are most reliable on facts you **state or tag**.
- **Stored monads are lossy.** They preserve meaning, not exact bytes. Byte-exact recovery is only via the Memory Compressor's separate compressed blob.
- **Optimization savings are workload-dependent** — they trend to ~0% on fully novel data.
- **Observer-partition is a configurable weighting**, not strong by default.

---

## Run from source

```bash
pip install -e ".[full]"                              # everything: semantic + ANN + AES
py -m unittest discover -s tests                      # validation tests
py benchmark/benchmark_vs_vectordb.py                 # ACI-VPU vs a real vector DB
ACI_EMBEDDER=st py benchmark/benchmark_vs_vectordb.py # same, with real embeddings
py benchmark/benchmark_optimization.py                # the optimization numbers above
```

## License

Apache-2.0. ACI-VPU is the *memory and reasoning layer* — it makes any AI remember, keep its facts straight, and cost less to run; it doesn't make the model smarter on its own.
