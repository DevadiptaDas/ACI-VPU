"""
Auto-extraction: raw text -> (subject, predicate, object) + entities.

ACI-VPU ships a REAL, dependency-free heuristic extractor built in, so the
crown-jewel behaviour (fact-level contradiction / supersession) works standalone
with no manual tagging and no extra packages. When the richer UQRT-MCA NLP
extractor (spaCy / local-LLM) is installed it is preferred automatically via the
same `extract()` interface; otherwise this stdlib heuristic is used (NOT a no-op).

Degrades gracefully: if no confident triple is found, returns just entities and
the monad still works for recall — it just won't participate in fact-level
contradiction until tagged or re-extracted by a stronger extractor.
"""
from __future__ import annotations
import os
import re
from typing import Dict, List

COPULA = {"is", "are", "was", "were", "be", "been", "being"}
WH = {"who", "what", "where", "when", "why", "how", "which", "whose", "whom"}
ARTICLES = {"the", "a", "an", "my", "your", "our", "their", "his", "her", "its",
            "this", "that", "these", "those"}
PREPS = {"on", "at", "by", "to", "in", "of", "for", "from", "with"}
SUBJ_STOP = WH | {"it", "this", "that", "there", "here", "i", "you", "we", "they",
                  "he", "she", "one", "user"}

_ENT = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b")
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*\s?(?:dollars|usd|rupees|inr|eur)\b",
                    re.IGNORECASE)
_WORD = re.compile(r"[a-zA-Z0-9]+")

# ---- fact-quality gate: keep document-prose fragments OUT of the fact layer ----
GENERIC_SUBJECT = {
    "page", "pages", "content", "contents", "document", "documents", "section", "sections",
    "paragraph", "paragraphs", "para", "clause", "clauses", "list", "lists", "point", "points",
    "line", "lines", "part", "parts", "item", "items", "note", "notes", "chapter", "table",
    "figure", "file", "files", "text", "word", "words", "sentence", "sentences", "heading",
    "title", "footer", "header", "thing", "things", "something", "anything", "everything",
    "nothing", "fact", "facts", "matter", "matters", "copy", "copies", "order", "orders",
    "background", "summary", "detail", "details",
}
WEAK_ABSTRACT = {
    "unable", "unclear", "clear", "evident", "obvious", "true", "false", "correct",
    "incorrect", "wrong", "right", "bad", "good", "fine", "doubt", "doubtful", "aware",
    "sure", "unsure", "ready", "present", "absent", "applicable", "relevant", "irrelevant",
    "valid", "invalid", "void", "similar", "different", "same", "such", "various", "certain",
    "uncertain", "able", "necessary", "possible", "important", "purported", "alleged",
}
_FACT_STOP = ARTICLES | PREPS | COPULA | WH | SUBJ_STOP | {
    "and", "or", "but", "not", "no", "as", "so", "if", "then", "than", "also", "very", "to",
}
ANAPHORIC = {
    "aforesaid", "aforementioned", "abovementioned", "above", "said", "foregoing",
    "former", "latter", "same", "such", "similar", "instant", "present", "impugned",
    "respective", "hereinabove", "subject",
}
GENERIC_HEAD = GENERIC_SUBJECT | {
    "direction", "directions", "view", "views", "submission", "submissions",
    "contention", "contentions", "reason", "reasons", "purpose", "purposes",
    "issue", "issues", "aspect", "aspects", "respect", "regard", "case", "cases",
}
_NUM = re.compile(r"\d")
_VOWELS = set("aeiouy")
_ABBR_OK = {"mr", "mrs", "ms", "dr", "jr", "sr", "st", "co", "ltd", "pvt", "inc", "llp",
            "plc", "corp", "mfg", "mgmt", "dept", "govt", "vs", "no", "pp",
            "smt", "sh", "shri", "kum", "ku", "md"}


