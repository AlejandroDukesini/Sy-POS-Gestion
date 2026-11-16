"""Estado de acceso: asistente de configuración inicial e inicio de sesión activable.

Se guarda en la tabla settings bajo la clave «acceso» (fuera del esquema editable genérico, para que
solo estas operaciones, con sus reglas, puedan cambiarlo):

  login_enabled    True: todos ingresan con usuario y contraseña.
                   False: «acceso directo» desde el propio equipo; cada persona elige su perfil y
                   actúa con SUS permisos. Los perfiles de administrador con contraseña la siguen
                   pidiendo, así que un empleado no puede cambiar la configuración de seguridad.
  setup_completed  False mientras el asistente de configuración inicial no haya terminado.
  setup_step       Último paso alcanzado del asistente (para continuar donde se quedó).

Sin fila guardada (bases anteriores a la migración 3 creadas por consola o pruebas), el estado se
deduce: si ya existe una cuenta con contraseña, el inicio de sesión sigue activo y la instalación
está terminada; si no, el sistema está pendiente de configurar.
"""
from __future__ import annotations

import json
import sqlite3

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import PermissionDenied, ValidationError

KEY = "acceso"
STEPS = ("empresa", "preferencias", "seguridad", "empleados", "listo")


class AccessService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ lectura
    def state(self, conn: sqlite3.Connection | None = None) -> dict:
        if conn is None:
            with self.db.read() as c:
                return self._state(c)
        return self._state(conn)

    @staticmethod
    def _state(conn: sqlite3.Connection) -> dict:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
        if row:
            stored = json.loads(row[0])
            step = stored.get("setup_step") if stored.get("setup_step") in STEPS else STEPS[0]
            return {"login_enabled": bool(stored.get("login_enabled")), "setup_completed": bool(stored.get("setup_completed")),
                    "setup_step": step}
        legacy = conn.execute("SELECT 1 FROM users WHERE password_hash <> '' LIMIT 1").fetchone() is not None
        return {"login_enabled": legacy, "setup_completed": legacy, "setup_step": "listo" if legacy else STEPS[0]}

    @staticmethod
    def admins_with_password(conn: sqlite3.Connection, exclude_id: int | None = None) -> int:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND password_hash <> ''"
                            " AND id IS NOT ?", (exclude_id,)).fetchone()[0]

    def summary(self, actor: Actor) -> dict:
        """Estado que muestra Configuración › Seguridad."""
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            state = self._state(conn)
            me = conn.execute("SELECT password_hash <> '' FROM users WHERE id = ?", (actor.id,)).fetchone()
            counts = conn.execute(
                "SELECT SUM(role = 'admin' AND active = 1), SUM(role = 'admin' AND active = 1 AND password_hash = ''),"
                " SUM(role = 'employee' AND active = 1), SUM(role = 'employee' AND active = 1 AND password_hash <> '')"
                " FROM users").fetchone()
            state.update({
                "admins_with_password": self.admins_with_password(conn),
                "admins_without_password": counts[1] or 0,
                "active_admins": counts[0] or 0,
                "active_employees": counts[2] or 0,
                "employees_with_account": counts[3] or 0,
                "current_user_has_password": bool(me and me[0]),
            })
        return state

    # ------------------------------------------------------------------ escritura
    @staticmethod
    def write(conn: sqlite3.Connection, state: dict, actor_id: int | None) -> None:
        conn.execute("INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE"
                     " SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                     (KEY, json.dumps({k: state[k] for k in ("login_enabled", "setup_completed", "setup_step")}),
                      iso(), actor_id))

    def set_login(self, actor: Actor, enabled: bool) -> dict:
        """Activa o desactiva el inicio de sesión. Nunca borra cuentas, contraseñas, empleados ni permisos."""
        _require_admin(actor)
        with self.db.tx() as conn:
            state = self._state(conn)
            if enabled and self.admins_with_password(conn) == 0:
                raise ValidationError("Antes de activar el inicio de sesión cree una cuenta de administrador con contraseña.",
                                      {"login_enabled": "Se necesita al menos un administrador activo con contraseña."})
            if state["login_enabled"] == bool(enabled):
                return self._state(conn)
            state["login_enabled"] = bool(enabled)
            self.write(conn, state, actor.id)
            # Las sesiones de acceso directo dejan de valer: todos deben identificarse. Durante el
            # asistente se conserva la del administrador que configura; se cierra al terminarlo.
            revoked = self._revoke_direct(conn) if enabled and state["setup_completed"] else 0
            record(conn, actor, "seguridad.inicio_sesion_" + ("activado" if enabled else "desactivado"), "settings", KEY,
                   {"sesiones_directas_cerradas": revoked} if enabled else None)
            return self._state(conn)

    def set_step(self, actor: Actor, step: str) -> dict:
        _require_admin(actor)
        if step not in STEPS:
            raise ValidationError("Paso desconocido del asistente.")
        with self.db.tx() as conn:
            state = self._state(conn)
            if not state["setup_completed"]:
                state["setup_step"] = step
                self.write(conn, state, actor.id)
            return self._state(conn)

    def complete_setup(self, actor: Actor) -> dict:
        _require_admin(actor)
        with self.db.tx() as conn:
            state = self._state(conn)
            if state["setup_completed"]:
                return state
            if state["login_enabled"] and self.admins_with_password(conn) == 0:
                raise ValidationError("El inicio de sesión está activo pero ningún administrador tiene contraseña.")
            state.update(setup_completed=True, setup_step="listo")
            self.write(conn, state, actor.id)
            if state["login_enabled"]:
                self._revoke_direct(conn)
            record(conn, actor, "instalacion.completada", "settings", KEY, {"inicio_sesion": state["login_enabled"]})
            return state

    @staticmethod
    def _revoke_direct(conn: sqlite3.Connection) -> int:
        return conn.execute("UPDATE sessions SET revoked_at = ? WHERE open_mode = 1 AND revoked_at IS NULL",
                            (iso(),)).rowcount


def _require_admin(actor: Actor) -> None:
    actor.require("gestion.configuracion")
    if not actor.is_admin:
        raise PermissionDenied("Solo un administrador puede cambiar la configuración de seguridad.")
