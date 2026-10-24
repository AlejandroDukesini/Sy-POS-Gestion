"""Almacén de secretos cifrados (tokens OAuth, secretos de cliente).

Los valores se cifran con Fernet (AES-128-CBC + HMAC). La clave maestra:
  * Windows: clave aleatoria guardada en data/secret.key protegida con DPAPI (cuenta de Windows actual);
    copiar el archivo a otro equipo o cuenta no permite descifrarla.
  * Otros sistemas: variable de entorno POS_MASTER_KEY (obligatoria para guardar secretos).
El frontend nunca recibe los valores: la API solo informa si un secreto está configurado.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .clock import iso
from .errors import DomainError


class SecretStoreError(DomainError):
    title = "Almacén de secretos no disponible"


if sys.platform == "win32":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes) -> _Blob:
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _dpapi(data: bytes, protect: bool) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        src, out = _blob(data), _Blob()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out))  # CRYPTPROTECT_UI_FORBIDDEN
        if not ok:
            raise SecretStoreError("Windows no pudo proteger o recuperar la clave de cifrado (DPAPI).")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)


class SecretStore:
    def __init__(self, db, data_dir: Path, master_key: str = ""):
        self.db = db
        self.key_file = Path(data_dir) / "secret.key"
        self.master_key = master_key
        self._fernet: Fernet | None = None

    def _cipher(self) -> Fernet:
        if self._fernet:
            return self._fernet
        if self.master_key:
            key = base64.urlsafe_b64encode(hashlib.sha256(self.master_key.encode()).digest())
        elif sys.platform == "win32":
            if self.key_file.exists():
                key = _dpapi(self.key_file.read_bytes(), protect=False)
            else:
                key = Fernet.generate_key()
                self.key_file.write_bytes(_dpapi(key, protect=True))
        else:
            raise SecretStoreError("Defina POS_MASTER_KEY para guardar credenciales en este sistema.")
        self._fernet = Fernet(key)
        return self._fernet

    def set(self, conn: sqlite3.Connection, name: str, value: str) -> None:
        token = self._cipher().encrypt(value.encode("utf-8"))
        conn.execute("INSERT INTO secrets(name, ciphertext, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext, updated_at = excluded.updated_at",
                     (name, token, iso()))

    def get(self, name: str) -> str | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT ciphertext FROM secrets WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        try:
            return self._cipher().decrypt(bytes(row[0])).decode("utf-8")
        except InvalidToken:
            raise SecretStoreError("No se pudo descifrar una credencial guardada (¿cambió la clave maestra o la cuenta"
                                   " de Windows?). Vuelva a autorizar la conexión.") from None

    def has(self, name: str) -> bool:
        with self.db.read() as conn:
            return conn.execute("SELECT 1 FROM secrets WHERE name = ?", (name,)).fetchone() is not None

    def delete(self, conn: sqlite3.Connection, prefix: str) -> None:
        conn.execute("DELETE FROM secrets WHERE name = ? OR name LIKE ?", (prefix, prefix + ".%"))


def restrict_file(path: Path) -> None:
    """Mejor esfuerzo: en POSIX deja el archivo legible solo por el propietario."""
    if os.name == "posix":
        os.chmod(path, 0o600)
