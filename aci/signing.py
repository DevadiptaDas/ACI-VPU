"""
SignedMonad — Ed25519 cryptographic provenance for monads.

Every monad written by this node is signed with the node's Ed25519 private key
over a canonical (content-hash, subject, predicate, object, observer, timestamp)
message. This turns "who said what" from an advisory metadata field into a fact
you can VERIFY — the foundation for poison-resistance and cross-node/cross-vendor
trust: a monad whose signature does not verify against its claimed signer is
forged and must not be trusted, no matter what truth-value it claims.

- Node identity: an Ed25519 keypair, generated on first use and stored under
  ~/.aci/ (private key protected with Windows DPAPI when available, else a
  0600 file). The public key hex IS the signer id.
- Additive & backwards-compatible: legacy/unsigned monads verify as None
  ("unsigned"), never as invalid. Signing is on by default (ACI_SIGN=0 disables).
- Standard primitives only (Ed25519 via `cryptography`); no novel crypto. If the
  `cryptography` package is unavailable, signing degrades to a no-op (cid only).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional, Tuple

_IDENT = None            # cached (private_key, public_hex)


def _dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".aci")
    os.makedirs(d, exist_ok=True)
    return d


def _key_path() -> str:
    return os.path.join(_dir(), "node_ed25519.key")


def _save_private(raw: bytes) -> None:
    """Persist the raw 32-byte private key, DPAPI-protected on Windows."""
    path = _key_path()
    data = raw
    if os.name == "nt":
        try:
            from . import keystore
            data = b"DPAPI\x00" + keystore.protect(raw)
        except Exception:
            data = raw
    with open(path, "wb") as f:
        f.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_private() -> Optional[bytes]:
    path = _key_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data.startswith(b"DPAPI\x00"):
            from . import keystore
            return keystore.unprotect(data[6:])
        return data
    except Exception:
        return None


def available() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
        return True
    except Exception:
        return False


def get_identity():
    """Return (private_key, public_hex). Loads the node key or generates one."""
    global _IDENT
    if _IDENT is not None:
        return _IDENT
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption)
    sk = None
    raw = _load_private()
    if raw:
        try:
            sk = Ed25519PrivateKey.from_private_bytes(raw)
        except Exception:
            sk = None
    if sk is None:
        sk = Ed25519PrivateKey.generate()
        _save_private(sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    _IDENT = (sk, pub)
    return _IDENT


def signer_id() -> str:
    try:
        return get_identity()[1]
    except Exception:
        return ""


def content_id(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _canonical(content: str, metadata: dict, observer_id: str, timestamp) -> Tuple[str, bytes]:
    md = metadata or {}
    cid = content_id(content)
    payload = json.dumps(
        {"cid": cid, "s": (md.get("subject") or ""), "p": (md.get("predicate") or ""),
         "o": (md.get("object") or ""), "obs": (observer_id or ""), "ts": int(timestamp or 0)},
        sort_keys=True, separators=(",", ":"))
    return cid, payload.encode("utf-8")


def sign(content: str, metadata: dict, observer_id: str, timestamp) -> Tuple[str, str, str]:
    """Return (cid, signer_hex, sig_hex). On any failure returns (cid, "", "")."""
    cid = content_id(content)
    try:
        sk, pub = get_identity()
        _, msg = _canonical(content, metadata, observer_id, timestamp)
        return cid, pub, sk.sign(msg).hex()
    except Exception:
        return cid, "", ""


def verify(content: str, metadata: dict, observer_id: str, timestamp,
           signer_hex: str, sig_hex: str) -> Optional[bool]:
    """True = signature valid; False = INVALID (forged/tampered); None = unsigned."""
    if not signer_hex or not sig_hex:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        _, msg = _canonical(content, metadata, observer_id, timestamp)
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signer_hex))
        try:
            pk.verify(bytes.fromhex(sig_hex), msg)
            return True
        except InvalidSignature:
            return False
    except Exception:
        return None
