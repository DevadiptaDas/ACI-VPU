"""
cryptobox - at-rest encryption for the ACI store.

Encryption is keyed by a passphrase (env ACI_PASSPHRASE). The key is derived with
PBKDF2-HMAC-SHA256 over a per-store random salt. Two interchangeable backends:

  * AES (via the `cryptography` package's Fernet) when it is installed  -> scheme "f"
  * a stdlib-only authenticated cipher otherwise                        -> scheme "h"
    (HMAC-SHA256 keystream in counter mode, encrypt-then-MAC with HMAC-SHA256;
     standard primitives composed the standard way - no novel crypto)

Ciphertext is tagged with its scheme, so a store written by one backend stays
readable after the other becomes available (e.g. you later `pip install
cryptography`). This protects the on-device data against disk theft / copies;
embeddings (lossy vectors) are intentionally left unencrypted so recall stays fast.

Threat model: defends data at rest (stolen/copied DB). It is NOT a substitute for
OS login security while the machine is unlocked and the service is running.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os

ITERS = 200_000


def _master(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITERS, dklen=32)


class _StdlibBox:
    """HMAC-SHA256 keystream (CTR) + encrypt-then-MAC. Stdlib only."""
    scheme = "h"

    def __init__(self, passphrase: str, salt: bytes):
        m = _master(passphrase, salt)
        self.enc_key = hmac.new(m, b"aci-enc", hashlib.sha256).digest()
        self.mac_key = hmac.new(m, b"aci-mac", hashlib.sha256).digest()

    def _keystream(self, nonce: bytes, n: int) -> bytes:
        out = bytearray()
        ctr = 0
        while len(out) < n:
            out += hmac.new(self.enc_key, nonce + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
            ctr += 1
        return bytes(out[:n])

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(16)
        ks = self._keystream(nonce, len(plaintext))
        ct = bytes(a ^ b for a, b in zip(plaintext, ks))
        tag = hmac.new(self.mac_key, nonce + ct, hashlib.sha256).digest()
        return nonce + ct + tag

    def decrypt(self, blob: bytes) -> bytes:
        nonce, ct, tag = blob[:16], blob[16:-32], blob[-32:]
        expect = hmac.new(self.mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expect):
            raise ValueError("authentication failed")
        return bytes(a ^ b for a, b in zip(ct, self._keystream(nonce, len(ct))))


class _FernetBox:
    """AES-128-CBC + HMAC via cryptography.Fernet."""
    scheme = "f"

    def __init__(self, passphrase: str, salt: bytes):
        from cryptography.fernet import Fernet  # raises if not installed
        self._f = Fernet(base64.urlsafe_b64encode(_master(passphrase, salt)))

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._f.encrypt(plaintext)

    def decrypt(self, blob: bytes) -> bytes:
        return self._f.decrypt(blob)


class Cipher:
    """Tagged text encryptor: enc(str)->token str, dec(token)->str. Decrypts both
    schemes so the store is portable across backends."""

    def __init__(self, passphrase: str, salt: bytes):
        self.std = _StdlibBox(passphrase, salt)
        try:
            self.fer = _FernetBox(passphrase, salt)
        except Exception:
            self.fer = None
        self.pref = self.fer or self.std
        self.backend = "AES (cryptography)" if self.fer else "HMAC-SHA256 stream (stdlib)"

    def enc(self, s):
        if s is None:
            return None
        blob = self.pref.encrypt(s.encode("utf-8"))
        return self.pref.scheme + ":" + base64.b64encode(blob).decode("ascii")

    def dec(self, s):
        if s is None or not (isinstance(s, str) and len(s) > 2 and s[1] == ":" and s[0] in "fh"):
            return s  # legacy plaintext (pre-encryption rows) pass through
        scheme, blob = s[0], base64.b64decode(s[2:])
        box = self.fer if scheme == "f" else self.std
        if box is None:
            raise ValueError("this store was encrypted with AES; `pip install cryptography` to read it")
        return box.decrypt(blob).decode("utf-8")

    # raw-bytes variants for archived file blobs (scheme tagged as a leading byte)
    def enc_bytes(self, b: bytes) -> bytes:
        if b is None:
            return None
        return self.pref.scheme.encode("ascii") + self.pref.encrypt(b)

    def dec_bytes(self, b: bytes) -> bytes:
        if not b:
            return b
        scheme, body = chr(b[0]), b[1:]
        box = self.fer if scheme == "f" else self.std
        if box is None:
            raise ValueError("this archive was encrypted with AES; `pip install cryptography` to read it")
        return box.decrypt(body)
