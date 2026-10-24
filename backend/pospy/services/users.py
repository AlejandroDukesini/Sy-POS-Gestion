"""Usuarios y permisos (solo administradores con gestion.usuarios)."""
from __future__ import annotations

import sqlite3

from ..core import permissions as perms
from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.security import check_policy, hash_password
from .auth import _clean_username

PUBLIC_COLUMNS = ("id, username, full_name, role, active, must_change_password, locked_until, last_login_at,"
                  " created_at, updated_at, version")


class UserService:
    def __init__(self, db):
        self.db = db

    def list(self, actor: Actor) -> list[dict]:
        actor.require("gestion.usuarios")
        with self.db.read() as conn:
            users = [dict(r) for r in conn.execute(f"SELECT {PUBLIC_COLUMNS} FROM users ORDER BY role, username")]
            for u in users:
                u["permissions"] = self._permissions(conn, u)
        return users

    def get(self, actor: Actor, user_id: int) -> dict:
        actor.require("gestion.usuarios")
        with self.db.read() as conn:
            return self._get(conn, user_id)

    def _get(self, conn: sqlite3.Connection, user_id: int) -> dict:
        row = conn.execute(f"SELECT {PUBLIC_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise NotFoundError("Usuario no encontrado.")
        user = dict(row)
        user["permissions"] = self._permissions(conn, user)
        return user

    @staticmethod
    def _permissions(conn: sqlite3.Connection, user: dict) -> list[str]:
        assigned = {r[0] for r in conn.execute("SELECT permission FROM user_permissions WHERE user_id = ?", (user["id"],))}
        return sorted(perms.effective(user["role"], assigned))

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("gestion.usuarios")
        username = _clean_username(data.get("username", ""))
        full_name = (data.get("full_name") or "").strip()
        role = data.get("role", "employee")
        password = data.get("password") or ""
        if not full_name:
            raise ValidationError("Faltan datos.", {"full_name": "El nombre es obligatorio."})
        if role not in ("admin", "employee"):
            raise ValidationError("Rol no válido.", {"role": "Elija Administrador o Empleado."})
        check_policy(password, username)
        requested = set(data.get("permissions") or perms.DEFAULT_EMPLOYEE)
        self._validate_assignable(actor, role, requested)
        with self.db.tx() as conn:
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ConflictError("Ya existe un usuario con ese nombre.", {"username": "Elija otro nombre de usuario."})
            now = iso()
            cur = conn.execute("INSERT INTO users(username, full_name, role, password_hash, must_change_password,"
                               " created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
                               (username, full_name, role, hash_password(password), now, now))
            uid = cur.lastrowid
            if role == "employee":
                conn.executemany("INSERT INTO user_permissions(user_id, permission) VALUES (?,?)",
                                 [(uid, p) for p in sorted(requested)])
            record(conn, actor, "usuario.crear", "user", uid, {"usuario": username, "rol": role,
                                                              "permisos": sorted(requested) if role == "employee" else "todos"})
            return self._get(conn, uid)

    def update(self, actor: Actor, user_id: int, data: dict) -> dict:
        actor.require("gestion.usuarios")
        allowed = {"full_name", "role", "active", "permissions", "version"}
        if set(data) - allowed:
            raise ValidationError("Campos no permitidos: " + ", ".join(sorted(set(data) - allowed)))
        with self.db.tx() as conn:
            user = self._get(conn, user_id)
            if "version" in data and int(data["version"]) != user["version"]:
                raise ConflictError("Otra persona modificó este usuario. Recargue y vuelva a intentarlo.")
            role = data.get("role", user["role"])
            active = int(bool(data.get("active", user["active"])))
            if role not in ("admin", "employee"):
                raise ValidationError("Rol no válido.", {"role": "Elija Administrador o Empleado."})
            if user_id == actor.id and (role != user["role"] or not active):
                raise ValidationError("No puede cambiar su propio rol ni desactivar su propia cuenta.")
            if user["role"] == "admin" and user["active"] and (role != "admin" or not active):
                admins = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0]
                if admins <= 1:
                    raise ValidationError("Debe existir al menos un administrador activo.")
            full_name = (data.get("full_name", user["full_name"]) or "").strip()
            if not full_name:
                raise ValidationError("Faltan datos.", {"full_name": "El nombre es obligatorio."})
            changes: dict = {}
            revoke = role != user["role"] or (not active and user["active"])
            if "permissions" in data or role != user["role"]:
                if "permissions" in data:
                    requested = set(data["permissions"] or [])
                elif role == "employee" and user["role"] == "admin":
                    requested = set(perms.DEFAULT_EMPLOYEE)   # al degradar no se heredan permisos de administración
                else:
                    requested = set(user["permissions"])
                self._validate_assignable(actor, role, requested)
                before = set(user["permissions"])
                conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
                if role == "employee":
                    conn.executemany("INSERT INTO user_permissions(user_id, permission) VALUES (?,?)",
                                     [(user_id, p) for p in sorted(requested)])
                after = set(perms.effective(role, requested))
                if before != after:
                    changes["permisos"] = {"agregados": sorted(after - before), "retirados": sorted(before - after)}
                    revoke = True
            conn.execute("UPDATE users SET full_name = ?, role = ?, active = ?, updated_at = ?, version = version + 1,"
                         " session_version = session_version + ? WHERE id = ?",
                         (full_name, role, active, iso(), 1 if revoke else 0, user_id))
            for key, old, new in (("nombre", user["full_name"], full_name), ("rol", user["role"], role),
                                  ("activo", user["active"], active)):
                if old != new:
                    changes[key] = {"antes": old, "despues": new}
            if changes:
                record(conn, actor, "usuario.actualizar", "user", user_id, changes)
            return self._get(conn, user_id)

    def reset_password(self, actor: Actor, user_id: int, password: str) -> None:
        actor.require("gestion.usuarios")
        with self.db.tx() as conn:
            user = self._get(conn, user_id)
            check_policy(password, user["username"])
            conn.execute("UPDATE users SET password_hash = ?, must_change_password = 1, failed_attempts = 0,"
                         " locked_until = NULL, session_version = session_version + 1, updated_at = ?,"
                         " version = version + 1 WHERE id = ?", (hash_password(password), iso(), user_id))
            record(conn, actor, "usuario.restablecer_contrasena", "user", user_id)

    def unlock(self, actor: Actor, user_id: int) -> None:
        actor.require("gestion.usuarios")
        with self.db.tx() as conn:
            self._get(conn, user_id)
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
            record(conn, actor, "usuario.desbloquear", "user", user_id)

    @staticmethod
    def _validate_assignable(actor: Actor, role: str, requested: set[str]) -> None:
        if role == "admin":
            return
        unknown = requested - perms.ALL
        if unknown:
            raise ValidationError("Permisos desconocidos: " + ", ".join(sorted(unknown)))
        forbidden = requested - perms.ASSIGNABLE_TO_EMPLOYEE
        if forbidden:
            raise ValidationError("Estos permisos son exclusivos de administradores: " + ", ".join(sorted(forbidden)))

    @staticmethod
    def catalog() -> list[dict]:
        return [{"code": p.code, "label": p.label, "group": p.group, "admin_only": p.admin_only} for p in perms.CATALOG]