def _toks(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _garbled(phrase: str) -> bool:
    """OCR/extraction noise: stray single letters, vowelless word-fragments, punctuation runs."""
    for t in _toks(phrase):
        if len(t) == 1 and t.isalpha() and t not in ("a", "i"):
            return True
        if len(t) >= 2 and t.isalpha() and t not in _ABBR_OK and not (set(t) & _VOWELS):
            return True
    return bool(re.search(r"[^\w\s]{2,}", phrase or ""))


def _has_proper_noun(phrase: str, original: str) -> bool:
    for t in _toks(phrase):
        if len(t) >= 2 and re.search(r"\b" + re.escape(t[0].upper() + t[1:]) + r"\b", original or ""):
            return True
    return False


def is_registerable_fact(subject: str, predicate: str, obj: str, original: str = "") -> bool:
    """True iff an auto-extracted triple is clean enough to enter the FACT layer
    (contradiction / supersession). Otherwise it stays as content only."""
    s, o = (subject or "").strip().lower(), (obj or "").strip().lower()
    if not s or not o or s == o:
        return False
    if _garbled(subject) or _garbled(obj):
        return False
    s_toks = _toks(s)
    if s_toks and all(t in GENERIC_SUBJECT or t in _FACT_STOP for t in s_toks):
        return False
    if s_toks and s_toks[0] in ANAPHORIC:
        return False
    if s_toks and s_toks[-1] in GENERIC_HEAD:
        return False
    specific = _has_proper_noun(obj, original) or bool(_NUM.search(o))
    first_content = next((t for t in _toks(o) if t not in _FACT_STOP), None)
    if first_content in WEAK_ABSTRACT and not specific:
        return False
    contentful = [t for t in _toks(o)
                  if len(t) >= 3 and t not in _FACT_STOP and t not in WEAK_ABSTRACT]
    if not contentful and not specific:
        return False
    return True


_GROUND_FLOOR = 0.6


def _content(phrase: str) -> list:
    return [t for t in _toks(phrase)
            if len(t) >= 3 and t not in _FACT_STOP and t not in WEAK_ABSTRACT]


def _grounding_score(subject: str, obj: str, source: str) -> float:
    """Sentence-local faithfulness: object must be supported in a source sentence that
    also mentions the subject (catches relation hallucinations)."""
    subj_c, obj_c = _content(subject), _content(obj)
    if not subj_c or not obj_c:
        return 1.0
    best = 0.0
    for sent in re.split(r"(?<=[.!?])\s+|\n+", source or ""):
        st = set(_toks(sent))
        if not any(t in st for t in subj_c):
            continue
        best = max(best, sum(1 for t in obj_c if t in st) / len(obj_c))
        if best >= 1.0:
            break
    return best


def _gate(out: Dict, text: str) -> Dict:
    """Drop a triple that fails the quality gate (keep entities). Env kill-switches:
    ACI_FACT_GATE (structure) and ACI_GROUNDING (faithfulness)."""
    if os.environ.get("ACI_FACT_GATE", "on").lower() == "off":
        return out
    if not (out.get("subject") and out.get("predicate")):
        return out

    def _drop():
        for k in ("subject", "predicate", "object", "grounding"):
            out.pop(k, None)
        return out

    if not is_registerable_fact(out["subject"], out["predicate"], out.get("object", ""), text):
        return _drop()
    if os.environ.get("ACI_GROUNDING", "on").lower() != "off":
        g = _grounding_score(out["subject"], out.get("object", ""), text)
        src = set(_toks(text))
        subj_content = [t for t in _toks(out["subject"])
                        if len(t) >= 3 and t not in _FACT_STOP]
        subj_grounded = (not subj_content) or any(t in src for t in subj_content)
        if g < _GROUND_FLOOR or not subj_grounded:
            return _drop()
        out["grounding"] = round(g, 3)
    return out


class HeuristicExtractor:
    """Self-contained stdlib subject/predicate/object + entity extractor. No deps."""
    name = "heuristic-spo-v1"

    def extract(self, text: str) -> Dict:
        out: Dict = {"entities": self._entities(text)}
        first = re.split(r"(?<=[.!?])\s+", text.strip())[0] if text.strip() else ""
        out.update(self._triple(first))
        return _gate(out, text)

    def _entities(self, text: str) -> List[str]:
        ents = [m for m in _ENT.findall(text) if m.lower() not in SUBJ_STOP and len(m) > 1]
        ents += _MONEY.findall(text)
        seen, dedup = set(), []
        for e in ents:
            if e.lower() not in seen:
                seen.add(e.lower())
                dedup.append(e)
        return dedup[:8]

    def _triple(self, sent: str) -> Dict:
        s = sent.strip().rstrip(".!?")
        if not s or sent.strip().endswith("?"):
            return {}
        words = [w for w in _WORD.findall(s.lower())]
        if not words or words[0] in WH:
            return {}
        # Pattern A: copula  ->  "<subject...> <predicate-attr> is/are <object>"
        cop = next((i for i, w in enumerate(words) if w in COPULA), None)
        if cop is not None:
            left = [w for w in words[:cop] if w not in ARTICLES]
            right = [w for w in words[cop + 1:] if w not in ARTICLES]
            return self._assemble(left, right, default_pred="is")
        # Pattern B: verb + preposition  ->  "<subject...> <verb> on/at/by <object>"
        for i, w in enumerate(words):
            if w in PREPS and 0 < i < len(words) - 1:
                left = [x for x in words[:i] if x not in ARTICLES]
                right = [x for x in words[i + 1:] if x not in ARTICLES]
                if len(left) >= 2:
                    return self._assemble(left, right, default_pred=left[-1])
        return {}

    @staticmethod
    def _assemble(left: List[str], right: List[str], default_pred: str) -> Dict:
        if not left or not right or left[0] in SUBJ_STOP:
            return {}
        if len(left) >= 2:
            subject, predicate = " ".join(left[:-1]), left[-1]
        else:
            subject, predicate = left[0], default_pred
        obj = " ".join(right)
        if subject in SUBJ_STOP or not obj:
            return {}
        return {"subject": subject, "predicate": predicate, "object": obj}


class NoopExtractor:
    """Legacy no-op (kept for tests / explicit opt-out via ACI_EXTRACTOR=noop)."""
    name = "noop-stub"

    def extract(self, text: str) -> Dict:
        return {"entities": []}


def get_extractor():
    """Return the active extractor. Order:
      1. explicit ACI_EXTRACTOR override (noop | heuristic)
      2. the richer UQRT-MCA NLP extractor when installed (spaCy / local-LLM)
      3. the built-in stdlib HeuristicExtractor (default — the USP works standalone)."""
    mode = os.environ.get("ACI_EXTRACTOR", "").lower()
    if mode == "noop":
        return NoopExtractor()
    if mode == "heuristic":
        return HeuristicExtractor()
    if os.environ.get("ACI_DISABLE_NLP_EXTRACTOR", "0") != "1":
        try:
            from uqrt_mca_nlp.extract import get_extractor as nlp_get_extractor
            return nlp_get_extractor()
        except Exception:
            pass
    return HeuristicExtractor()
