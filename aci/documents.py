"""
Document loading for REAL files: plain text, Word (.docx), PDF.

- txt/md/etc : read directly
- .docx      : stdlib zip + XML (no dependency)
- .pdf       : pypdf (pure-python, preferred) -> pdftotext (poppler) fallback

Plus chunk(): split long documents into monad-sized pieces.
Self-contained: no external API, no LLM.
"""
from __future__ import annotations
import html
import os
import re
import shutil
import subprocess

# no console flash when shelling out to helper exes (Windows)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
import zipfile
from pathlib import Path
from typing import List

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".log", ".json", ".yaml", ".yml"}
SUPPORTED_EXT = TEXT_EXT | {".docx", ".pdf"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}


def load_text(path) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return p.read_text(encoding="utf-8", errors="ignore")
        if ext == ".docx":
            return _docx(p)
        if ext == ".pdf":
            return _pdf(p)
    except Exception:
        return ""
    return ""


def _docx(p: Path) -> str:
    z = zipfile.ZipFile(str(p))
    x = z.read("word/document.xml").decode("utf-8", "ignore")
    x = re.sub(r"</w:p>", "\n", x)
    x = re.sub(r"<w:tab/>", "\t", x)
    x = re.sub(r"<[^>]+>", "", x)
    return html.unescape(x)


def _pdf(p: Path) -> str:
    try:                                   # pure-python, portable
        import pypdf
        reader = pypdf.PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    except Exception:
        pass
    exe = shutil.which("pdftotext")        # poppler fallback if present
    if exe:
        try:
            return subprocess.run([exe, str(p), "-"], capture_output=True,
                                  text=True, timeout=120, creationflags=_NO_WINDOW).stdout
        except Exception:
            return ""
    return ""


_SMALL_WORDS = {"a", "an", "the", "of", "to", "for", "and", "or", "in", "on", "with",
                "we", "had", "ones", "that", "is", "are", "by", "as", "at", "vs"}


def _is_heading(line: str) -> bool:
    """A section header: short, no terminal punctuation, and (markdown # or
    Title Case - most significant words capitalized). This separates category
    headers ('Security Intelligence') from list items ('Malware detection')."""
    l = line.strip()
    if not l or len(l) > 64:
        return False
    if l.startswith("#"):
        return True
    if l[-1] in ".!?,;":
        return False
    words = [w for w in re.split(r"\s+", l) if w]
    if not (2 <= len(words) <= 8):
        return False
    significant = [w for w in words if w.lower().strip(":-") not in _SMALL_WORDS]
    if not significant:
        return False
    capped = sum(1 for w in significant if w[:1].isupper())
    return capped >= 2 and capped / len(significant) >= 0.6


def chunk(text: str, max_chars: int = 900, overlap: int = 0) -> List[str]:
    """Split a document into focused, monad-sized chunks.

    Structure-aware: starts a new chunk at each detected section header (so a
    taxonomy/list yields one chunk per subsection, not one giant blurry chunk),
    and caps chunk size, carrying the section header into continuation chunks for
    context. Falls back to size-based line packing for header-less prose.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    cur: List[str] = []
    header = None

    def cur_len():
        return sum(len(x) + 1 for x in cur)

    def flush():
        body = "\n".join(cur).strip()
        if body:
            chunks.append(body)

    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if _is_heading(ln):
            flush()
            cur = [ln]
            header = ln
        elif cur and cur_len() + len(ln) > max_chars:
            flush()
            cur = [header, ln] if header else [ln]   # carry header for context
        else:
            cur.append(ln)
    flush()

    # merge a header-only chunk into the following one
    merged: List[str] = []
    for c in chunks:
        if merged and "\n" not in merged[-1] and _is_heading(merged[-1]):
            merged[-1] = merged[-1] + "\n" + c
        else:
            merged.append(c)

    # hard-split anything still over the cap (e.g. one very long line)
    out: List[str] = []
    for c in merged:
        if len(c) <= max_chars:
            out.append(c)
        else:
            step = max(1, max_chars - overlap)
            for i in range(0, len(c), step):
                out.append(c[i:i + max_chars])
    return [c for c in out if c.strip()]
