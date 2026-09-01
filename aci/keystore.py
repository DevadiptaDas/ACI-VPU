"""
OS keystore for the at-rest encryption key (Phase 3 / F4).

So the passphrase doesn't have to live in a plaintext env var or script: store it
once, protected by Windows DPAPI (tied to the logged-in Windows account), and the
service loads it automatically. Stdlib ctypes, no dependency. macOS/Linux: returns
None (fall back to ACI_PASSPHRASE; Keychain/secret-service backends come later).

    aci set-key --passphrase "..."   # protect + save (once)
    # thereafter the service decrypts automatically, no env var needed
"""
from __future__ import annotations
import os

_DEFAULT = os.path.join(os.path.expanduser("~"), ".aci", "key.dpapi")


def _win() -> bool:
    return os.name == "nt"


def protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    bin_, bout = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(bout)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(bout.pbData, bout.cbData)
    finally:
        kernel32.LocalFree(bout.pbData)


def unprotect(blob: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(bytes(blob), len(blob))
    bin_, bout = BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(bout)):
        raise OSError("CryptUnprotectData failed (wrong Windows account?)")
    try:
        return ctypes.string_at(bout.pbData, bout.cbData)
    finally:
        kernel32.LocalFree(bout.pbData)


def save_passphrase(passphrase: str, path: str = _DEFAULT) -> str:
    if not _win():
        raise OSError("OS keystore currently supports Windows (DPAPI); use ACI_PASSPHRASE elsewhere.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(protect(passphrase.encode("utf-8")))
    return path


def load_passphrase(path: str = _DEFAULT):
    if not _win() or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return unprotect(f.read()).decode("utf-8")
    except Exception:
        return None
