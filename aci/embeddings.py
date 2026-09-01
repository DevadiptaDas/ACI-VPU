"""
Embeddings - pluggable.

Default = LexicalEmbedder: stdlib-only hashing of tokens + char trigrams,
L2-normalized. No dependencies, runs anywhere. It captures lexical/word overlap
but NOT deep semantics.

For production semantics, drop in SemanticEmbedder (sentence-transformers) by
passing a different provider to ACI(...). The rest of the system is unchanged.
This is the "real embeddings are pluggable" cleanup vs. the hard-coded hash
embeddings in the live Android code.
"""

from __future__ import annotations
import math
import re
from typing import List

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 1]


class LexicalEmbedder:
    name = "lexical-hash-v1"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            vec[hash(tok) % self.dim] += 1.0
            for i in range(len(tok) - 2):
                shard = tok[i:i + 3]
                vec[hash(shard) % self.dim] += 0.35
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# Note: hash() is randomized per-process by default. For a stable store across
# runs we seed determinism by disabling hash randomization in the entrypoints
# (PYTHONHASHSEED=0) OR by using a stable hash here:
def _stable_hash(s: str) -> int:
    h = 1469598103934665603
    for ch in s:
        h ^= ord(ch)
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


class StableLexicalEmbedder(LexicalEmbedder):
    """Deterministic across processes (FNV-1a hash) so stored embeddings stay valid."""
    name = "lexical-stable-v1"

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            vec[_stable_hash(tok) % self.dim] += 1.0
            for i in range(len(tok) - 2):
                vec[_stable_hash(tok[i:i + 3]) % self.dim] += 0.35
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


class SentenceTransformerEmbedder:
    """Real semantic embeddings via sentence-transformers (if installed).
    Captures paraphrase/synonymy that the lexical embedder cannot."""
    name = "sentence-transformers"

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import
        self._model = SentenceTransformer(model)
        try:
            self.dim = self._model.get_embedding_dimension()      # newer API
        except AttributeError:
            self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> List[float]:
        v = self._model.encode(text or "", normalize_embeddings=True)
        return v.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vs = self._model.encode([t or "" for t in texts], normalize_embeddings=True,
                                batch_size=64)
        return [v.tolist() for v in vs]


_STOPWORDS = set((
    "the a an of to in on for and or but is are was were be been being it its this "
    "that these those with as at by from into about over under i you he she we they "
    "my your his her our their me him them do does did have has had will would can "
    "could should what which who whom how when where why not no yes if then than"
).split())


class UqrtMcaEmbedder:
    """UQRT-MCA-native embedder (Phase 19). Deterministic, dependency-free.

    Encodes text into the meaning-field organised by the 4-weight matrix bands:
      [object]  content tokens (what it's about)
      [concept] content tokens in a separate concept projection
      [monad]   char-trigrams (subword structure / morphology)
      [event]   adjacent-token bigrams (relational structure)
    Each band scaled by its default weight (W_O, W_C, W_M, W_E). Captures lexical
    + subword + short-phrase overlap with NO model download — but, being
    derivational rather than learned, it does not capture deep synonymy the way a
    trained semantic model does. (Benchmark vs sentence-transformers to see the gap.)
    """
    name = "uqrt-mca-v1"

    def __init__(self, dim: int = 384):
        self.dim = dim
        q = dim // 4
        self.bands = [(0, q), (q, 2 * q), (2 * q, 3 * q), (3 * q, dim)]
        self.bw = [0.6, 0.5, 1.0, 0.6]   # object, concept, monad, event weights

    def _bucket(self, s: str, lo: int, hi: int) -> int:
        return lo + (_stable_hash(s) % (hi - lo))

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        toks = tokenize(text)
        if not toks:
            return vec
        content = [t for t in toks if t not in _STOPWORDS] or toks
        lo, hi = self.bands[0]                                  # object
        for t in content:
            vec[self._bucket(t, lo, hi)] += self.bw[0]
        lo, hi = self.bands[1]                                  # concept
        for t in content:
            vec[self._bucket("c:" + t, lo, hi)] += self.bw[1]
        lo, hi = self.bands[2]                                  # monad / subword
        for t in toks:
            for i in range(len(t) - 2):
                vec[self._bucket(t[i:i + 3], lo, hi)] += self.bw[2] * 0.35
        lo, hi = self.bands[3]                                  # event / bigram
        for i in range(len(toks) - 1):
            vec[self._bucket(toks[i] + "_" + toks[i + 1], lo, hi)] += self.bw[3]
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


class OpenAIEmbedder:
    """Real semantic embeddings via the OpenAI API (needs OPENAI_API_KEY)."""
    name = "openai"

    def __init__(self, model: str = "text-embedding-3-small"):
        from openai import OpenAI  # lazy import
        self._client = OpenAI()
        self._model = model
        self.dim = 1536

    def embed(self, text: str) -> List[float]:
        r = self._client.embeddings.create(model=self._model, input=text or " ")
        return r.data[0].embedding


def embed_many(embedder, texts: List[str]) -> List[List[float]]:
    """Embed many texts, using the embedder's batched path when it has one
    (sentence-transformers is far faster batched), else falling back to a loop."""
    fn = getattr(embedder, "embed_batch", None)
    if fn is not None:
        return fn(texts)
    return [embedder.embed(t) for t in texts]


def get_default():
    """Provider selection.

    DEFAULT = local semantic model (sentence-transformers, runs in the backend,
    no external API/LLM). Downloads once (~90MB) then cached. This is the right
    default for the product: real meaning-based recall on real data.

    Overrides via ACI_EMBEDDER:
      lexical  -> stdlib lexical (offline, deterministic; used for tests/CI)
      openai   -> OpenAI embeddings (needs OPENAI_API_KEY)
      st/auto  -> local semantic (the default)
    Falls back to lexical automatically if the semantic model is unavailable."""
    import os
    choice = os.environ.get("ACI_EMBEDDER", "auto").lower()
    if choice == "lexical":
        return StableLexicalEmbedder()
    if choice in ("uqrt-mca", "uqrt", "native", "monad"):
        return UqrtMcaEmbedder()
    try:
        if choice == "openai":
            return OpenAIEmbedder()
        return SentenceTransformerEmbedder()      # auto / st / semantic / default
    except Exception as e:
        print(f"[ACI] semantic embedder unavailable ({e}); falling back to lexical. "
              f"(install sentence-transformers, or set ACI_EMBEDDER=lexical to silence)")
        return StableLexicalEmbedder()
