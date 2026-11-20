"""Administración de inventarios: el administrador crea uno o varios inventarios, cada uno asociado a un
grupo suyo, y decide qué puede hacer cada integrante en cada inventario.

- Solo el administrador DUEÑO ve y administra sus inventarios (otro administrador recibe 404).
- Un grupo tiene como máximo un inventario y un inventario un solo grupo (índice único).
- Integrantes autorizados: solo integrantes activos del grupo. Sus permisos en el inventario se
  combinan con sus permisos de usuario (debe tener ambos).
- Eliminar solo se permite si el inventario no tiene historia (productos, ventas, documentos,
  movimientos, plantillas). Con historia se desactiva o archiva: nunca se destruye información.
- Cada inventario tiene su configuración (existencias negativas, alertas, permisos iniciales) y sus
  columnas personalizadas («Observaciones» del sistema se crea al crearlo).
"""
from __future__ import annotations

import json
import secrets
import sqlite3

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.permissions import ASSIGNABLE_TO_EMPLOYEE, BY_CODE, INVENTORY_SCOPED

MEMBER_ASSIGNABLE = INVENTORY_SCOPED & ASSIGNABLE_TO_EMPLOYEE
from .scopes import DEFAULT_SETTINGS, InventoryScopes, settings_of

STATUSES = ("activo", "inactivo", "archivado")


def new_public_id(conn: sqlite3.Connection) -> str:
    while True:
        pid = "I-" + secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM inventories WHERE public_id = ?", (pid,)).fetchone():
            return pid


def create_inventory_conn(conn: sqlite3.Connection, owner_id: int, name: str, group_id: int | None = None,
                          description: str = "", settings: dict | None = None, created_by: int | None = None) -> int:
    """Crea el inventario con su configuración y su columna del sistema «Observaciones». No crea productos."""
    now = iso()
    inv = conn.execute(
        "INSERT INTO inventories(public_id, owner_id, group_id, name, description, settings, created_by, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (new_public_id(conn), owner_id, group_id, name, description, json.dumps({**DEFAULT_SETTINGS, **(settings or {})}),
         created_by or owner_id, now, now)).lastrowid
    conn.execute("INSERT INTO inventory_columns(inventory_id, name, data_type, description, position, is_system, created_at,"
                 " updated_at, created_by, updated_by) VALUES (?, 'Observaciones', 'texto_largo',"
                 " 'Información adicional sobre el producto (texto libre).', 10, 1, ?, ?, ?, ?)",
                 (inv, now, now, owner_id, owner_id))
    return inv


