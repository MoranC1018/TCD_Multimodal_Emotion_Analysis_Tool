"""Windows user-scoped credential storage backed by DPAPI."""

from __future__ import annotations

import ctypes
import hashlib
import os
import threading
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x1
MAX_SECRET_BYTES = 64 * 1024
SECRET_FILENAMES = {
    "youtubeApiKey": "youtube_api_key.bin",
    "huggingFaceToken": "huggingface_token.bin",
}
_LOCK = threading.RLock()


class CredentialStoreUnavailable(RuntimeError):
    """The current platform cannot provide user-protected credential storage."""


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def store_secret(settings_path: Path, name: str, value: str) -> None:
    """Encrypt and atomically persist one nonblank secret for the current user."""

    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("Credential values must not be blank.")
    raw = cleaned.encode("utf-8")
    if len(raw) > MAX_SECRET_BYTES:
        raise ValueError(f"Credential exceeds {MAX_SECRET_BYTES} bytes.")
    encrypted = protect_for_current_user(raw, entropy_for_settings(settings_path))
    path = secret_path(settings_path, name)
    with _LOCK:
        atomic_write_bytes(path, encrypted)


def load_secret(settings_path: Path, name: str) -> str:
    """Decrypt one stored secret for the current Windows user."""

    path = secret_path(settings_path, name)
    with _LOCK:
        try:
            encrypted = path.read_bytes()
        except FileNotFoundError:
            return ""
    if not encrypted:
        return ""
    raw = unprotect_for_current_user(encrypted, entropy_for_settings(settings_path))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialStoreUnavailable(f"Stored credential is not valid UTF-8: {path}") from exc


def delete_secret(settings_path: Path, name: str) -> None:
    """Remove every encrypted file for one credential name."""

    path = secret_path(settings_path, name)
    with _LOCK:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass


def secret_path(settings_path: Path, name: str) -> Path:
    try:
        file_name = SECRET_FILENAMES[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported credential name: {name}") from exc
    return credential_scope_directory(settings_path) / file_name


def credential_scope_directory(settings_path: Path) -> Path:
    """Return an outside-repository directory unique to this settings file."""

    override = str(os.getenv("MEA_CREDENTIAL_STORE_ROOT") or "").strip()
    if override:
        base = Path(override).expanduser().resolve()
    else:
        local_app_data = str(os.getenv("LOCALAPPDATA") or "").strip()
        if not local_app_data:
            local_app_data = str(Path.home() / "AppData" / "Local")
        base = Path(local_app_data).expanduser().resolve() / "MultimodalEmotionAnalysisTool" / "Credentials"
    scope_text = os.path.normcase(str(settings_path.expanduser().resolve())).encode("utf-8")
    scope_id = hashlib.sha256(scope_text).hexdigest()[:24]
    return base / scope_id


def entropy_for_settings(settings_path: Path) -> bytes:
    canonical = os.path.normcase(str(settings_path.expanduser().resolve())).encode("utf-8")
    return hashlib.sha256(b"MultimodalEmotionAnalysisTool\0" + canonical).digest()


def protect_for_current_user(raw: bytes, entropy: bytes) -> bytes:
    crypt32, kernel32 = windows_dpapi_libraries()
    input_blob, input_buffer = make_blob(raw)
    entropy_blob, entropy_buffer = make_blob(entropy)
    output_blob = DataBlob()
    _ = input_buffer, entropy_buffer
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "Multimodal Emotion Analysis Tool credential",
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise CredentialStoreUnavailable(f"Windows DPAPI encryption failed with error {ctypes.get_last_error()}.")
    return copy_and_free_blob(output_blob, kernel32)


def unprotect_for_current_user(encrypted: bytes, entropy: bytes) -> bytes:
    crypt32, kernel32 = windows_dpapi_libraries()
    input_blob, input_buffer = make_blob(encrypted)
    entropy_blob, entropy_buffer = make_blob(entropy)
    output_blob = DataBlob()
    _ = input_buffer, entropy_buffer
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise CredentialStoreUnavailable(f"Windows DPAPI decryption failed with error {ctypes.get_last_error()}.")
    return copy_and_free_blob(output_blob, kernel32)


def windows_dpapi_libraries():
    if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
        raise CredentialStoreUnavailable("Windows DPAPI is required for persisted credentials.")
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def make_blob(data: bytes) -> tuple[DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return DataBlob(len(data), pointer), buffer


def copy_and_free_blob(blob: DataBlob, kernel32) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            kernel32.LocalFree(blob.pbData)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
