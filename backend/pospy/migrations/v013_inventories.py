"""Inventarios como entidad propia: ADMINISTRADOR → INVENTARIOS → GRUPO → INTEGRANTES AUTORIZADOS.

Antes (v011) el inventario ERA el grupo: products.group_id (NULL = «Inventario general»). Eso dejaba
al administrador trabajando en el inventario general y a sus empleados (integrantes de un grupo) en
el inventario VACÍO del grupo: nunca veían lo mismo.

Ahora:
- inventories: dueño (administrador), grupo asociado (uno por inventario y como máximo un inventario
  por grupo), nombre, descripción, estado (activo / inactivo / archivado) y configuración propia.
- inventory_members: permisos de cada integrante en ese inventario (se combinan con sus permisos de
  usuario: debe tener ambos).
- products, sales, commercial_documents, print_templates e inventory_columns pasan de group_id a
  inventory_id (NOT NULL). Cambiar el grupo de un inventario ya no obliga a reescribir sus datos.

Migración de datos (sin borrar nada):
- Cada grupo que ya tenía datos (productos, ventas, documentos o plantillas) recibe un inventario con su
  nombre, del dueño del grupo, y sus integrantes activos conservan el acceso.
- Lo que estaba en el «Inventario general» pasa a un inventario «Inventario general» SIN grupo, del
  primer administrador. Como no se puede saber a qué grupo pertenece, el administrador lo asocia desde
  Gestión › Administrar inventarios (proceso controlado). Mientras tanto conserva el acceso anterior:
  el dueño y los empleados que no pertenecían a ningún grupo.
- Las columnas personalizadas se copian a cada inventario migrado (con sus valores).
- Es idempotente: se registra en schema_migrations y además cada inserción comprueba que no exista.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3

VERSION = 13
NAME = "inventarios por administrador asociados a grupos, integrantes autorizados y permisos por inventario"
FOREIGN_KEYS_OFF = True

SCOPED = ["inventario.ver", "inventario.costos", "inventario.editar", "inventario.movimientos", "inventario.importar",
          "inventario.columnas", "observaciones.ver", "observaciones.crear", "observaciones.editar", "observaciones.estado",
          "observaciones.comentar", "observaciones.eliminar", "ventas.vender", "ventas.descuento", "ventas.historial",
          "ventas.anular", "documentos.ver", "documentos.crear", "documentos.anular", "documentos.imprimir"]
# member_permissions None: sin restricción, cada integrante conserva sus permisos de usuario.
DEFAULT_SETTINGS = {"auto_authorize": True, "member_permissions": None, "allow_negative_stock": None,
                    "low_stock_alerts": True}
OLD_REF = "group_id INTEGER REFERENCES work_groups(id)"
NEW_REF = "inventory_id INTEGER NOT NULL REFERENCES inventories(id)"

DDL = r"""
CREATE TABLE IF NOT EXISTS inventories(
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  owner_id INTEGER NOT NULL REFERENCES users(id),
  group_id INTEGER UNIQUE REFERENCES work_groups(id),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 300),
  status TEXT NOT NULL DEFAULT 'activo' CHECK(status IN ('activo','inactivo','archivado')),
  settings TEXT NOT NULL DEFAULT '{}',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_inventories_owner ON inventories(owner_id, status);
