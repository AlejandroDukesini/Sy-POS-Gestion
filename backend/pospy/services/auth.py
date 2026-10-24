"""Autenticación, sesiones e instalación inicial.

Instalación: mientras no exista ningún usuario, el sistema acepta crear el primer administrador
solo con un código de instalación de un solo uso. El código lo genera el servidor y lo guarda en
<datos>/setup-code.txt (o lo inyecta la aplicación de escritorio vía POS_SETUP_CODE). No hay
credenciales por defecto en el repositorio ni registro público de usuarios.
"""
from __future__ import annotations

import hmac
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ..core import permissions as perms
from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, now_utc, parse_iso
from ..core.errors import AuthError, ValidationError
from ..core.security import DUMMY_HASH, check_policy, hash_password, new_token, token_hash, verify_password
from ..core.settings import Settings

log = logging.getLogger("pospy.auth")


@dataclass
class LoginResult:
    token: str
    actor: Actor
    must_change_password: bool


class AuthService:
    def __init__(self, db, settings: Settings, data_dir: Path, injected_setup_code: str = ""):
        self.db = db
        self.settings = settings
        self.setup_file = Path(data_dir) / "setup-code.txt"
        self._injected = injected_setup_code

    # ------------------------------------------------------------------ instalación
    def needs_setup(self) -> bool:
        with self.db.read() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    def prepare_setup(self) -> None:
        """Genera el código de instalación si hace falta. Se llama al arrancar."""
        if not self.needs_setup():
            if self.setup_file.exists():
                self.setup_file.unlink()
            return
        if self._injected:
            return
        if not self.setup_file.exists():
            code = "-".join(secrets.token_hex(3).upper() for _ in range(3))
            self.setup_file.write_text(code + "\n", encoding="utf-8")
        log.warning("POS-PY sin usuarios. Código de instalación en: %s", self.setup_file)

    def _valid_setup_code(self, code: str) -> bool:
        expected = self._injected or (self.setup_file.read_text(encoding="utf-8").strip() if self.setup_file.exists() else "")
        return bool(expected) and hmac.compare_digest(code.strip().upper(), expected.upper())

    def setup_admin(self, code: str, username: str, full_name: str, password: str) -> None:
        if not self.needs_setup():
            raise AuthError("El sistema ya está inicializado.")
        if not self._valid_setup_code(code or ""):
            raise ValidationError("Código de instalación incorrecto.", {"code": "El código no coincide."})
        username = _clean_username(username)
        check_policy(password, username)
        with self.db.tx() as conn:
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise AuthError("El sistema ya está inicializado.")
            now = iso()
            cur = conn.execute("INSERT INTO users(username, full_name, role, password_hash, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?)", (username, full_name.strip() or username, "admin",
                                                         hash_password(password), now, now))
            actor = Actor(cur.lastrowid, username, "admin", perms.ALL)
            record(conn, actor, "instalacion.administrador_creado", "user", cur.lastrowid)
        if self.setup_file.exists():
            self.setup_file.unlink()

    # ------------------------------------------------------------------ sesión
    def login(self, username: str, password: str, client: str = "") -> LoginResult:
        sec = self.settings.get("seguridad")
        failure: AuthError | None = None
        with self.db.tx() as conn:  # los fallos se registran y confirman antes de lanzar el error
            user = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
            now = now_utc()
            if user is None:
                verify_password(password or "", DUMMY_HASH)
                record(conn, None, "sesion.fallida", "user", None, {"usuario": (username or "")[:40]})
                failure = AuthError("Usuario o contraseña incorrectos.")
            elif user["locked_until"] and parse_iso(user["locked_until"]) > now:
                record(conn, None, "sesion.bloqueada", "user", user["id"])
                minutes = int((parse_iso(user["locked_until"]) - now).total_seconds() // 60) + 1
                failure = AuthError(f"Cuenta bloqueada temporalmente por intentos fallidos. Intente en {minutes} minutos.")
            elif not verify_password(password or "", user["password_hash"]):
                attempts = user["failed_attempts"] + 1
                locked = iso(now + timedelta(minutes=sec["lockout_minutes"])) if attempts >= sec["lockout_attempts"] else None
                conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                             (0 if locked else attempts, locked, user["id"]))
                record(conn, None, "sesion.fallida", "user", user["id"], {"bloqueo": bool(locked)})
                failure = AuthError("Usuario o contraseña incorrectos.")
            elif not user["active"]:
                record(conn, None, "sesion.cuenta_inactiva", "user", user["id"])
                failure = AuthError("La cuenta está desactivada. Consulte con un administrador.")
            else:
                token = new_token()
                conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                             (iso(now), user["id"]))
                conn.execute("INSERT INTO sessions(token_hash, user_id, session_version, created_at, last_seen_at,"
                             " expires_at, client) VALUES (?,?,?,?,?,?,?)",
                             (token_hash(token), user["id"], user["session_version"], iso(now), iso(now),
                              iso(now + timedelta(hours=sec["session_max_hours"])), (client or "")[:120]))
                actor = self._actor(conn, user)
                record(conn, actor, "sesion.inicio", "user", user["id"])
        if failure:
            raise failure
        return LoginResult(token, actor, bool(user["must_change_password"]))

    def resolve(self, token: str | None) -> tuple[Actor, bool]:
        """Devuelve (actor, debe_cambiar_contraseña) o lanza AuthError si la sesión no es válida."""
        if not token:
            raise AuthError("Inicie sesión para continuar.")
        idle = timedelta(minutes=self.settings.get("seguridad")["session_idle_minutes"])
        failure: AuthError | None = None
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT s.id AS sid, s.session_version AS sv, s.last_seen_at, s.expires_at, s.revoked_at, u.*"
                " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (token_hash(token),)).fetchone()
            now = now_utc()
            if row is None or row["revoked_at"]:
                failure = AuthError("La sesión terminó. Inicie sesión de nuevo.")
            else:
                expired = parse_iso(row["expires_at"]) <= now or parse_iso(row["last_seen_at"]) + idle <= now
                if expired or not row["active"] or row["sv"] != row["session_version"]:
                    conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (iso(now), row["sid"]))
                    failure = AuthError("La sesión expiró por seguridad. Inicie sesión de nuevo." if expired
                                        else "La sesión fue cerrada por un cambio en la cuenta. Inicie sesión de nuevo.")
                else:
                    if (now - parse_iso(row["last_seen_at"])).total_seconds() > 30:
                        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (iso(now), row["sid"]))
                    actor = self._actor(conn, row)
        if failure:
            raise failure
        return actor, bool(row["must_change_password"])

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.db.tx() as conn:
            row = conn.execute("SELECT s.id, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE token_hash = ?"
                               " AND revoked_at IS NULL", (token_hash(token),)).fetchone()
            if row:
                conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (iso(), row[0]))
                record(conn, Actor(row["id"], row["username"], row["role"]), "sesion.cierre", "user", row["id"])

    def change_password(self, actor: Actor, current: str, new: str, token: str) -> None:
        check_policy(new, actor.username)
        with self.db.tx() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (actor.id,)).fetchone()
            if not verify_password(current or "", user["password_hash"]):
                raise ValidationError("La contraseña actual no es correcta.", {"current": "Contraseña incorrecta."})
            if verify_password(new, user["password_hash"]):
                raise ValidationError("La nueva contraseña debe ser distinta.", {"password": "Use una contraseña nueva."})
            conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0, session_version = session_version + 1,"
                         " updated_at = ?, version = version + 1 WHERE id = ?", (hash_password(new), iso(), actor.id))
            # La sesión actual sigue válida con la nueva versión; las demás quedan revocadas.
            conn.execute("UPDATE sessions SET session_version = session_version + 1 WHERE token_hash = ?", (token_hash(token),))
            record(conn, actor, "usuario.cambio_contrasena", "user", actor.id)

    @staticmethod
    def _actor(conn: sqlite3.Connection, user) -> Actor:
        assigned = {r[0] for r in conn.execute("SELECT permission FROM user_permissions WHERE user_id = ?", (user["id"],))}
        return Actor(user["id"], user["username"], user["role"], perms.effective(user["role"], assigned), user["full_name"])


def _clean_username(username: str) -> str:
    import re
    value = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", value):
        raise ValidationError("Usuario no válido.", {"username": "Use de 3 a 40 letras, números, punto, guion o guion bajo."})
    return value
