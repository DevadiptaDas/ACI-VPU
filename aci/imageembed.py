"""
CLIP image+text embeddings - semantic photo/image search (multimodal, #1).

CLIP maps images AND text into ONE shared vector space, so a text query like
"sunset over water" can retrieve matching photos. Uses sentence-transformers'
clip-ViT-B-32 (sentence-transformers is already a dependency); needs Pillow to load
images. Optional: if Pillow / the CLIP model aren't available it degrades to None
and image features are simply off (text search is unaffected).

    pip install pillow        # then first image use downloads the CLIP model once
"""
from __future__ import annotations

_clip = None
_tried = False


class ClipEmbedder:
    name = "clip-ViT-B-32"
    dim = 512

    def __init__(self):
        import PIL  # noqa: F401  (fail fast if Pillow missing)
        from sentence_transformers import SentenceTransformer
        self._m = SentenceTransformer("clip-ViT-B-32")

    def embed_image(self, path: str):
        from PIL import Image
        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            return None
        return self._m.encode(img, normalize_embeddings=True).tolist()

    def embed_text(self, text: str):
        return self._m.encode(text or "", normalize_embeddings=True).tolist()


def get_clip():
    """Lazy singleton; returns None (once) if CLIP/Pillow unavailable."""
    global _clip, _tried
    if _clip is None and not _tried:
        _tried = True
        try:
            _clip = ClipEmbedder()
        except Exception:
            _clip = None
    return _clip
