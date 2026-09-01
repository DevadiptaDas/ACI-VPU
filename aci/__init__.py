"""
ACI - Artificial Cognition Infrastructure (reference implementation)

A cognition layer that turns information into MONADS and exposes universal
cognition primitives (monadise, recall, relate, validate, compress, route)
that any consumer - file system, OS, app, sensor, or AI - can call.

This is the stdlib-only Python reference implementation. The core logic is
ported from the AIOS Kotlin engine (Monad, MonadLogicGates, MeaningField,
MultiValuedTruth) with two cleanups:
  1. Formal harmonic logic gates (per "Formal Mathematical System of Monad Logic")
  2. Pluggable embeddings (default lexical; semantic provider drop-in)

Three-product separation note: this is the SUBSTRATE only (storage, retrieval,
math, indexing, audit). The brain layer — MACA learning loop, full extractors,
intent dispatch, lexicon evolution, LLM orchestration — lives in the
`uqrt-mca-nlp` package, which depends on this one. Install both to get full
functionality; install only this for substrate-primitive use.
"""

from .monad import Monad
from .observer import Observer
from .aci import ACI, ValidationResult, RecallHit

__all__ = ["Monad", "Observer", "ACI", "ValidationResult", "RecallHit"]
__version__ = "0.1.0"
