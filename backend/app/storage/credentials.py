"""User-scoped Windows DPAPI. No plaintext fallback or exception detail escapes."""

import ctypes
import os
from ctypes import wintypes

from app.storage.errors import ProjectError


class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, decrypt: bool) -> bytes:
    code = "CREDENTIAL_UNAVAILABLE" if decrypt else "CREDENTIAL_ENCRYPTION_FAILED"
    if os.name != "nt":
        raise ProjectError(code, 503)
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        function.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        source = Blob(len(value), buffer)
        result = Blob()
        # CRYPTPROTECT_UI_FORBIDDEN only: never CRYPTPROTECT_LOCAL_MACHINE.
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise ProjectError(code, 503)
        try:
            return ctypes.string_at(result.data, result.length)
        finally:
            kernel32.LocalFree(result.data)
    except Exception:
        raise ProjectError(code, 503) from None


def protect(value: bytes) -> bytes:
    return _crypt(value, False)


def unprotect(value: bytes) -> bytes:
    return _crypt(value, True)