CREATE TABLE IF NOT EXISTS inventory_members(
  inventory_id INTEGER NOT NULL REFERENCES inventories(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  permissions TEXT NOT NULL DEFAULT '[]',
  granted_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(inventory_id, user_id)
);
CREATE TRIGGER IF NOT EXISTS inventories_no_delete_with_data BEFORE DELETE ON inventories
WHEN EXISTS (SELECT 1 FROM products WHERE inventory_id = OLD.id) OR EXISTS (SELECT 1 FROM sales WHERE inventory_id = OLD.id)
  OR EXISTS (SELECT 1 FROM commercial_documents WHERE inventory_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'Un inventario con productos, ventas o documentos no se elimina: archívelo'); END;
"""

NOW = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"


def _pid(conn: sqlite3.Connection) -> str:
    while True:
        pid = "I-" + secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM inventories WHERE public_id = ?", (pid,)).fetchone():
            return pid


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))  # noqa: S608 - tabla fija


def _create_inventory(conn, owner: int, group_id: int | None, name: str) -> int:
    row = conn.execute("SELECT id FROM inventories WHERE group_id IS ? AND (group_id IS NOT NULL OR name = ?)",
                       (group_id, name)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        f"INSERT INTO inventories(public_id, owner_id, group_id, name, settings, created_by, created_at, updated_at)"
        f" VALUES (?,?,?,?,?,?,{NOW},{NOW})", (_pid(conn), owner, group_id, name[:80], json.dumps(DEFAULT_SETTINGS), owner)
    ).lastrowid


def _rebuild(conn: sqlite3.Connection, table: str, mapping_sql: str) -> None:
    """Reconstruye la tabla cambiando group_id por inventory_id (procedimiento oficial de SQLite)."""
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    if OLD_REF not in ddl:
        raise RuntimeError(f"La tabla {table} no tiene la columna esperada: {OLD_REF}")
    extras = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index','trigger')"
                                         " AND sql IS NOT NULL", (table,))]
    new_ddl = ddl.replace(OLD_REF, NEW_REF, 1)
    new_ddl = re.sub(rf"^CREATE TABLE\s+\"?{table}\"?", f"CREATE TABLE {table}_v13", new_ddl, count=1)
    conn.execute(new_ddl)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]  # noqa: S608
    target = ["inventory_id" if c == "group_id" else c for c in cols]
    source = [mapping_sql if c == "group_id" else c for c in cols]
    conn.execute(f"INSERT INTO {table}_v13({', '.join(target)}) SELECT {', '.join(source)} FROM {table} t")  # noqa: S608
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_v13 RENAME TO {table}")
    for sql in extras:
        conn.execute(re.sub(r"\bgroup_id\b", "inventory_id", sql))


def run(conn: sqlite3.Connection) -> None:
    for stmt in DDL.split(";\n"):
        if stmt.strip():
            conn.execute(stmt + (";" if "BEGIN" in stmt else ""))
    if not _has_col(conn, "products", "group_id"):
        return                                   # ya migrado
    admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY active DESC, id LIMIT 1").fetchone()
    tables = ("products", "sales", "commercial_documents", "print_templates")
    groups_with_data: set[int] = set()
    general_has_data = False
    for t in tables:
        for (g,) in conn.execute(f"SELECT DISTINCT group_id FROM {t}"):  # noqa: S608
            if g is None:
                general_has_data = True
            else:
                groups_with_data.add(g)
    inventories: dict[int | None, int] = {}
    for g in sorted(groups_with_data):
        grp = conn.execute("SELECT owner_id, name FROM work_groups WHERE id = ?", (g,)).fetchone()
        inventories[g] = _create_inventory(conn, grp[0], g, grp[1])
        for (uid,) in conn.execute("SELECT user_id FROM work_group_members WHERE group_id = ? AND status = 'activo'", (g,)):
            conn.execute(f"INSERT OR IGNORE INTO inventory_members(inventory_id, user_id, permissions, created_at, updated_at)"
                         f" VALUES (?,?,?,{NOW},{NOW})", (inventories[g], uid, json.dumps(SCOPED)))
    if general_has_data or admin:
        if not admin:
            raise RuntimeError("Hay datos de inventario pero ningún administrador al que asignarlos.")
        general = _create_inventory(conn, admin[0], None, "Inventario general")
        inventories[None] = general
        # Acceso que ya tenían: empleados activos que no pertenecen a ningún grupo.
        for (uid,) in conn.execute(
                "SELECT u.id FROM users u WHERE u.role = 'employee' AND u.active = 1 AND NOT EXISTS (SELECT 1 FROM"
                " work_group_members m WHERE m.user_id = u.id AND m.status = 'activo')"):
            conn.execute(f"INSERT OR IGNORE INTO inventory_members(inventory_id, user_id, permissions, created_at, updated_at)"
                         f" VALUES (?,?,?,{NOW},{NOW})", (general, uid, json.dumps(SCOPED)))
    mapping = "(SELECT i.id FROM inventories i WHERE i.group_id IS t.group_id ORDER BY i.id LIMIT 1)"
    conn.execute("DROP TRIGGER IF EXISTS products_inventory_fixed")
    for t in tables:
        _rebuild(conn, t, mapping)
    conn.execute("CREATE TRIGGER products_inventory_fixed BEFORE UPDATE OF inventory_id ON products"
                 " WHEN OLD.inventory_id IS NOT NEW.inventory_id"
                 " BEGIN SELECT RAISE(ABORT, 'Un producto no cambia de inventario'); END")
    # Columnas personalizadas: una definición por inventario.
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'inventory_columns'").fetchone()[0]
    extras = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name = 'inventory_columns'"
                                         " AND type IN ('index','trigger') AND sql IS NOT NULL")]
    new_ddl = ddl.replace("id INTEGER PRIMARY KEY,", "id INTEGER PRIMARY KEY,\n  inventory_id INTEGER NOT NULL REFERENCES inventories(id),", 1)
    new_ddl = new_ddl.replace("name TEXT NOT NULL UNIQUE COLLATE NOCASE", "name TEXT NOT NULL COLLATE NOCASE", 1)
    if "inventory_id" not in new_ddl or "UNIQUE COLLATE NOCASE" in new_ddl:
        raise RuntimeError("No se pudo adaptar la tabla inventory_columns.")
    new_ddl = new_ddl.replace("CREATE TABLE inventory_columns", "CREATE TABLE inventory_columns_v13", 1)
    conn.execute(new_ddl)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(inventory_columns)")]
    old_columns = [dict(zip(cols, r, strict=True)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM inventory_columns")]  # noqa: S608
    ordered = sorted(inventories.values())
    first = inventories.get(None, ordered[0] if ordered else None)
    # Primero el inventario que conserva los id originales; las copias de los demás toman id nuevos después.
    ordered = ([first] if first is not None else []) + [i for i in ordered if i != first]
    for inv in ordered:
        for col in old_columns:
            values = dict(col)
            if inv != first:
                values.pop("id")
            values["inventory_id"] = inv
            keys = list(values)
            new_id = conn.execute(f"INSERT INTO inventory_columns_v13({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",  # noqa: S608
                                  [values[k] for k in keys]).lastrowid
            if inv != first:
                conn.execute("UPDATE inventory_custom_values SET column_id = ? WHERE column_id = ?"
                             " AND product_id IN (SELECT id FROM products WHERE inventory_id = ?)", (new_id, col["id"], inv))
    conn.execute("DROP TABLE inventory_columns")
    conn.execute("ALTER TABLE inventory_columns_v13 RENAME TO inventory_columns")
    for sql in extras:
        conn.execute(sql)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_columns_name ON inventory_columns(inventory_id, name)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_inventory_columns_inventory ON inventory_columns(inventory_id, active, position)")
    # Importaciones guardadas: el inventario de cada proceso pasa a ser el id del inventario.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sync_runs'").fetchone():
        for run_id, summary in conn.execute("SELECT id, summary FROM sync_runs WHERE summary LIKE '%group_id%'").fetchall():
            try:
                data = json.loads(summary)
            except (TypeError, ValueError):
                continue
            opts = data.get("options") or {}
            if "group_id" in opts:
                opts["inventory_id"] = inventories.get(opts.pop("group_id"))
                data["options"] = opts
                conn.execute("UPDATE sync_runs SET summary = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), run_id))


SQL = run
