"""Contraseñas (scrypt), tokens de sesión y política de contraseñas."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from .errors import ValidationError

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
MIN_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# Hash de una contraseña aleatoria: igualar el tiempo de respuesta cuando el usuario no existe.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_policy(password: str, username: str = "") -> None:
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"al menos {MIN_LENGTH} caracteres")
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", password) or not re.search(r"\d", password):
        problems.append("letras y números")
    if username and username.lower() in password.lower():
        problems.append("no contener el nombre de usuario")
    if problems:
        raise ValidationError("La contraseña no cumple la política.",
                              {"password": "La contraseña debe tener " + ", ".join(problems) + "."})


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
