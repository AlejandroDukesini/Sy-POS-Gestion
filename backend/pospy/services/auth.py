"""Autenticación, sesiones e instalación inicial.

Instalación: mientras el asistente de configuración inicial no haya terminado, el sistema permite
abrirlo sin cuenta ni contraseña, pero solo desde el propio equipo y con un código de instalación de
un solo uso. El código lo genera el servidor y lo guarda en <datos>/setup-code.txt (o lo inyecta la
aplicación de escritorio vía POS_SETUP_CODE, de modo que allí no hay que escribirlo). El asistente
crea un perfil de administrador sin contraseña; la contraseña se asigna al activar el inicio de
sesión (o antes, si se desea). No hay credenciales por defecto ni registro público de usuarios.

Acceso directo (inicio de sesión desactivado): ver services/access.py. Las sesiones creadas así se
marcan con open_mode = 1 y dejan de valer en cuanto se activa el inicio de sesión.
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
from ..core.ratelimit import RateLimiter
from ..core.security import DUMMY_HASH, check_policy, hash_password, new_token, token_hash, verify_password
from ..core.settings import Settings
from .access import AccessService
from .devices import DeviceError, DeviceService

log = logging.getLogger("pospy.auth")


@dataclass
class LoginResult:
    token: str
    actor: Actor
    must_change_password: bool


class AuthService:
    def __init__(self, db, settings: Settings, data_dir: Path, injected_setup_code: str = "",
                 access: AccessService | None = None, devices: DeviceService | None = None):
        self.db = db
        self.settings = settings
        self.access = access or AccessService(db)
        self.devices = devices or DeviceService(db)
        # Límite por origen (además del bloqueo por cuenta): 20 fallos en 15 minutos desde la misma dirección.
        self.limiter = RateLimiter(limit=20, window_s=15 * 60,
                                   message="Demasiados intentos fallidos de inicio de sesión desde este equipo.")
        self.setup_file = Path(data_dir) / "setup-code.txt"
        self._injected = injected_setup_code

    # ------------------------------------------------------------------ instalación
    def needs_setup(self) -> bool:
        """True mientras la configuración inicial no haya terminado."""
        return not self.access.state()["setup_completed"]

    def has_users(self) -> bool:
        with self.db.read() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def prepare_setup(self) -> None:
        """Genera el código de instalación si hace falta. Se llama al arrancar."""
        if not self.needs_setup():
            self.discard_setup_code()
            return
        if self._injected:
            return
        if not self.setup_file.exists():
            code = "-".join(secrets.token_hex(3).upper() for _ in range(3))
            self.setup_file.write_text(code + "\n", encoding="utf-8")
        log.warning("POS-PY pendiente de configurar. Código de instalación en: %s", self.setup_file)

    def discard_setup_code(self) -> None:
        if self.setup_file.exists():
            self.setup_file.unlink()

    def _valid_setup_code(self, code: str) -> bool:
        expected = self._injected or (self.setup_file.read_text(encoding="utf-8").strip() if self.setup_file.exists() else "")
        return bool(expected) and hmac.compare_digest(code.strip().upper(), expected.upper())

    def setup_admin(self, code: str, username: str, full_name: str, password: str) -> None:
        """Instalación clásica (consola): primer administrador con contraseña e inicio de sesión activo."""
        if self.has_users():
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
            self.access.write(conn, {"login_enabled": True, "setup_completed": True, "setup_step": "listo"}, actor.id)
            _first_inventory(conn, actor.id)
            record(conn, actor, "instalacion.administrador_creado", "user", cur.lastrowid)
        self.discard_setup_code()

    def start_setup(self, code: str, client: str = "") -> LoginResult:
        """Abre (o retoma) el asistente de configuración inicial sin exigir cuenta.

        Requiere el código de instalación. Si no hay usuarios crea el perfil «admin» sin contraseña.
        Si el administrador ya tiene contraseña, el asistente se retoma iniciando sesión con ella.
        """
        if not self.needs_setup():
            raise AuthError("La configuración inicial ya terminó. Ingrese con su usuario.")
        if not self._valid_setup_code(code or ""):
            raise ValidationError("Código de instalación incorrecto.", {"code": "El código no coincide."})
        with self.db.tx() as conn:
            if self.access.state(conn)["setup_completed"]:
                raise AuthError("La configuración inicial ya terminó. Ingrese con su usuario.")
            user = conn.execute("SELECT * FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1").fetchone()
            if user is None:
                if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                    raise AuthError("No hay un administrador activo. Revise la instalación con: python -m pospy.cli status")
                now = iso()
                cur = conn.execute("INSERT INTO users(username, full_name, role, password_hash, created_at, updated_at)"
                                   " VALUES ('admin', 'Administrador', 'admin', '', ?, ?)", (now, now))
                user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
                self.access.write(conn, {"login_enabled": False, "setup_completed": False, "setup_step": "empresa"},
                                  user["id"])
                record(conn, Actor(user["id"], "admin", "admin", perms.ALL), "instalacion.iniciada", "user", user["id"])
            elif user["password_hash"]:
                raise AuthError("El administrador ya tiene contraseña: ingrese con ella para continuar la configuración.")
            _first_inventory(conn, user["id"])
            token, actor = self._open(conn, user, client, open_mode=True)
            record(conn, actor, "instalacion.asistente_abierto", "user", user["id"])
        return LoginResult(token, actor, False)

    # ------------------------------------------------------------------ acceso directo
    def direct_access_available(self) -> bool:
        state = self.access.state()
        return state["setup_completed"] and not state["login_enabled"]

    def profiles(self) -> list[dict]:
        """Perfiles que se pueden elegir con el inicio de sesión desactivado (sin datos sensibles)."""
        if not self.direct_access_available():
            raise AuthError("El inicio de sesión está activo. Ingrese con su usuario y contraseña.")
        with self.db.read() as conn:
            return [{"id": r["id"], "username": r["username"], "full_name": r["full_name"], "role": r["role"],
                     "requires_password": r["role"] == "admin" and bool(r["password_hash"])}
                    for r in conn.execute("SELECT id, username, full_name, role, password_hash FROM users WHERE active = 1"
                                          " ORDER BY role = 'admin', full_name COLLATE NOCASE")]

    def open_session(self, user_id: int, client: str = "") -> LoginResult:
        """Entra con un perfil sin contraseña. Los administradores con contraseña deben usarla."""
        if not self.direct_access_available():
            raise AuthError("El inicio de sesión está activo. Ingrese con su usuario y contraseña.")
        with self.db.tx() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None or not user["active"]:
                raise AuthError("Perfil no disponible.")
            if user["role"] == "admin" and user["password_hash"]:
                raise AuthError("Los perfiles de administrador con contraseña deben ingresar con ella.")
            token, actor = self._open(conn, user, client, open_mode=True)
            record(conn, actor, "sesion.inicio_directo", "user", user["id"])
        return LoginResult(token, actor, False)

    # ------------------------------------------------------------------ sesión
    def login(self, username: str, password: str, client: str = "", origin: str = "", device_proof: dict | None = None,
              local: bool = False) -> LoginResult:
        sec = self.settings.get("seguridad")
        origin_key = f"login:{origin or '?'}"
        self.limiter.check(origin_key)
        failure: AuthError | None = None
        # La firma del equipo se comprueba antes (consume el desafío de un solo uso); el resultado se usa después de
        # validar la contraseña, para no revelar el estado de los equipos a quien no conoce las credenciales.
        proof_error: DeviceError | None = None
        thumb = None
        if device_proof is not None:
            try:
                _, thumb = self.devices.verify_proof(device_proof)
            except DeviceError as exc:
                proof_error = exc
        device_id = None
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
            elif not user["password_hash"]:
                # Perfil sin cuenta (empleado sin contraseña): mismo mensaje y mismo coste que un error de clave.
                verify_password(password or "", DUMMY_HASH)
                record(conn, None, "sesion.fallida", "user", user["id"], {"sin_cuenta": True})
                failure = AuthError("Usuario o contraseña incorrectos.")
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
                device = self.devices.by_thumbprint(conn, thumb) if thumb else None
                if self.devices.enforced(conn) and not local:
                    try:
                        if proof_error:
                            raise proof_error
                        if thumb is None:
                            self.devices.verify_proof(None)
                        self.devices.require_authorized(device)
                    except DeviceError as exc:
                        record(conn, None, "sesion.equipo_rechazado", "user", user["id"],
                               {"motivo": exc.code, "equipo": device["public_id"] if device else None, "cliente": (client or "")[:80]})
                        failure = exc
                if failure is None:
                    if device and device["status"] == "autorizado":
                        device_id = device["id"]
                        self.devices.touch(conn, device_id, user["id"])
                    token, actor = self._open(conn, user, client, open_mode=False, device_id=device_id)
                    record(conn, actor, "sesion.inicio", "user", user["id"], {"equipo": device["public_id"]} if device_id else None)
        if failure:
            if not isinstance(failure, DeviceError):
                self.limiter.hit(origin_key)
            raise failure
        self.limiter.reset(origin_key)
        return LoginResult(token, actor, bool(user["must_change_password"]))

    def _open(self, conn: sqlite3.Connection, user, client: str, open_mode: bool,
              device_id: int | None = None) -> tuple[str, Actor]:
        sec = self.settings.get("seguridad", conn)
        now = now_utc()
        token = new_token()
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                     (iso(now), user["id"]))
        conn.execute("INSERT INTO sessions(token_hash, user_id, session_version, created_at, last_seen_at,"
                     " expires_at, client, open_mode, device_id) VALUES (?,?,?,?,?,?,?,?,?)",
                     (token_hash(token), user["id"], user["session_version"], iso(now), iso(now),
                      iso(now + timedelta(hours=sec["session_max_hours"])), (client or "")[:120], int(open_mode), device_id))
        return token, self._actor(conn, user)

    def resolve(self, token: str | None, touch: bool = True, local: bool = False) -> tuple[Actor, bool]:
        """Devuelve (actor, debe_cambiar_contraseña) o lanza AuthError si la sesión no es válida.

        touch=False valida sin contar como actividad (lo usa el canal de tiempo real: una pestaña abierta
        no debe impedir el cierre de sesión por inactividad).
        """
        if not token:
            raise AuthError("Inicie sesión para continuar.")
        idle = timedelta(minutes=self.settings.get("seguridad")["session_idle_minutes"])
        failure: AuthError | None = None
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT s.id AS sid, s.session_version AS sv, s.last_seen_at, s.expires_at, s.revoked_at, s.open_mode,"
                " s.device_id, d.status AS device_status, u.*"
                " FROM sessions s JOIN users u ON u.id = s.user_id LEFT JOIN devices d ON d.id = s.device_id"
                " WHERE s.token_hash = ?", (token_hash(token),)).fetchone()
            now = now_utc()
            if row is None or row["revoked_at"]:
                failure = AuthError("La sesión terminó. Inicie sesión de nuevo.")
            else:
                expired = parse_iso(row["expires_at"]) <= now or parse_iso(row["last_seen_at"]) + idle <= now
                # Una sesión de acceso directo deja de valer si se activa el inicio de sesión.
                closed = bool(row["open_mode"]) and self._direct_closed(conn)
                # Restricción por equipo: fuera del equipo servidor, la sesión debe venir de un equipo que SIGA autorizado.
                device_denied = (not local and row["device_status"] != "autorizado" and not row["open_mode"]
                                 and self.devices.enforced(conn))
                if device_denied:
                    conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (iso(now), row["sid"]))
                    record(conn, None, "sesion.equipo_rechazado", "user", row["id"],
                           {"motivo": row["device_status"] or "sin_equipo", "sesion": row["sid"]})
                    # 401 (no 403): la interfaz cierra la sesión y muestra el motivo en la pantalla de ingreso.
                    failure = AuthError("Este equipo no está autorizado para usar el POS (o su autorización fue revocada). "
                                        "Consulte con un administrador.")
                elif expired or closed or not row["active"] or row["sv"] != row["session_version"]:
                    conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (iso(now), row["sid"]))
                    failure = AuthError("La sesión expiró por seguridad. Inicie sesión de nuevo." if expired
                                        else "El inicio de sesión ahora es obligatorio. Ingrese con su usuario y contraseña."
                                        if closed else
                                        "La sesión fue cerrada por un cambio en la cuenta. Inicie sesión de nuevo.")
                else:
                    if touch and (now - parse_iso(row["last_seen_at"])).total_seconds() > 30:
                        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (iso(now), row["sid"]))
                        if row["device_id"]:
                            self.devices.touch(conn, row["device_id"], row["id"])
                    actor = self._actor(conn, row)
        if failure:
            raise failure
        # En acceso directo no se exige cambiar la contraseña temporal (no se usó para entrar).
        return actor, bool(row["must_change_password"]) and not row["open_mode"]

    def device_status(self, token: str | None) -> dict:
        """Equipo de la sesión actual (para la interfaz)."""
        with self.db.read() as conn:
            row = conn.execute("SELECT d.public_id, d.name, d.status FROM sessions s JOIN devices d ON d.id = s.device_id"
                               " WHERE s.token_hash = ?", (token_hash(token or ""),)).fetchone()
            return {"enforced": self.devices.enforced(conn), "device": dict(row) if row else None}

    def register_device(self, actor: Actor, token: str | None, proof: dict, name: str, user_agent: str) -> dict:
        """Con una sesión abierta: registra ESTE equipo. Un administrador lo autoriza de inmediato y la sesión queda
        vinculada; un empleado queda «pendiente» (no puede autorizarse a sí mismo)."""
        spki, thumb = self.devices.verify_proof(proof)
        with self.db.tx() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (actor.id,)).fetchone()
            device = self.devices.request(conn, user, spki, thumb, name, user_agent,
                                          auto_authorize=actor if actor.can("gestion.configuracion") else None)
            if device["status"] == "autorizado":
                conn.execute("UPDATE sessions SET device_id = ? WHERE token_hash = ?", (device["id"], token_hash(token or "")))
        return {"device": {k: device[k] for k in ("public_id", "name", "status")}}

    def request_device(self, username: str, password: str, proof: dict, name: str, user_agent: str, origin: str) -> dict:
        """Sin sesión (el equipo aún no está autorizado): solicita la autorización con las credenciales de la persona.
        Queda «pendiente» hasta que un administrador la apruebe; nunca se autoriza sola."""
        key = f"login:{origin or '?'}"
        self.limiter.check(key)
        spki, thumb = self.devices.verify_proof(proof)
        failure: AuthError | None = None
        with self.db.tx() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", ((username or "").strip(),)).fetchone()
            if user is None or not user["password_hash"] or not verify_password(password or "", user["password_hash"]):
                if user is None:
                    verify_password(password or "", DUMMY_HASH)
                record(conn, None, "dispositivo.solicitud_fallida", "user", user["id"] if user else None)
                failure = AuthError("Usuario o contraseña incorrectos.")
            else:
                device = self.devices.request(conn, user, spki, thumb, name, user_agent)
        if failure:
            self.limiter.hit(key)
            raise failure
        return {"device": {k: device[k] for k in ("public_id", "name", "status")}}

    def _direct_closed(self, conn: sqlite3.Connection) -> bool:
        """Sesiones directas válidas: durante el asistente o con el inicio de sesión desactivado."""
        state = self.access.state(conn)
        return state["setup_completed"] and state["login_enabled"]

    def has_password(self, user_id: int) -> bool:
        with self.db.read() as conn:
            row = conn.execute("SELECT password_hash <> '' FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row[0])

    def is_direct(self, token: str | None) -> bool:
        if not token:
            return False
        with self.db.read() as conn:
            row = conn.execute("SELECT open_mode FROM sessions WHERE token_hash = ?", (token_hash(token),)).fetchone()
        return bool(row and row[0])

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.db.tx() as conn:
            # Columnas con alias propios: «s.id» y «u.id» se llamaban igual y el registro usaba el id de la SESIÓN como
            # usuario; la clave foránea fallaba, se revertía la transacción y la sesión NO quedaba revocada.
            row = conn.execute("SELECT s.id AS session_id, u.id AS user_id, u.username, u.role FROM sessions s"
                               " JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.revoked_at IS NULL",
                               (token_hash(token),)).fetchone()
            if row:
                conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (iso(), row["session_id"]))
                record(conn, Actor(row["user_id"], row["username"], row["role"]), "sesion.cierre", "user", row["user_id"])

    def change_password(self, actor: Actor, current: str, new: str, token: str) -> None:
        check_policy(new, actor.username)
        with self.db.tx() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (actor.id,)).fetchone()
            had_password = bool(user["password_hash"])
            # Un perfil sin contraseña (creado sin cuenta) asigna aquí su primera contraseña.
            if had_password and not verify_password(current or "", user["password_hash"]):
                raise ValidationError("La contraseña actual no es correcta.", {"current": "Contraseña incorrecta."})
            if had_password and verify_password(new, user["password_hash"]):
                raise ValidationError("La nueva contraseña debe ser distinta.", {"password": "Use una contraseña nueva."})
            conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0, session_version = session_version + 1,"
                         " updated_at = ?, version = version + 1 WHERE id = ?", (hash_password(new), iso(), actor.id))
            # La sesión actual sigue válida con la nueva versión; las demás quedan revocadas.
            conn.execute("UPDATE sessions SET session_version = session_version + 1 WHERE token_hash = ?", (token_hash(token),))
            record(conn, actor, "usuario.cambio_contrasena" if had_password else "usuario.contrasena_asignada",
                   "user", actor.id)

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


def _first_inventory(conn, admin_id: int) -> None:
    """El primer administrador empieza con su inventario principal (sin productos: no se crean datos ficticios)."""
    from .inventories import create_inventory_conn
    if not conn.execute("SELECT 1 FROM inventories WHERE owner_id = ?", (admin_id,)).fetchone():
        create_inventory_conn(conn, admin_id, "Inventario principal")