class InventoryAdminService:
    def __init__(self, db, scopes: InventoryScopes):
        self.db = db
        self.scopes = scopes

    # ------------------------------------------------------------------ utilidades
    def _own(self, conn: sqlite3.Connection, actor: Actor, public_id: str):
        row = conn.execute("SELECT * FROM inventories WHERE public_id = ?", (str(public_id)[:20],)).fetchone()
        if not row or row["owner_id"] != actor.id:
            raise NotFoundError("Inventario no encontrado.")
        return row

    def _group(self, conn: sqlite3.Connection, actor: Actor, group_key: str | None, inventory_id: int | None = None):
        if not group_key:
            return None
        g = conn.execute("SELECT * FROM work_groups WHERE public_id = ?", (str(group_key)[:20],)).fetchone()
        if not g or g["owner_id"] != actor.id:
            raise ValidationError("Elija uno de sus grupos.", {"group": "Grupo no válido."})
        taken = conn.execute("SELECT name FROM inventories WHERE group_id = ? AND id IS NOT ?", (g["id"], inventory_id)).fetchone()
        if taken:
            raise ConflictError(f"El grupo «{g['name']}» ya tiene el inventario «{taken['name']}». Cada grupo tiene un solo inventario.",
                                {"group": "Grupo con inventario."})
        return g

    @staticmethod
    def _clean_settings(raw: dict | None, current: dict | None = None) -> dict:
        cfg = {**(current or DEFAULT_SETTINGS)}
        raw = raw or {}
        if "auto_authorize" in raw:
            cfg["auto_authorize"] = bool(raw["auto_authorize"])
        if "low_stock_alerts" in raw:
            cfg["low_stock_alerts"] = bool(raw["low_stock_alerts"])
        if "allow_negative_stock" in raw:
            v = raw["allow_negative_stock"]
            cfg["allow_negative_stock"] = None if v in (None, "", "global") else bool(v)
        if "member_permissions" in raw:
            perms = set(raw["member_permissions"] or [])
            if perms - MEMBER_ASSIGNABLE:
                raise ValidationError("Permisos no válidos para empleados.",
                                      {"member_permissions": ", ".join(sorted(perms - MEMBER_ASSIGNABLE))})
            cfg["member_permissions"] = sorted(perms)
        return cfg

    def _summary(self, conn: sqlite3.Connection, inv) -> dict:
        stats = conn.execute("SELECT COUNT(*) AS products, COALESCE(SUM(CASE WHEN active = 1 THEN stock_milli END), 0) AS stock_milli,"
                             " SUM(active = 1 AND stock_milli <= min_stock_milli) AS low_stock, MAX(updated_at) AS products_updated"
                             " FROM products WHERE inventory_id = ?", (inv["id"],)).fetchone()
        first = [dict(r) for r in conn.execute("SELECT code, description, stock_milli, unit FROM products WHERE inventory_id = ?"
                                                " AND active = 1 ORDER BY id LIMIT 2", (inv["id"],))]
        last_move = conn.execute("SELECT MAX(m.created_at) FROM inventory_movements m JOIN products p ON p.id = m.product_id"
                                 " WHERE p.inventory_id = ?", (inv["id"],)).fetchone()[0]
        updated = max(x for x in (inv["updated_at"], stats["products_updated"], last_move) if x)
        return {"products": stats["products"], "stock_milli": stats["stock_milli"], "low_stock": stats["low_stock"] or 0,
                "first_products": first, "last_update": updated}

    def _public(self, conn: sqlite3.Connection, inv, actor: Actor, detail: bool = False) -> dict:
        group = conn.execute("SELECT public_id, name, status FROM work_groups WHERE id = ?", (inv["group_id"],)).fetchone() \
            if inv["group_id"] else None
        out = {"key": inv["public_id"], "name": inv["name"], "description": inv["description"], "status": inv["status"],
               "group": dict(group) if group else None, "owner": inv["owner_id"] == actor.id,
               "created_at": inv["created_at"], "updated_at": inv["updated_at"], "version": inv["version"],
               **self._summary(conn, inv)}
        if detail:
            out["settings"] = settings_of(inv["settings"])
            out["members"] = self._members(conn, inv)
            out["history"] = self._history(conn, inv["id"])
        return out

    @staticmethod
    def _history(conn: sqlite3.Connection, inventory_id: int) -> dict:
        q = lambda sql: conn.execute(sql, (inventory_id,)).fetchone()[0]   # noqa: E731
        return {"products": q("SELECT COUNT(*) FROM products WHERE inventory_id = ?"),
                "sales": q("SELECT COUNT(*) FROM sales WHERE inventory_id = ?"),
                "documents": q("SELECT COUNT(*) FROM commercial_documents WHERE inventory_id = ?"),
                "movements": q("SELECT COUNT(*) FROM inventory_movements m JOIN products p ON p.id = m.product_id WHERE p.inventory_id = ?"),
                "templates": q("SELECT COUNT(*) FROM print_templates WHERE inventory_id = ?")}

    def _members(self, conn: sqlite3.Connection, inv) -> list[dict]:
        """Integrantes del grupo (y autorizados sin grupo) con sus permisos en este inventario."""
        people: dict[int, dict] = {}
        if inv["group_id"]:
            for r in conn.execute("SELECT u.id, u.full_name, u.username, u.role, u.active, m.status FROM work_group_members m"
                                  " JOIN users u ON u.id = m.user_id WHERE m.group_id = ? AND m.status IN ('activo','pendiente')",
                                  (inv["group_id"],)):
                people[r["id"]] = {**dict(r), "in_group": r["status"] == "activo"}
        if inv["group_id"] is None:
            for r in conn.execute("SELECT u.id, u.full_name, u.username, u.role, u.active FROM users u WHERE u.role = 'employee'"
                                  " AND u.active = 1 AND NOT EXISTS (SELECT 1 FROM work_group_members m WHERE m.user_id = u.id"
                                  " AND m.status = 'activo')"):
                people[r["id"]] = {**dict(r), "status": None, "in_group": True}
        for r in conn.execute("SELECT u.id, u.full_name, u.username, u.role, u.active FROM inventory_members im JOIN users u"
                              " ON u.id = im.user_id WHERE im.inventory_id = ?", (inv["id"],)):
            people.setdefault(r["id"], {**dict(r), "status": None, "in_group": inv["group_id"] is None})
        out = []
        for uid, p in people.items():
            row = conn.execute("SELECT permissions FROM inventory_members WHERE inventory_id = ? AND user_id = ?",
                               (inv["id"], uid)).fetchone()
            user_perms = conn.execute("SELECT permission FROM user_permissions WHERE user_id = ?", (uid,)).fetchall() \
                if _has_table(conn, "user_permissions") else []
            effective = sorted(self.scopes.member_permissions(conn, inv, uid))
            out.append({"id": uid, "full_name": p["full_name"], "username": p["username"], "role": p["role"],
                        "in_group": p["in_group"], "custom": row is not None,
                        "permissions": sorted(json.loads(row["permissions"])) if row else effective,
                        "effective": effective, "user_permissions": sorted(r[0] for r in user_perms)})
        return sorted(out, key=lambda m: m["full_name"].lower())

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor) -> list[dict]:
        """Inventarios a los que entra la persona, con el resumen de las tarjetas (datos reales)."""
        with self.db.read() as conn:
            result = []
            for o in self.scopes.accessible(conn, actor):
                inv = conn.execute("SELECT * FROM inventories WHERE id = ?", (o["inventory_id"],)).fetchone()
                item = self._public(conn, inv, actor)
                item["permissions"] = o["permissions"]
                result.append(item)
            return result

    def get(self, actor: Actor, public_id: str) -> dict:
        with self.db.read() as conn:
            return self._public(conn, self._own(conn, actor, public_id), actor, detail=True)

    def catalog(self) -> list[dict]:
        return [{"code": c, "label": BY_CODE[c].label, "group": BY_CODE[c].group} for c in sorted(MEMBER_ASSIGNABLE)]

    def groups(self, actor: Actor) -> list[dict]:
        """Grupos del administrador y si ya tienen inventario (para el formulario)."""
        actor.require("grupos.gestionar")
        with self.db.read() as conn:
            out = []
            for r in conn.execute("SELECT g.id, g.public_id AS key, g.name, g.status, i.name AS inventory_name, i.public_id AS inventory_key"
                                  " FROM work_groups g LEFT JOIN inventories i ON i.group_id = g.id WHERE g.owner_id = ?"
                                  " ORDER BY g.name COLLATE NOCASE", (actor.id,)).fetchall():
                g = dict(r)
                g["members"] = [dict(m) for m in conn.execute(
                    "SELECT u.id, u.full_name, u.username FROM work_group_members m JOIN users u ON u.id = m.user_id"
                    " WHERE m.group_id = ? AND m.status = 'activo' AND u.role = 'employee' ORDER BY u.full_name COLLATE NOCASE",
                    (g.pop("id"),))]
                out.append(g)
            return out

    # ------------------------------------------------------------------ crear y editar
    def _validate(self, data: dict, partial: bool = False) -> dict:
        out = {}
        if not partial or "name" in data:
            name = " ".join(str(data.get("name") or "").split())
            if not name or len(name) > 80:
                raise ValidationError("Revise el nombre.", {"name": "Nombre obligatorio (máximo 80 caracteres)."})
            out["name"] = name
        if "description" in data:
            desc = str(data.get("description") or "").strip()
            if len(desc) > 300:
                raise ValidationError("Revise la descripción.", {"description": "Máximo 300 caracteres."})
            out["description"] = desc
        return out

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("grupos.gestionar")
        values = self._validate(data)
        if not data.get("group"):
            raise ValidationError("Elija el grupo al que pertenece el inventario.", {"group": "Grupo obligatorio."})
        settings = self._clean_settings(data.get("settings"))
        with self.db.tx() as conn:
            if conn.execute("SELECT 1 FROM inventories WHERE owner_id = ? AND name = ? COLLATE NOCASE",
                            (actor.id, values["name"])).fetchone():
                raise ConflictError("Ya tiene un inventario con ese nombre.", {"name": "Nombre repetido."})
            g = self._group(conn, actor, data.get("group"))
            inv_id = create_inventory_conn(conn, actor.id, values["name"], g["id"], values.get("description", ""), settings, actor.id)
            inv = conn.execute("SELECT * FROM inventories WHERE id = ?", (inv_id,)).fetchone()
            self._apply_members(conn, actor, inv, data.get("members"))
            record(conn, actor, "inventario.crear", "inventory", inv_id, {"nombre": values["name"], "grupo": g["name"]})
            public_id = inv["public_id"]
        self._notify_people(public_id)
        return self.get(actor, public_id)

    def update(self, actor: Actor, public_id: str, data: dict) -> dict:
        actor.require("grupos.gestionar")
        with self.db.tx() as conn:
            inv = self._own(conn, actor, public_id)
            if data.get("version") is not None and int(data["version"]) != inv["version"]:
                raise ConflictError("Otra persona modificó este inventario. Recargue y vuelva a intentarlo.")
            values = self._validate(data, partial=True)
            changes: dict = {}
            if "name" in values and values["name"] != inv["name"]:
                if conn.execute("SELECT 1 FROM inventories WHERE owner_id = ? AND name = ? COLLATE NOCASE AND id <> ?",
                                (actor.id, values["name"], inv["id"])).fetchone():
                    raise ConflictError("Ya tiene un inventario con ese nombre.", {"name": "Nombre repetido."})
                changes["name"] = values["name"]
            if "description" in values:
                changes["description"] = values["description"]
            if "group" in data:
                g = self._group(conn, actor, data.get("group"), inv["id"])
                if g is None and inv["group_id"] is not None:
                    raise ValidationError("Un inventario debe estar asociado a un grupo.", {"group": "Grupo obligatorio."})
                if g is not None:
                    changes["group_id"] = g["id"]
            if "status" in data:
                if data["status"] not in STATUSES:
                    raise ValidationError("Estado no válido.", {"status": "Activo, inactivo o archivado."})
                changes["status"] = data["status"]
            if "settings" in data:
                changes["settings"] = json.dumps(self._clean_settings(data["settings"], settings_of(inv["settings"])))
            if changes:
                sets = ", ".join(f"{k} = ?" for k in changes)
                conn.execute(f"UPDATE inventories SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",  # noqa: S608
                             (*changes.values(), iso(), inv["id"]))
                record(conn, actor, "inventario.actualizar", "inventory", inv["id"],
                       {k: (v if k != "settings" else json.loads(v)) for k, v in changes.items()})
            inv = conn.execute("SELECT * FROM inventories WHERE id = ?", (inv["id"],)).fetchone()
            if "members" in data:
                self._apply_members(conn, actor, inv, data["members"])
        self._notify_people(public_id)
        return self.get(actor, public_id)

    def _apply_members(self, conn: sqlite3.Connection, actor: Actor, inv, members) -> None:
        """members: [{"user_id", "permissions": [...] | None}] — None = vuelve a los permisos iniciales del inventario."""
        if not members:
            return
        allowed = set()
        if inv["group_id"]:
            allowed = {r[0] for r in conn.execute("SELECT user_id FROM work_group_members WHERE group_id = ? AND status = 'activo'",
                                                  (inv["group_id"],))}
        else:
            allowed = {r[0] for r in conn.execute("SELECT id FROM users WHERE role = 'employee' AND active = 1")}
        now = iso()
        for m in members:
            try:
                uid = int(m.get("user_id"))
            except (TypeError, ValueError, AttributeError):
                raise ValidationError("Integrante no válido.") from None
            if uid not in allowed:
                raise ValidationError("Solo se autorizan integrantes activos del grupo del inventario.",
                                      {"members": "Persona fuera del grupo."})
            perms = m.get("permissions")
            if perms is None:
                conn.execute("DELETE FROM inventory_members WHERE inventory_id = ? AND user_id = ?", (inv["id"], uid))
                continue
            perms = set(perms)
            if perms - MEMBER_ASSIGNABLE:
                raise ValidationError("Permisos no válidos para empleados (algunos son solo de administradores).",
                                      {"members": ", ".join(sorted(perms - MEMBER_ASSIGNABLE))})
            conn.execute("INSERT INTO inventory_members(inventory_id, user_id, permissions, granted_by, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?) ON CONFLICT(inventory_id, user_id) DO UPDATE SET permissions = excluded.permissions,"
                         " granted_by = excluded.granted_by, updated_at = excluded.updated_at",
                         (inv["id"], uid, json.dumps(sorted(perms)), actor.id, now, now))
            record(conn, actor, "inventario.permisos", "inventory", inv["id"], {"usuario": uid, "permisos": sorted(perms)})

    def delete(self, actor: Actor, public_id: str) -> dict:
        actor.require("grupos.gestionar")
        with self.db.tx() as conn:
            inv = self._own(conn, actor, public_id)
            hist = self._history(conn, inv["id"])
            if any(hist.values()):
                detail = ", ".join(f"{v} {k}" for k, v in {"productos": hist["products"], "ventas": hist["sales"],
                                                           "documentos": hist["documents"], "movimientos": hist["movements"],
                                                           "plantillas": hist["templates"]}.items() if v)
                raise ValidationError(f"El inventario tiene historia ({detail}): no se elimina para no perder información."
                                      " Desactívelo o archívelo.")
            owned = conn.execute("SELECT COUNT(*) FROM inventories WHERE owner_id = ?", (actor.id,)).fetchone()[0]
            if owned <= 1:
                raise ValidationError("Es su único inventario: cree otro antes de eliminar este.")
            conn.execute("DELETE FROM inventory_members WHERE inventory_id = ?", (inv["id"],))
            conn.execute("DELETE FROM inventory_custom_values WHERE column_id IN (SELECT id FROM inventory_columns"
                         " WHERE inventory_id = ?)", (inv["id"],))
            conn.execute("DELETE FROM inventory_columns WHERE inventory_id = ? AND is_system = 0", (inv["id"],))
            conn.execute("DROP TRIGGER IF EXISTS inventory_columns_system_no_delete")
            conn.execute("DELETE FROM inventory_columns WHERE inventory_id = ?", (inv["id"],))
            conn.execute("CREATE TRIGGER inventory_columns_system_no_delete BEFORE DELETE ON inventory_columns WHEN OLD.is_system = 1"
                         " BEGIN SELECT RAISE(ABORT, 'Las columnas del sistema no se eliminan'); END")
            conn.execute("DELETE FROM inventories WHERE id = ?", (inv["id"],))
            record(conn, actor, "inventario.eliminar", "inventory", inv["id"], {"nombre": inv["name"]})
        return {"deleted": public_id}

    def _notify_people(self, public_id: str) -> None:
        """Avisa a quienes ganaron o perdieron acceso para que su interfaz recargue la lista de inventarios."""
        if self.scopes.hub is None:
            return
        with self.db.read() as conn:
            inv = conn.execute("SELECT * FROM inventories WHERE public_id = ?", (public_id,)).fetchone()
            if not inv:
                return
            people = {inv["owner_id"]} | {r[0] for r in conn.execute("SELECT user_id FROM inventory_members WHERE inventory_id = ?",
                                                                       (inv["id"],))}
            if inv["group_id"]:
                people |= {r[0] for r in conn.execute("SELECT user_id FROM work_group_members WHERE group_id = ?", (inv["group_id"],))}
        self.scopes.hub.publish(people, {"type": "inventario", "inventory": public_id, "change": "configuracion"})


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())
