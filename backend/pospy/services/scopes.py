"""Inventarios: el «Inventario general» del negocio y un inventario propio por cada grupo de trabajo.

Quién accede a cada inventario (se valida en el servidor en cada operación; la interfaz solo elige):
- Inventario de un grupo: el administrador DUEÑO del grupo y los integrantes ACTIVOS del grupo. Nadie
  más, ni siquiera otro administrador: para ellos no existe (404).
- Inventario general (group_id NULL, todos los productos anteriores a los grupos): los administradores
  y los empleados que no pertenecen a ningún grupo (por ejemplo, los registrados en la configuración
  inicial). Un empleado que pertenece a un grupo trabaja solo en el inventario de su grupo.
Además de poder entrar al inventario, cada operación exige su permiso (inventario.ver, ventas.vender…).

La interfaz envía el inventario elegido en la cabecera X-Inventory («general» o el id público del
grupo). Las operaciones sobre un producto, una venta o un documento concretos usan el inventario al
que ese registro pertenece, no la cabecera.
"""
from __future__ import annotations

import sqlite3

from ..core.actor import Actor
from ..core.errors import NotFoundError, PermissionDenied

GENERAL = "general"
GENERAL_NAME = "Inventario general"


class InventoryScopes:
    def __init__(self, db, hub=None):
        self.db = db
        self.hub = hub

    # ------------------------------------------------------------------ acceso
    @staticmethod
    def _member_groups(conn: sqlite3.Connection, user_id: int) -> list[dict]:
        return [dict(r) for r in conn.execute(
            "SELECT g.id, g.public_id, g.name, g.status FROM work_group_members m JOIN work_groups g ON g.id = m.group_id"
            " WHERE m.user_id = ? AND m.status = 'activo' ORDER BY g.name COLLATE NOCASE", (user_id,))]

    def accessible(self, conn: sqlite3.Connection, actor: Actor) -> list[dict]:
        """Inventarios a los que entra esta persona, en orden (el primero es el predeterminado)."""
        out: list[dict] = []
        member = self._member_groups(conn, actor.id) if actor.id else []
        if actor.is_admin or not member:
            out.append({"key": GENERAL, "group_id": None, "name": GENERAL_NAME, "kind": "general", "status": "activo"})
        if actor.is_admin and actor.can("grupos.gestionar"):
            for g in conn.execute("SELECT id, public_id, name, status FROM work_groups WHERE owner_id = ?"
                                  " ORDER BY status, name COLLATE NOCASE", (actor.id,)):
                out.append({"key": g["public_id"], "group_id": g["id"], "name": g["name"], "kind": "grupo", "status": g["status"]})
        for g in member:
            if not any(x["group_id"] == g["id"] for x in out):
                out.append({"key": g["public_id"], "group_id": g["id"], "name": g["name"], "kind": "grupo", "status": g["status"]})
        return out

    def resolve(self, conn: sqlite3.Connection, actor: Actor, key: str | None) -> int | None:
        """group_id del inventario pedido (None = general). Sin clave: el predeterminado de la persona."""
        options = self.accessible(conn, actor)
        if not options:
            raise PermissionDenied("No tiene acceso a ningún inventario.")
        key = (key or "").strip()
        if not key:
            return options[0]["group_id"]
        for o in options:
            if o["key"] == key[:20]:
                return o["group_id"]
        raise NotFoundError("Inventario no encontrado.")   # el de otro grupo no existe para esta persona

    def check(self, conn: sqlite3.Connection, actor: Actor, group_id: int | None, what: str = "Producto") -> None:
        """Rechaza (404) el acceso a un registro de un inventario ajeno."""
        if not any(o["group_id"] == group_id for o in self.accessible(conn, actor)):
            raise NotFoundError(f"{what} no encontrado.")

    def describe(self, conn: sqlite3.Connection, group_id: int | None) -> dict:
        if group_id is None:
            return {"key": GENERAL, "name": GENERAL_NAME, "kind": "general"}
        g = conn.execute("SELECT public_id, name FROM work_groups WHERE id = ?", (group_id,)).fetchone()
        return {"key": g["public_id"], "name": g["name"], "kind": "grupo"}

    # ------------------------------------------------------------------ aviso en vivo
    @staticmethod
    def audience(conn: sqlite3.Connection, group_id: int | None) -> set[int]:
        if group_id is None:
            return {r[0] for r in conn.execute(
                "SELECT u.id FROM users u WHERE u.active = 1 AND (u.role = 'admin' OR NOT EXISTS (SELECT 1 FROM"
                " work_group_members m WHERE m.user_id = u.id AND m.status = 'activo'))")}
        people = {r[0] for r in conn.execute("SELECT user_id FROM work_group_members WHERE group_id = ? AND status = 'activo'",
                                              (group_id,))}
        owner = conn.execute("SELECT owner_id FROM work_groups WHERE id = ?", (group_id,)).fetchone()
        return people | ({owner[0]} if owner else set())

    def notify(self, group_id: int | None, change: str, **details) -> None:
        """Avisa a todos los que trabajan en ese inventario que algo cambió (después de confirmar en la base)."""
        if self.hub is None:
            return
        with self.db.read() as conn:
            people = self.audience(conn, group_id)
            key = self.describe(conn, group_id)["key"]
        self.hub.publish(people, {"type": "inventario", "inventory": key, "change": change, **details})
