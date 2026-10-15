"""What the program keeps that is a secret - the cookies of a sign-in - sealed with DPAPI of Windows.

DPAPI (CryptProtectData) seals bytes for the account of Windows that sealed them: another account, another machine or a
copy of the folder cannot open them, and the program holds no key of its own. The cookies of a browser are live sessions
in plain text; what the program keeps of them is config\\cookies.dpapi, opened for a run of yt-dlp into a file of its own
and sealed again after it (yt-dlp writes back the cookies it was given, renewed).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# A word of the program mixed into the seal: another program of the same account does not open it by chance.
ENTROPY = b"Audion Media Tools - cookies"
# No window of Windows may ask anything: a run has nobody to answer it.
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call(protect: bool, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is a part of Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    given, held = _blob(data)
    entropy, held_entropy = _blob(ENTROPY)
    out = _Blob()
    if protect:
        done = crypt32.CryptProtectData(ctypes.byref(given), "Audion Media Tools", ctypes.byref(entropy), None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    else:
        done = crypt32.CryptUnprotectData(ctypes.byref(given), None, ctypes.byref(entropy), None, None,
                                          CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not done:
        raise OSError(f"DPAPI refused to {'seal' if protect else 'open'} the data: Windows error {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
        del held, held_entropy


def seal(data: bytes) -> bytes:
    """The bytes sealed for this account of Windows."""
    return _call(True, data)


def open_sealed(data: bytes) -> bytes:
    """The bytes a seal of this account of Windows holds; OSError for a seal of another account or a damaged one."""
    return _call(False, data)
