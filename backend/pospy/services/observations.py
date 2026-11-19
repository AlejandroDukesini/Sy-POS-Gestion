"""Observaciones de inventario: novedades por producto con seguimiento, adjuntos y trazabilidad.

Reglas:
- Una observación DOCUMENTA una situación. Este servicio no llama al servicio de inventario ni escribe
  en products, inventory_movements, compras, ventas, costos ni asientos: registrar, editar, resolver o
  eliminar una observación nunca cambia existencias. Los ajustes se hacen con los movimientos del POS.
- Cada observación referencia un producto existente por su id (no copia sus datos).
- El historial (inventory_observation_events) es inmutable: cada creación, comentario, cambio de estado,
  de prioridad, edición, adjunto y eliminación queda como un registro nuevo con fecha y usuario.
- Eliminar es lógico (deleted_at + motivo); la base de datos impide el borrado físico.
- Permisos por acción: observaciones.ver / crear / editar / estado / comentar / eliminar.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, now_utc
from ..core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from ..core.money import parse_decimal, to_milli
from ..core.query import like, paginate
from ..core.settings import Settings
from .scopes import InventoryScopes
from .suppliers import _check_signature, safe_filename

PRIORITIES = ("baja", "media", "alta", "critica")
PRIORITY_LABELS = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
STATUSES = ("pendiente", "en_proceso", "resuelta", "cerrada")
STATUS_LABELS = {"pendiente": "Pendiente", "en_proceso": "En proceso", "resuelta": "Resuelta", "cerrada": "Cerrada"}
OPEN = ("pendiente", "en_proceso")
QUICK = ("todas", "pendientes", "criticas", "en_proceso", "resueltas", "recientes")
RECENT_DAYS = 7
FILE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_FILE_MB = 10
MAX_FILES = 10
EDITABLE = ("category_id", "priority", "description", "qty", "supplier_id", "reference_doc", "detected_on",
            "follow_up_date", "notes", "assigned_to")
FIELD_LABELS = {"category_id": "categoría", "priority": "prioridad", "description": "descripción", "qty_milli": "cantidad afectada",
                "supplier_id": "proveedor", "reference_doc": "documento de referencia", "detected_on": "fecha de la novedad",
                "follow_up_date": "fecha límite de seguimiento", "notes": "comentarios adicionales", "assigned_to": "responsable"}
PRIORITY_RANK = "CASE o.priority WHEN 'critica' THEN 4 WHEN 'alta' THEN 3 WHEN 'media' THEN 2 ELSE 1 END"
STATUS_RANK = "CASE o.status WHEN 'pendiente' THEN 1 WHEN 'en_proceso' THEN 2 WHEN 'resuelta' THEN 3 ELSE 4 END"

BASE_SQL = (
    "SELECT o.id, o.product_id, o.category_id, o.priority, o.status, o.description, o.qty_milli, o.supplier_id,"
    " o.reference_doc, o.detected_on, o.follow_up_date, o.assigned_to, o.created_by, o.created_at, o.updated_at,"
    " o.resolved_at, o.closed_at, o.version,"
    " p.code AS product_code, p.description AS product_description, p.unit AS product_unit, p.active AS product_active,"
    " c.name AS category_name, s.name AS supplier_name,"
    " COALESCE(au.full_name, cu.full_name) AS responsible_name, cu.full_name AS created_by_name"
    " FROM inventory_observations o"
    " JOIN products p ON p.id = o.product_id"
    " JOIN observation_categories c ON c.id = o.category_id"
    " LEFT JOIN suppliers s ON s.id = o.supplier_id"
    " LEFT JOIN users au ON au.id = o.assigned_to"
    " LEFT JOIN users cu ON cu.id = o.created_by"
)


class ObservationService:
    def __init__(self, db, settings: Settings, data_dir: Path, scopes: InventoryScopes | None = None):
        self.db = db
        self.scopes = scopes or InventoryScopes(db)
        self.settings = settings
        self.root = Path(data_dir) / "observaciones"

    def _today(self) -> date:
        return local_today(self.settings.get("empresa")["timezone"])

    # ------------------------------------------------------------------ catálogos para formularios y filtros
    def meta(self, actor: Actor) -> dict:
        actor.require("observaciones.ver")
        with self.db.read() as conn:
            categories = [dict(r) for r in conn.execute(
                "SELECT id, code, name FROM observation_categories WHERE active = 1 ORDER BY sort_order, name")]
            suppliers = [dict(r) for r in conn.execute(
                "SELECT id, name, active FROM suppliers ORDER BY active DESC, name COLLATE NOCASE")]
            users = [dict(r) for r in conn.execute(
                "SELECT id, full_name, active FROM users ORDER BY active DESC, full_name COLLATE NOCASE")]
        return {"categories": categories, "suppliers": suppliers, "users": users,
                "priorities": [{"value": k, "label": v} for k, v in PRIORITY_LABELS.items()],
                "statuses": [{"value": k, "label": v} for k, v in STATUS_LABELS.items()],
                "max_file_mb": MAX_FILE_MB, "max_files": MAX_FILES, "file_types": sorted(FILE_TYPES),
                "recent_days": RECENT_DAYS}

    def product_search(self, actor: Actor, q: str, limit: int = 15, inventory: str | None = None) -> list[dict]:
        """Busca productos existentes por nombre, código (SKU / código de barras) o referencia externa.
        Incluye inactivos (p. ej., descontinuados) para poder documentarlos; se marcan en la respuesta."""
        actor.require("observaciones.ver")
        q = (q or "").strip()[:80]
        if not q:
            return []
        with self.db.read() as conn:
            group_id = self.scopes.resolve(conn, actor, inventory)
            rows = conn.execute(
                "SELECT p.id, p.code, p.description, p.unit, p.active, p.external_ref FROM products p"
                " WHERE p.group_id IS ? AND (p.code = ? COLLATE NOCASE OR p.code LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\'"
                " OR COALESCE(p.external_ref, '') LIKE ? ESCAPE '\\')"
                " ORDER BY (p.code = ? COLLATE NOCASE) DESC, p.active DESC, p.description COLLATE NOCASE LIMIT ?",
                (group_id, q, like(q), like(q), like(q), q, min(30, max(1, int(limit))))).fetchall()
        return [dict(r) for r in rows]

    def product_context(self, actor: Actor, product_id: int) -> dict:
        """Datos de referencia del producto (se leen, nunca se copian a la observación)."""
        actor.require("observaciones.ver")
        with self.db.read() as conn:
            return self._product_context(conn, actor, product_id)

    def _product_context(self, conn: sqlite3.Connection, actor: Actor, product_id: int) -> dict:
        row = conn.execute("SELECT p.id, p.group_id, p.code, p.description, p.unit, p.active, p.external_ref, p.stock_milli,"
                           " p.min_stock_milli, p.cost_cents, c.name AS category_name FROM products p"
                           " LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?", (product_id,)).fetchone()
        if not row:
            raise NotFoundError("Producto no encontrado.", {"product_id": "Seleccione un producto del inventario."})
        self.scopes.check(conn, actor, row["group_id"])
        product = dict(row)
        if not (actor.can("inventario.costos")):
            product.pop("cost_cents")
        # Proveedor asociado: el de la compra a crédito más reciente que dio entrada a este producto.
        supplier = conn.execute(
            "SELECT s.id, s.name FROM payables pa JOIN inventory_movements m ON m.id = pa.source_id"
            " JOIN suppliers s ON s.id = pa.supplier_id WHERE pa.source_type = 'entrada_inventario'"
            " AND m.product_id = ? ORDER BY pa.id DESC LIMIT 1", (product_id,)).fetchone()
        product["last_supplier"] = dict(supplier) if supplier else None
        product.update(self._counts(conn, product_id))
        return product

    @staticmethod
    def _counts(conn: sqlite3.Connection, product_id: int) -> dict:
        r = conn.execute("SELECT COUNT(*) FILTER (WHERE status IN ('pendiente','en_proceso')),"
                         " COUNT(*) FILTER (WHERE status IN ('pendiente','en_proceso') AND priority = 'critica'),"
                         " COUNT(*) FROM inventory_observations WHERE product_id = ? AND deleted_at IS NULL",
                         (product_id,)).fetchone()
        return {"open_observations": r[0], "critical_observations": r[1], "total_observations": r[2]}

    def product_flags(self, actor: Actor, product_ids: list[int]) -> dict[str, dict]:
        """Indicadores discretos para el listado de productos: solo productos con observaciones abiertas."""
        if not actor.can("observaciones.ver"):
            return {}
        ids = [int(i) for i in product_ids[:200]]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT product_id, COUNT(*), COUNT(*) FILTER (WHERE priority = 'critica') FROM inventory_observations"
                f" WHERE deleted_at IS NULL AND status IN ('pendiente','en_proceso') AND product_id IN ({marks})"
                f" GROUP BY product_id", ids).fetchall()
        return {str(r[0]): {"open": r[1], "critical": r[2]} for r in rows}

    # ------------------------------------------------------------------ consulta, filtros e indicadores
    def list(self, actor: Actor, filters: dict, sort: str = "recientes", page: int = 1, page_size: int = 25,
             inventory: str | None = None) -> dict:
        actor.require("observaciones.ver")
        with self.db.read() as conn:
            group_id = self.scopes.resolve(conn, actor, inventory)
        where, params = ["o.deleted_at IS NULL", "p.group_id IS ?"], [group_id]
        q = str(filters.get("q") or "").strip()[:80]
        if q:
            explicit_id = re.fullmatch(r"(?i)(?:obs[-\s]?|#)0*(\d{1,9})", q)   # «OBS-00012» o «#12»: solo el id
            if explicit_id:
                where.append("o.id = ?")
                params.append(int(explicit_id.group(1)))
            else:
                clause = ("(p.code LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\' OR COALESCE(p.external_ref,'') LIKE ?"
                          " ESCAPE '\\' OR o.description LIKE ? ESCAPE '\\' OR o.reference_doc LIKE ? ESCAPE '\\'")
                params += [like(q)] * 5
                if q.isdigit() and len(q) <= 9:      # un número también puede ser el id de la observación
                    clause += " OR o.id = ?"
                    params.append(int(q))
                where.append(clause + ")")
        for key, column in (("product_id", "o.product_id"), ("category_id", "o.category_id"), ("supplier_id", "o.supplier_id")):
            if filters.get(key):
                where.append(f"{column} = ?")
                params.append(_int(filters[key], key))
        if filters.get("responsible_id"):
            where.append("COALESCE(o.assigned_to, o.created_by) = ?")
            params.append(_int(filters["responsible_id"], "responsible_id"))
        if filters.get("priority"):
            where.append("o.priority = ?")
            params.append(_choice(filters["priority"], PRIORITIES, "priority"))
        if filters.get("status"):
            where.append("o.status = ?")
            params.append(_choice(filters["status"], STATUSES, "status"))
        date_from = _date(filters.get("date_from"), "date_from")
        date_to = _date(filters.get("date_to"), "date_to")
        if date_from and date_to and date_to < date_from:
            raise ValidationError("Rango de fechas no válido.", {"date_to": "La fecha final debe ser posterior a la inicial."})
        if date_from:
            where.append("o.detected_on >= ?")
            params.append(date_from)
        if date_to:
            where.append("o.detected_on <= ?")
            params.append(date_to)
        quick = filters.get("quick") or "todas"
        _choice(quick, QUICK, "quick")
        recent_since = iso(now_utc() - timedelta(days=RECENT_DAYS))
        if quick == "pendientes":
            where.append("o.status = 'pendiente'")
        elif quick == "criticas":
            where.append("o.priority = 'critica' AND o.status IN ('pendiente','en_proceso')")
        elif quick == "en_proceso":
            where.append("o.status = 'en_proceso'")
        elif quick == "resueltas":
            where.append("o.status = 'resuelta'")
        elif quick == "recientes":
            where.append("o.created_at >= ?")
            params.append(recent_since)
        sorts = {"recientes": ("o.created_at", "desc"), "antiguas": ("o.created_at", "asc"),
                 "prioridad": (PRIORITY_RANK, "desc"), "producto": ("p.description COLLATE NOCASE", "asc"),
                 "estado": (STATUS_RANK, "asc")}
        column, direction = sorts.get(sort or "recientes", sorts["recientes"])
        sql = BASE_SQL + " WHERE " + " AND ".join(where)
        with self.db.read() as conn:
            result = paginate(conn, sql, params, sort="s", direction=direction, sortable={"s": column}, default_sort="s",
                              page=page, page_size=page_size, tiebreak="o.id")
            result["metrics"] = self._metrics(conn, recent_since, group_id)
        today = self._today().isoformat()
        for item in result["items"]:
            _flags(item, today)
        return result

    def _metrics(self, conn: sqlite3.Connection, recent_since: str, group_id: int | None = None) -> dict:
        r = conn.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'pendiente'), COUNT(*) FILTER (WHERE status = 'en_proceso'),"
            " COUNT(*) FILTER (WHERE status = 'resuelta'), COUNT(*) FILTER (WHERE status = 'cerrada'),"
            " COUNT(*) FILTER (WHERE priority = 'critica' AND status IN ('pendiente','en_proceso')),"
            " COUNT(*) FILTER (WHERE created_at >= ?),"
            " COUNT(*) FILTER (WHERE status IN ('pendiente','en_proceso') AND follow_up_date IS NOT NULL AND follow_up_date < ?)"
            " FROM inventory_observations WHERE deleted_at IS NULL AND product_id IN (SELECT id FROM products WHERE group_id IS ?)",
            (recent_since, self._today().isoformat(), group_id)).fetchone()
        return {"total": r[0], "pendiente": r[1], "en_proceso": r[2], "resuelta": r[3], "cerrada": r[4], "criticas": r[5],
                "recientes": r[6], "seguimiento_vencido": r[7]}

    def get(self, actor: Actor, observation_id: int) -> dict:
        actor.require("observaciones.ver")
        with self.db.read() as conn:
            obs = self._observation(conn, actor, observation_id, full=True)
            obs["product"] = self._product_context(conn, actor, obs["product_id"])
            obs["events"] = [_event(dict(r)) for r in conn.execute(
                "SELECT e.*, u.full_name AS user_name FROM inventory_observation_events e LEFT JOIN users u ON u.id = e.user_id"
                " WHERE e.observation_id = ? ORDER BY e.created_at, e.id", (observation_id,))]
            obs["files"] = [dict(r) for r in conn.execute(
                "SELECT f.id, f.original_name, f.stored_name, f.content_type, f.size_bytes, f.uploaded_at, u.full_name AS uploaded_by_name"
                " FROM inventory_observation_files f LEFT JOIN users u ON u.id = f.uploaded_by"
                " WHERE f.observation_id = ? ORDER BY f.id", (observation_id,))]
        for f in obs["files"]:
            f["available"] = self._file_path(observation_id, f.pop("stored_name")).is_file()
        _flags(obs, self._today().isoformat())
        return obs

    # ------------------------------------------------------------------ crear y editar
    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("observaciones.crear")
        with self.db.tx() as conn:
            product_id = _int(data.get("product_id"), "product_id", "Seleccione el producto relacionado.")
            product = conn.execute("SELECT group_id FROM products WHERE id = ?", (product_id,)).fetchone()
            if not product:
                raise NotFoundError("Producto no encontrado.", {"product_id": "Seleccione un producto del inventario."})
            self.scopes.check(conn, actor, product["group_id"])
            values = self._values(conn, actor, data, None)
            now = iso()
            status = "pendiente"
            obs_id = conn.execute(
                "INSERT INTO inventory_observations(product_id, category_id, priority, status, description, qty_milli,"
                " supplier_id, reference_doc, detected_on, follow_up_date, notes, assigned_to, created_by, updated_by,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (product_id, values["category_id"], values["priority"], status, values["description"], values["qty_milli"],
                 values["supplier_id"], values["reference_doc"], values["detected_on"], values["follow_up_date"],
                 values["notes"], values["assigned_to"] or actor.id, actor.id, actor.id, now, now)).lastrowid
            self._event(conn, actor, obs_id, "creada", None, status, values["description"][:300],
                        {"prioridad": values["priority"], "categoria": values["category_id"]})
            record(conn, actor, "observacion.crear", "inventory_observation", obs_id,
                   {"producto": product_id, "categoria": values["category_id"], "prioridad": values["priority"]})
        return self.get(actor, obs_id)

    def update(self, actor: Actor, observation_id: int, data: dict) -> dict:
        """Edita los datos. El producto no cambia (la observación quedó documentada sobre él) y el estado se
        cambia con change_status. Cada valor anterior queda en el historial."""
        actor.require("observaciones.editar")
        if "product_id" in data:
            raise ValidationError("El producto de una observación no se cambia.",
                                  {"product_id": "Registre una observación nueva para otro producto."})
        with self.db.tx() as conn:
            current = self._observation(conn, actor, observation_id)
            _check_version(data, current)
            values = self._values(conn, actor, data, current)
            changes = {k: (current[k], v) for k, v in values.items() if current[k] != v}
            if not changes:
                return self.get(actor, observation_id)
            sets = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(f"UPDATE inventory_observations SET {sets}, updated_by = ?, updated_at = ?, version = version + 1"
                         f" WHERE id = ?", (*(v for _, v in changes.values()), actor.id, iso(), observation_id))
            if "priority" in changes:
                before, after = changes.pop("priority")
                self._event(conn, actor, observation_id, "prioridad", before, after, str(data.get("comment") or "")[:2000])
            if changes:
                self._event(conn, actor, observation_id, "edicion", None, None, "",
                            {k: {"antes": a, "despues": b} for k, (a, b) in changes.items()})
            record(conn, actor, "observacion.actualizar", "inventory_observation", observation_id,
                   {k: {"antes": a, "despues": b} for k, (a, b) in changes.items()})
        return self.get(actor, observation_id)

    def _values(self, conn: sqlite3.Connection, actor: Actor, data: dict, current: dict | None) -> dict:
        merged = {**(current or {}), **{k: v for k, v in data.items() if k in EDITABLE}}
        category_id = _int(merged.get("category_id"), "category_id", "Seleccione la categoría.")
        if not conn.execute("SELECT 1 FROM observation_categories WHERE id = ? AND (active = 1 OR id = ?)",
                            (category_id, (current or {}).get("category_id"))).fetchone():
            raise ValidationError("Categoría no válida.", {"category_id": "Seleccione una categoría de la lista."})
        if not merged.get("priority"):
            raise ValidationError("Faltan datos obligatorios.", {"priority": "Seleccione la prioridad."})
        if "qty" in data:
            qty = parse_decimal(data["qty"]) if data["qty"] not in (None, "") else None
            if qty is not None and qty < 0:
                raise ValidationError("Revise la cantidad.", {"qty": "La cantidad afectada no puede ser negativa."})
            qty_milli = None if qty is None else to_milli(qty, "Cantidad afectada")
        else:
            qty_milli = (current or {}).get("qty_milli")
        supplier_id = merged.get("supplier_id") or None
        if supplier_id is not None:
            supplier_id = _int(supplier_id, "supplier_id")
            if not conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone():
                raise ValidationError("Proveedor no válido.", {"supplier_id": "Seleccione un proveedor de la lista."})
        assigned_to = merged.get("assigned_to") or None
        if assigned_to is not None:
            assigned_to = _int(assigned_to, "assigned_to")
            row = conn.execute("SELECT active FROM users WHERE id = ?", (assigned_to,)).fetchone()
            if not row or (not row[0] and assigned_to != (current or {}).get("assigned_to")):
                raise ValidationError("Responsable no válido.", {"assigned_to": "Seleccione una persona activa."})
        today = self._today()
        detected_on = _date(merged.get("detected_on"), "detected_on") or today.isoformat()
        if detected_on > (today + timedelta(days=1)).isoformat():
            raise ValidationError("Fecha no válida.", {"detected_on": "La fecha de la novedad no puede ser futura."})
        follow_up = _date(merged.get("follow_up_date"), "follow_up_date")
        if follow_up and follow_up < detected_on:
            raise ValidationError("Fecha no válida.", {"follow_up_date": "La fecha límite debe ser posterior a la novedad."})
        return {"category_id": category_id,
                "priority": _choice(merged.get("priority"), PRIORITIES, "priority"),
                "description": _text(merged, "description", "La descripción", required=True, max_len=2000, min_len=5),
                "qty_milli": qty_milli,
                "supplier_id": supplier_id,
                "reference_doc": _text(merged, "reference_doc", "El documento de referencia", max_len=80),
                "detected_on": detected_on,
                "follow_up_date": follow_up,
                "notes": _text(merged, "notes", "Los comentarios adicionales", max_len=2000),
                "assigned_to": assigned_to}

    # ------------------------------------------------------------------ seguimiento
    def change_status(self, actor: Actor, observation_id: int, status: str, comment: str = "", version: int | None = None) -> dict:
        actor.require("observaciones.estado")
        status = _choice(status, STATUSES, "status")
        comment = _clean(comment, 2000, "comment", "El comentario")
        with self.db.tx() as conn:
            current = self._observation(conn, actor, observation_id)
            _check_version({"version": version}, current)
            if current["status"] == status:
                raise ValidationError("La observación ya tiene ese estado.", {"status": "Elija un estado diferente."})
            reopening = current["status"] in ("resuelta", "cerrada") and status in OPEN
            if (reopening or status == "cerrada") and not comment:
                raise ValidationError("Escriba el motivo del cambio.",
                                      {"comment": "Para cerrar o reabrir una observación explique el motivo."})
            now = iso()
            resolved_at = current["resolved_at"]
            closed_at = current["closed_at"]
            if status == "resuelta":
                resolved_at, closed_at = now, None
            elif status == "cerrada":
                closed_at = now
            else:
                resolved_at, closed_at = None, None
            conn.execute("UPDATE inventory_observations SET status = ?, resolved_at = ?, closed_at = ?, updated_by = ?,"
                         " updated_at = ?, version = version + 1 WHERE id = ?",
                         (status, resolved_at, closed_at, actor.id, now, observation_id))
            self._event(conn, actor, observation_id, "estado", current["status"], status, comment)
            record(conn, actor, "observacion.estado", "inventory_observation", observation_id,
                   {"antes": current["status"], "despues": status, "comentario": comment})
        return self.get(actor, observation_id)

    def add_comment(self, actor: Actor, observation_id: int, comment: str) -> dict:
        actor.require("observaciones.comentar")
        text = _clean(comment, 2000, "comment", "El comentario")
        if not text:
            raise ValidationError("Faltan datos.", {"comment": "Escriba el comentario."})
        with self.db.tx() as conn:
            self._observation(conn, actor, observation_id)
            event_id = self._event(conn, actor, observation_id, "comentario", None, None, text)
            conn.execute("UPDATE inventory_observations SET updated_at = ?, updated_by = ? WHERE id = ?",
                         (iso(), actor.id, observation_id))
            return _event(dict(conn.execute("SELECT e.*, u.full_name AS user_name FROM inventory_observation_events e"
                                             " LEFT JOIN users u ON u.id = e.user_id WHERE e.id = ?", (event_id,)).fetchone()))

    def delete(self, actor: Actor, observation_id: int, reason: str) -> None:
        """Eliminación lógica: deja de verse en listados e indicadores, pero el registro y su historial se conservan."""
        actor.require("observaciones.eliminar")
        reason = _clean(reason, 300, "reason", "El motivo")
        if not reason:
            raise ValidationError("Escriba el motivo.", {"reason": "El motivo de la eliminación es obligatorio."})
        with self.db.tx() as conn:
            current = self._observation(conn, actor, observation_id)
            now = iso()
            conn.execute("UPDATE inventory_observations SET deleted_at = ?, deleted_by = ?, delete_reason = ?, updated_at = ?,"
                         " updated_by = ?, version = version + 1 WHERE id = ?",
                         (now, actor.id, reason, now, actor.id, observation_id))
            self._event(conn, actor, observation_id, "eliminada", current["status"], None, reason)
            record(conn, actor, "observacion.eliminar", "inventory_observation", observation_id,
                   {"producto": current["product_id"], "estado": current["status"], "prioridad": current["priority"],
                    "descripcion": current["description"], "motivo": reason})

    # ------------------------------------------------------------------ adjuntos
    def upload_file(self, actor: Actor, observation_id: int, filename: str, content: bytes) -> dict:
        if not (actor.can("observaciones.crear") or actor.can("observaciones.editar")):
            raise PermissionDenied("No tiene permiso para adjuntar archivos.", {"permiso": "observaciones.crear"})
        original = safe_filename(filename)
        suffix = Path(original).suffix.lower()
        if suffix not in FILE_TYPES:
            raise ValidationError("Tipo de archivo no permitido.",
                                  {"file": "Formatos permitidos: " + ", ".join(sorted(FILE_TYPES)) + "."})
        if not content:
            raise ValidationError("El archivo está vacío.", {"file": "Elija un archivo con contenido."})
        if len(content) > MAX_FILE_MB * 1024 * 1024:
            raise ValidationError("Archivo demasiado grande.", {"file": f"Máximo {MAX_FILE_MB} MB."})
        _check_signature(suffix, content)
        with self.db.read() as conn:
            self._observation(conn, actor, observation_id)
            count = conn.execute("SELECT COUNT(*) FROM inventory_observation_files WHERE observation_id = ?",
                                 (observation_id,)).fetchone()[0]
        if count >= MAX_FILES:
            raise ValidationError("Demasiados adjuntos.", {"file": f"Máximo {MAX_FILES} archivos por observación."})
        folder = self.root / str(int(observation_id))
        folder.mkdir(parents=True, exist_ok=True)
        stored_name = f"{now_utc():%Y%m%d%H%M%S}-{secrets.token_hex(8)}{suffix}"
        target = folder / stored_name
        tmp = folder / f".subida-{secrets.token_hex(8)}"
        tmp.write_bytes(content)
        tmp.replace(target)
        digest = hashlib.sha256(content).hexdigest()
        try:
            with self.db.tx() as conn:
                self._observation(conn, actor, observation_id)
                file_id = conn.execute(
                    "INSERT INTO inventory_observation_files(observation_id, original_name, stored_name, content_type,"
                    " size_bytes, sha256, uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                    (observation_id, original, stored_name, FILE_TYPES[suffix], len(content), digest, actor.id, iso())).lastrowid
                self._event(conn, actor, observation_id, "adjunto", None, original, "", {"bytes": len(content), "sha256": digest})
                record(conn, actor, "observacion.adjunto", "inventory_observation", observation_id,
                       {"archivo": original, "bytes": len(content), "sha256": digest})
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return {"id": file_id, "original_name": original, "content_type": FILE_TYPES[suffix], "size_bytes": len(content)}

    def file_for_download(self, actor: Actor, observation_id: int, file_id: int) -> tuple[Path, str, str]:
        actor.require("observaciones.ver")
        with self.db.read() as conn:
            self._observation(conn, actor, observation_id)
            row = conn.execute("SELECT * FROM inventory_observation_files WHERE id = ? AND observation_id = ?",
                               (file_id, observation_id)).fetchone()
        if not row:
            raise NotFoundError("Archivo no encontrado.")
        path = self._file_path(observation_id, row["stored_name"])
        if not path.is_file():
            raise NotFoundError("El archivo ya no está en el disco. Restaure la carpeta de observaciones o súbalo de nuevo.")
        return path, row["original_name"], row["content_type"]

    def delete_file(self, actor: Actor, observation_id: int, file_id: int) -> None:
        actor.require("observaciones.editar")
        with self.db.tx() as conn:
            self._observation(conn, actor, observation_id)
            row = conn.execute("SELECT * FROM inventory_observation_files WHERE id = ? AND observation_id = ?",
                               (file_id, observation_id)).fetchone()
            if not row:
                raise NotFoundError("Archivo no encontrado.")
            conn.execute("DELETE FROM inventory_observation_files WHERE id = ?", (file_id,))
            self._event(conn, actor, observation_id, "adjunto_eliminado", row["original_name"], None, "",
                        {"sha256": row["sha256"]})
            record(conn, actor, "observacion.adjunto_eliminar", "inventory_observation", observation_id,
                   {"archivo": row["original_name"], "sha256": row["sha256"]})
        try:
            self._file_path(observation_id, row["stored_name"]).unlink(missing_ok=True)
        except OSError:
            pass   # si Windows lo tiene abierto queda huérfano; no afecta a los datos

    def _file_path(self, observation_id: int, stored_name: str) -> Path:
        folder = (self.root / str(int(observation_id))).resolve()
        path = (folder / stored_name).resolve()
        if path.parent != folder:
            raise NotFoundError("Archivo no encontrado.")
        return path

    # ------------------------------------------------------------------ utilidades
    def _observation(self, conn: sqlite3.Connection, actor: Actor, observation_id: int, full: bool = False) -> dict:
        """La observación, si su producto es de un inventario al que esta persona entra; si no, «no encontrada»."""
        group = conn.execute("SELECT p.group_id FROM inventory_observations o JOIN products p ON p.id = o.product_id"
                             " WHERE o.id = ?", (observation_id,)).fetchone()
        if group is not None:
            self.scopes.check(conn, actor, group[0], "Observación")
        if full:
            row = conn.execute(BASE_SQL.replace("SELECT o.id,", "SELECT o.notes, o.updated_by, o.id,") +
                               " WHERE o.id = ? AND o.deleted_at IS NULL", (observation_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM inventory_observations WHERE id = ? AND deleted_at IS NULL",
                               (observation_id,)).fetchone()
        if not row:
            raise NotFoundError("Observación no encontrada.")
        return dict(row)

    @staticmethod
    def _event(conn: sqlite3.Connection, actor: Actor, observation_id: int, kind: str, from_value, to_value,
               comment: str = "", details: dict | None = None) -> int:
        return conn.execute(
            "INSERT INTO inventory_observation_events(observation_id, kind, from_value, to_value, comment, details, user_id,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (observation_id, kind, None if from_value is None else str(from_value), None if to_value is None else str(to_value),
             comment or "", json.dumps(details, ensure_ascii=False, default=str) if details else None, actor.id, iso())).lastrowid


def _flags(item: dict, today: str) -> dict:
    item["code"] = f"OBS-{item['id']:05d}"
    item["is_open"] = item["status"] in OPEN
    item["follow_up_overdue"] = bool(item["is_open"] and item.get("follow_up_date") and item["follow_up_date"] < today)
    return item


def _event(row: dict) -> dict:
    row["details"] = json.loads(row["details"]) if row.get("details") else None
    return row


def _text(data: dict, key: str, label: str, required: bool = False, max_len: int = 200, min_len: int = 0) -> str:
    value = _clean(data.get(key), max_len, key, label)
    if required and not value:
        raise ValidationError("Faltan datos obligatorios.", {key: f"{label} es obligatoria."})
    if value and len(value) < min_len:
        raise ValidationError("Texto demasiado corto.", {key: f"{label}: escriba al menos {min_len} caracteres."})
    return value


def _clean(value, max_len: int, key: str, label: str) -> str:
    """Quita caracteres de control (conserva saltos de línea y tabulaciones) y valida la longitud."""
    text = "" if value is None else str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()
    if len(text) > max_len:
        raise ValidationError("Texto demasiado largo.", {key: f"{label}: máximo {max_len} caracteres."})
    return text


def _int(value, key: str, message: str = "Valor no válido.") -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Faltan datos obligatorios." if value in (None, "") else "Valor no válido.", {key: message}) from None
    if number <= 0:
        raise ValidationError("Valor no válido.", {key: message})
    return number


def _date(value, key: str) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ValidationError("Fecha no válida.", {key: "Use el formato AAAA-MM-DD."}) from None


def _choice(value, options: tuple, key: str) -> str:
    if value not in options:
        raise ValidationError("Opción no válida.", {key: "Opción no válida."})
    return value


def _check_version(data: dict, current: dict) -> None:
    if data.get("version") is not None and int(data["version"]) != current["version"]:
        raise ConflictError("Otra persona modificó esta observación. Recargue y vuelva a intentarlo.")
