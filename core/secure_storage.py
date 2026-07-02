# core/secure_storage.py
"""
Encrypts config secrets at rest using Windows DPAPI (CurrentUser scope), so
config.json can't be read in plaintext by another OS user account, a stray
backup, or anything else with file access but not this Windows login.

DPAPI ties the ciphertext to the logged-in Windows user — no key file to
manage or lose. Non-Windows / DPAPI-unavailable environments fall back to
storing values as-is (base64, unencrypted) rather than crashing the app.
"""

import base64
import ctypes
import sys
from ctypes import wintypes

MARKER = "dpapi:"

_available = sys.platform == "win32"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf  # buf must stay alive as long as blob is used


def _dpapi_protect(data: bytes) -> bytes:
    blob_in, _keepalive = _make_blob(data)
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    blob_in, _keepalive = _make_blob(data)
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def encrypt(plaintext: str) -> str:
    """Encrypt a string for storage. Returns a "dpapi:<base64>" marker string."""
    if not plaintext:
        return plaintext
    raw = plaintext.encode("utf-8")
    if _available:
        try:
            raw = _dpapi_protect(raw)
        except Exception:
            pass
    return MARKER + base64.b64encode(raw).decode("ascii")


def decrypt(stored: str) -> str:
    """Reverse of encrypt(). Values without the marker are returned unchanged
    (backward compatibility with configs written before encryption existed)."""
    if not isinstance(stored, str) or not stored.startswith(MARKER):
        return stored
    raw = base64.b64decode(stored[len(MARKER):].encode("ascii"))
    if _available:
        try:
            raw = _dpapi_unprotect(raw)
        except Exception:
            return stored  # can't decrypt (different user/machine) — leave opaque
    return raw.decode("utf-8", errors="replace")


def is_sensitive_key(key: str) -> bool:
    """Heuristic: does this config key name hold a secret?"""
    k = key.lower()
    return any(s in k for s in (
        "password", "pass", "apikey", "api_key", "token", "secret",
    ))
