"""Acceso a los inventarios: ADMINISTRADOR → INVENTARIOS → GRUPO → INTEGRANTES AUTORIZADOS.

Reglas (se validan en el servidor en cada operación; la interfaz solo elige):
- El administrador DUEÑO de un inventario entra siempre (también si está inactivo o archivado) con
  todos los permisos de inventario. Otro administrador no lo ve: para él no existe (404).
- Un empleado entra a un inventario ACTIVO si es integrante activo del grupo asociado y tiene permisos
  en ese inventario: los que el administrador le dio (inventory_members) o, si no se los ha definido, los
  permisos iniciales del inventario cuando «autorizar a los nuevos integrantes» está activo.
- Un inventario sin grupo (empresa que aún no usa grupos, o el «Inventario general» migrado mientras se
  asocia) admite a quienes tienen permisos explícitos en él y, con la autorización automática, a los
  empleados que no pertenecen a ningún grupo (con los permisos iniciales del inventario).
- Permiso efectivo de inventario = permiso del usuario Y permiso en ese inventario.

La interfaz envía el inventario elegido en la cabecera X-Inventory (id público «I-…»). La API construye
para cada petición un Actor con los permisos de ESE inventario (scope_actor) y check() rechaza registros
de otro inventario aunque se manipulen identificadores.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from ..core.actor import Actor
from ..core.errors import NotFoundError, PermissionDenied, ValidationError
from ..core.permissions import DEFAULT_INVENTORY_MEMBER, INVENTORY_SCOPED

DEFAULT_SETTINGS = {"auto_authorize": True, "member_permissions": sorted(DEFAULT_INVENTORY_MEMBER),
                    "allow_negative_stock": None, "low_stock_alerts": True}


def settings_of(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        data = {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in data.items() if k in DEFAULT_SETTINGS}}


class InventoryScopes:
    def __init__(self, db, hub=None):
        self.db = db
        self.hub = hub

    # ------------------------------------------------------------------ permisos de una persona en un inventario
    @staticmethod
    def member_permissions(conn: sqlite3.Connection, inv, user_id: int | None) -> set[str]:
        """Permisos de inventario de un empleado en ese inventario (vacío = no entra)."""
        if not user_id or inv["status"] != "activo":
            return set()
        if inv["group_id"] is not None:
            active = conn.execute("SELECT 1 FROM work_group_members WHERE group_id = ? AND user_id = ? AND status = 'activo'",
                                  (inv["group_id"], user_id)).fetchone()
            if not active:
                return set()
        row = conn.execute("SELECT permissions FROM inventory_members WHERE inventory_id = ? AND user_id = ?",
                           (inv["id"], user_id)).fetchone()
        if row is not None:
            return set(json.loads(row["permissions"] or "[]")) & INVENTORY_SCOPED
        cfg = settings_of(inv["settings"])
        if not cfg["auto_authorize"]:
            return set()
        if inv["group_id"] is None:
            # Inventario sin grupo (empresa que aún no usa grupos): los empleados que no pertenecen a ningún grupo.
            in_group = conn.execute("SELECT 1 FROM work_group_members WHERE user_id = ? AND status = 'activo'", (user_id,)).fetchone()
            employee = conn.execute("SELECT 1 FROM users WHERE id = ? AND role = 'employee' AND active = 1", (user_id,)).fetchone()
            if in_group or not employee:
                return set()
        return set(cfg["member_permissions"]) & INVENTORY_SCOPED

    def _accessible_rows(self, conn: sqlite3.Connection, actor: Actor) -> list[tuple[sqlite3.Row, set[str], bool]]:
        if not actor.id:
            return [(r, set(INVENTORY_SCOPED), True) for r in conn.execute("SELECT * FROM inventories ORDER BY id")]
        out = []
        for inv in conn.execute(
                "SELECT i.* FROM inventories i WHERE i.owner_id = ? OR i.status = 'activo' AND (i.id IN (SELECT inventory_id"
                " FROM inventory_members WHERE user_id = ?) OR i.group_id IN (SELECT group_id FROM work_group_members"
                " WHERE user_id = ? AND status = 'activo') OR i.group_id IS NULL AND ? = 'employee')"
                " ORDER BY i.status <> 'activo', i.name COLLATE NOCASE, i.id",
                (actor.id, actor.id, actor.id, actor.role)):
            if inv["owner_id"] == actor.id:
                out.append((inv, set(INVENTORY_SCOPED), True))
                continue
            perms = self.member_permissions(conn, inv, actor.id)
            if perms:
                out.append((inv, perms, False))
        return out

    def accessible(self, conn: sqlite3.Connection, actor: Actor) -> list[dict]:
        """Inventarios a los que entra esta persona (el primero activo es el predeterminado)."""
        result = []
        for inv, perms, owner in self._accessible_rows(conn, actor):
            group = conn.execute("SELECT public_id, name, status FROM work_groups WHERE id = ?", (inv["group_id"],)).fetchone() \
                if inv["group_id"] else None
            result.append({
                "key": inv["public_id"], "inventory_id": inv["id"], "name": inv["name"], "status": inv["status"],
                "owner": owner, "group": dict(group) if group else None,
                "permissions": sorted(perms & actor.permissions) if actor.id else sorted(perms),
            })
        return result

    def scope_actor(self, conn: sqlite3.Connection, actor: Actor, key: str | None) -> Actor:
        """Actor de la petición con los permisos de inventario del inventario elegido (o del predeterminado)."""
        rows = self._accessible_rows(conn, actor)
        chosen = None
        key = (key or "").strip()
        if key:
            chosen = next((r for r in rows if r[0]["public_id"] == key[:20]), None)
        if chosen is None and not key:
            chosen = next((r for r in rows if r[0]["status"] == "activo"), rows[0] if rows else None)
        base = actor.permissions - INVENTORY_SCOPED
        if chosen is None:
            return replace(actor, permissions=frozenset(base), inventory_id=None)
        inv, perms, _ = chosen
        return replace(actor, permissions=frozenset(base | (actor.permissions & perms)), inventory_id=inv["id"])

    def resolve(self, conn: sqlite3.Connection, actor: Actor, key: str | None) -> int:
        """id del inventario pedido. Sin clave: el de la petición o el predeterminado de la persona."""
        rows = self._accessible_rows(conn, actor)
        key = (key or "").strip()
        if key:
            for inv, _, _ in rows:
                if inv["public_id"] == key[:20]:
                    if actor.inventory_id is not None and inv["id"] != actor.inventory_id:
                        break
                    return inv["id"]
            raise NotFoundError("Inventario no encontrado.")   # el de otro administrador o grupo no existe para esta persona
        if actor.inventory_id is not None and any(inv["id"] == actor.inventory_id for inv, _, _ in rows):
            return actor.inventory_id
        active = [inv for inv, _, _ in rows if inv["status"] == "activo"]
        if active:
            return active[0]["id"]
        if rows:
            return rows[0][0]["id"]
        raise PermissionDenied("No tiene acceso a ningún inventario. Pida al administrador que lo autorice en un inventario.")

    def check(self, conn: sqlite3.Connection, actor: Actor, inventory_id: int | None, what: str = "Producto") -> None:
        """Rechaza (404) un registro de un inventario ajeno o distinto del inventario de la petición."""
        if actor.inventory_id is not None and inventory_id != actor.inventory_id:
            raise NotFoundError(f"{what} no encontrado.")
        if not any(inv["id"] == inventory_id for inv, _, _ in self._accessible_rows(conn, actor)):
            raise NotFoundError(f"{what} no encontrado.")

    @staticmethod
    def require_active(conn: sqlite3.Connection, inventory_id: int) -> None:
        row = conn.execute("SELECT status, name FROM inventories WHERE id = ?", (inventory_id,)).fetchone()
        if row and row["status"] != "activo":
            raise ValidationError(f"El inventario «{row['name']}» está {row['status']}: actívelo para registrar operaciones.")

    @staticmethod
    def allow_negative(conn: sqlite3.Connection, inventory_id: int | None, default: bool) -> bool:
        if inventory_id is None:
            return default
        row = conn.execute("SELECT settings FROM inventories WHERE id = ?", (inventory_id,)).fetchone()
        value = settings_of(row["settings"])["allow_negative_stock"] if row else None
        return default if value is None else bool(value)

    @staticmethod
    def describe(conn: sqlite3.Connection, inventory_id: int) -> dict:
        inv = conn.execute("SELECT i.public_id, i.name, i.status, g.name AS group_name FROM inventories i"
                           " LEFT JOIN work_groups g ON g.id = i.group_id WHERE i.id = ?", (inventory_id,)).fetchone()
        if not inv:
            raise NotFoundError("Inventario no encontrado.")
        return {"key": inv["public_id"], "name": inv["name"], "status": inv["status"], "group": inv["group_name"]}

    # ------------------------------------------------------------------ aviso en vivo
    def audience(self, conn: sqlite3.Connection, inventory_id: int) -> set[int]:
        inv = conn.execute("SELECT * FROM inventories WHERE id = ?", (inventory_id,)).fetchone()
        if not inv:
            return set()
        people = {inv["owner_id"]}
        candidates = {r[0] for r in conn.execute("SELECT user_id FROM inventory_members WHERE inventory_id = ?", (inventory_id,))}
        if inv["group_id"] is not None:
            candidates |= {r[0] for r in conn.execute(
                "SELECT user_id FROM work_group_members WHERE group_id = ? AND status = 'activo'", (inv["group_id"],))}
        else:
            candidates |= {r[0] for r in conn.execute("SELECT id FROM users WHERE role = 'employee' AND active = 1")}
        people |= {uid for uid in candidates if self.member_permissions(conn, inv, uid)}
        return people

    def notify(self, inventory_id: int | None, change: str, **details) -> None:
        """Avisa a todos los que trabajan en ese inventario que algo cambió (después de confirmar en la base)."""
        if self.hub is None or inventory_id is None:
            return
        with self.db.read() as conn:
            people = self.audience(conn, inventory_id)
            key = self.describe(conn, inventory_id)["key"]
        self.hub.publish(people, {"type": "inventario", "inventory": key, "change": change, **details})
