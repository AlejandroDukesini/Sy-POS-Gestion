"""Expediente comercial de cada proveedor: resumen, asesor, notas, visitas, cotizaciones y archivos.

Reglas:
- Todo exige el permiso «terceros.gestionar» (el mismo que ya protegía la edición de proveedores).
- Cada registro pertenece a un único proveedor; todas las consultas filtran por supplier_id, de modo
  que un id de otro proveedor responde «no encontrado» y nunca se lee, edita ni borra información ajena.
- Notas, visitas y cotizaciones son INFORMATIVAS: no crean compras, cuentas por pagar, asientos ni
  movimientos de inventario. Este servicio no llama a ningún otro servicio de negocio.
- Archivos: se guardan en <datos>/proveedores/<id>/ con un nombre interno aleatorio generado por el
  servidor (el nombre original solo se muestra y se usa en la descarga, ya normalizado). Nunca se
  importan al inventario.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import unicodedata
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, now_utc
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import to_cents
from ..core.query import like
from ..core.settings import Settings

NOTE_CATEGORIES = ("deuda", "pago", "entrega", "acuerdo", "reclamacion", "seguimiento", "general")
QUOTE_STATUSES = ("pendiente", "aceptada", "rechazada", "vencida")
PRODUCT_TYPES = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 ".xls": "application/vnd.ms-excel"}
QUOTE_TYPES = {**PRODUCT_TYPES, ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # formato binario de Excel 97-2003 (.xls)


class SupplierService:
    def __init__(self, db, settings: Settings, data_dir: Path):
        self.db = db
        self.settings = settings
        self.root = Path(data_dir) / "proveedores"

    # ------------------------------------------------------------------ vista general
    def overview(self, actor: Actor, q: str = "", status: str = "activos") -> dict:
        actor.require("terceros.gestionar")
        recent_days = self.settings.get("proveedores")["recent_visit_days"]
        since = (date.today() - timedelta(days=recent_days)).isoformat()
        sql = ("SELECT s.id, s.name, s.identification, s.phone, s.whatsapp, s.email, s.city, s.active, s.advisor_name,"
               " s.created_at,"
               " (SELECT COUNT(*) FROM supplier_notes n WHERE n.supplier_id = s.id AND n.status = 'pendiente') AS pending_notes,"
               " (SELECT COUNT(*) FROM supplier_notes n WHERE n.supplier_id = s.id AND n.status = 'pendiente'"
               "   AND n.important = 1) AS important_notes,"
               " (SELECT MAX(visit_date) FROM supplier_visits v WHERE v.supplier_id = s.id) AS last_visit,"
               " (SELECT COUNT(*) FROM supplier_quotes c WHERE c.supplier_id = s.id) AS quotes,"
               " (SELECT COUNT(*) FROM supplier_files f WHERE f.supplier_id = s.id AND f.kind = 'productos') AS product_files"
               " FROM suppliers s")
        where, params = [], []
        if status == "activos":
            where.append("s.active = 1")
        elif status == "inactivos":
            where.append("s.active = 0")
        elif status != "todos":
            raise ValidationError("Filtro de estado no válido.")
        if q.strip():
            where.append("(s.name LIKE ? ESCAPE '\\' OR s.identification LIKE ? ESCAPE '\\')")
            params += [like(q.strip())] * 2
        sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.name COLLATE NOCASE LIMIT 500"
        with self.db.read() as conn:
            items = [dict(r) for r in conn.execute(sql, params)]
            totals = conn.execute(
                "SELECT COUNT(*), SUM(active = 1),"
                " (SELECT COUNT(DISTINCT supplier_id) FROM supplier_notes WHERE status = 'pendiente'),"
                " (SELECT COUNT(DISTINCT supplier_id) FROM supplier_visits WHERE visit_date >= ?),"
                " (SELECT COUNT(DISTINCT supplier_id) FROM supplier_quotes) FROM suppliers", (since,)).fetchone()
        for item in items:
            item["recent_visit"] = bool(item["last_visit"] and item["last_visit"] >= since)
        return {"items": items, "recent_visit_days": recent_days,
                "metrics": {"total": totals[0], "active": totals[1] or 0, "with_pending": totals[2],
                            "recent_visits": totals[3], "with_quotes": totals[4]}}

    # ------------------------------------------------------------------ resumen (dashboard)
    def dashboard(self, actor: Actor, supplier_id: int) -> dict:
        actor.require("terceros.gestionar")
        with self.db.read() as conn:
            supplier = self._supplier(conn, supplier_id)
            notes = conn.execute("SELECT COUNT(*) FILTER (WHERE status = 'pendiente'),"
                                 " COUNT(*) FILTER (WHERE status = 'pendiente' AND important = 1),"
                                 " COUNT(*) FILTER (WHERE status = 'pendiente' AND due_date IS NOT NULL AND due_date < ?),"
                                 " COUNT(*) FROM supplier_notes WHERE supplier_id = ?",
                                 (date.today().isoformat(), supplier_id)).fetchone()
            last_visit = _one(conn.execute("SELECT * FROM supplier_visits WHERE supplier_id = ?"
                                           " ORDER BY visit_date DESC, id DESC LIMIT 1", (supplier_id,)))
            next_visit = conn.execute("SELECT MIN(next_visit_date) FROM supplier_visits WHERE supplier_id = ?"
                                      " AND next_visit_date >= ?", (supplier_id, date.today().isoformat())).fetchone()[0]
            latest_quote = _one(conn.execute(self._quote_sql() + " WHERE q.supplier_id = ?"
                                             " ORDER BY q.issue_date DESC, q.id DESC LIMIT 1", (supplier_id,)))
            counts = conn.execute("SELECT (SELECT COUNT(*) FROM supplier_visits WHERE supplier_id = ?),"
                                  " (SELECT COUNT(*) FROM supplier_quotes WHERE supplier_id = ?)",
                                  (supplier_id, supplier_id)).fetchone()
            product_file = _one(conn.execute(f"SELECT {FILE_COLUMNS} FROM supplier_files WHERE supplier_id = ?"
                                             " AND kind = 'productos' ORDER BY uploaded_at DESC, id DESC LIMIT 1",
                                             (supplier_id,)))
        if latest_quote:
            _quote_flags(latest_quote)
        if product_file:
            product_file["available"] = self._path(supplier_id, product_file.pop("stored_name")).is_file()
        return {"supplier": supplier, "pending_notes": notes[0], "important_notes": notes[1], "overdue_notes": notes[2],
                "total_notes": notes[3], "last_visit": last_visit, "next_visit": next_visit, "visits": counts[0],
                "latest_quote": latest_quote, "quotes": counts[1], "product_file": product_file}

    def update_advisor(self, actor: Actor, supplier_id: int, data: dict) -> dict:
        actor.require("terceros.gestionar")
        values = {"advisor_name": _text(data, "advisor_name", "El nombre del asesor", max_len=120),
                  "advisor_phone": _text(data, "advisor_phone", "El teléfono del asesor", max_len=60),
                  "advisor_email": _text(data, "advisor_email", "El correo del asesor", max_len=120),
                  "advisor_notes": _text(data, "advisor_notes", "Las observaciones", max_len=1000)}
        if values["advisor_email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["advisor_email"]):
            raise ValidationError("Correo no válido.", {"advisor_email": "Escriba un correo como nombre@dominio.com."})
        with self.db.tx() as conn:
            current = self._supplier(conn, supplier_id)
            conn.execute("UPDATE suppliers SET advisor_name = ?, advisor_phone = ?, advisor_email = ?, advisor_notes = ?,"
                         " updated_at = ?, version = version + 1 WHERE id = ?", (*values.values(), iso(), supplier_id))
            changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
            if changes:
                record(conn, actor, "proveedor.asesor", "suppliers", supplier_id, changes)
            return self._supplier(conn, supplier_id)

    # ------------------------------------------------------------------ notas y pendientes
    def notes(self, actor: Actor, supplier_id: int, status: str = "", category: str = "") -> list[dict]:
        actor.require("terceros.gestionar")
        where, params = ["supplier_id = ?"], [supplier_id]
        if status:
            _choice(status, ("pendiente", "resuelta"), "status")
            where.append("status = ?")
            params.append(status)
        if category:
            _choice(category, NOTE_CATEGORIES, "category")
            where.append("category = ?")
            params.append(category)
        with self.db.read() as conn:
            self._supplier(conn, supplier_id)
            return [dict(r) for r in conn.execute(
                "SELECT * FROM supplier_notes WHERE " + " AND ".join(where) +
                " ORDER BY status = 'resuelta', important DESC, due_date IS NULL, due_date, id DESC", params)]

    def save_note(self, actor: Actor, supplier_id: int, data: dict, note_id: int | None = None) -> dict:
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            self._supplier(conn, supplier_id)
            current = self._child(conn, "supplier_notes", supplier_id, note_id, "Nota") if note_id else None
            merged = {**(current or {}), **data}
            values = {"category": _choice(merged.get("category") or "general", NOTE_CATEGORIES, "category"),
                      "title": _text(merged, "title", "El título", required=True, max_len=200),
                      "body": _text(merged, "body", "El detalle", max_len=4000),
                      "status": _choice(merged.get("status") or "pendiente", ("pendiente", "resuelta"), "status"),
                      "important": int(bool(merged.get("important"))),
                      "due_date": _date(merged.get("due_date"), "due_date")}
            now = iso()
            if current is None:
                cur = conn.execute("INSERT INTO supplier_notes(supplier_id, category, title, body, status, important, due_date,"
                                   " created_by, updated_by, created_at, updated_at, resolved_at)"
                                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (supplier_id, *values.values(), actor.id, actor.id, now, now,
                                    now if values["status"] == "resuelta" else None))
                note_id = cur.lastrowid
                record(conn, actor, "proveedor.nota_crear", "supplier_note", note_id,
                       {"proveedor": supplier_id, "categoria": values["category"], "titulo": values["title"]})
            else:
                _check_version(data, current)
                resolved_at = (current["resolved_at"] or now) if values["status"] == "resuelta" else None
                conn.execute("UPDATE supplier_notes SET category = ?, title = ?, body = ?, status = ?, important = ?,"
                             " due_date = ?, updated_by = ?, updated_at = ?, resolved_at = ?, version = version + 1"
                             " WHERE id = ? AND supplier_id = ?",
                             (*values.values(), actor.id, now, resolved_at, note_id, supplier_id))
                changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
                if changes:   # historial: la auditoría conserva cada valor anterior
                    record(conn, actor, "proveedor.nota_actualizar", "supplier_note", note_id,
                           {"proveedor": supplier_id, **changes})
            return dict(conn.execute("SELECT * FROM supplier_notes WHERE id = ?", (note_id,)).fetchone())

    def delete_note(self, actor: Actor, supplier_id: int, note_id: int) -> None:
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            note = self._child(conn, "supplier_notes", supplier_id, note_id, "Nota")
            conn.execute("DELETE FROM supplier_notes WHERE id = ? AND supplier_id = ?", (note_id, supplier_id))
            record(conn, actor, "proveedor.nota_eliminar", "supplier_note", note_id,
                   {"proveedor": supplier_id, "categoria": note["category"], "titulo": note["title"], "detalle": note["body"],
                    "estado": note["status"], "vence": note["due_date"], "creada": note["created_at"]})

    # ------------------------------------------------------------------ visitas
    def visits(self, actor: Actor, supplier_id: int) -> list[dict]:
        actor.require("terceros.gestionar")
        with self.db.read() as conn:
            self._supplier(conn, supplier_id)
            return [dict(r) for r in conn.execute("SELECT * FROM supplier_visits WHERE supplier_id = ?"
                                                  " ORDER BY visit_date DESC, id DESC", (supplier_id,))]

    def save_visit(self, actor: Actor, supplier_id: int, data: dict, visit_id: int | None = None) -> dict:
        """Cada visita es un registro propio: crear nunca sobrescribe las anteriores."""
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            supplier = self._supplier(conn, supplier_id)
            current = self._child(conn, "supplier_visits", supplier_id, visit_id, "Visita") if visit_id else None
            merged = {**(current or {}), **data}
            visit_date = _date(merged.get("visit_date"), "visit_date", required=True)
            if visit_date > (date.today() + timedelta(days=1)).isoformat():
                raise ValidationError("Fecha no válida.", {"visit_date": "Una visita realizada no puede tener fecha futura."})
            next_date = _date(merged.get("next_visit_date"), "next_visit_date")
            if next_date and next_date < visit_date:
                raise ValidationError("Fecha no válida.", {"next_visit_date": "La próxima visita debe ser posterior a esta."})
            values = {"visit_date": visit_date,
                      "advisor_name": _text(merged, "advisor_name", "El asesor", max_len=120) or supplier["advisor_name"],
                      "reason": _text(merged, "reason", "El motivo", required=True, max_len=200),
                      "summary": _text(merged, "summary", "La descripción", max_len=4000),
                      "agreements": _text(merged, "agreements", "Los acuerdos", max_len=4000),
                      "next_visit_date": next_date}
            now = iso()
            if current is None:
                visit_id = conn.execute("INSERT INTO supplier_visits(supplier_id, visit_date, advisor_name, reason, summary,"
                                        " agreements, next_visit_date, created_by, created_at, updated_at)"
                                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                                        (supplier_id, *values.values(), actor.id, now, now)).lastrowid
                record(conn, actor, "proveedor.visita_crear", "supplier_visit", visit_id,
                       {"proveedor": supplier_id, "fecha": visit_date, "motivo": values["reason"]})
            else:
                _check_version(data, current)
                conn.execute("UPDATE supplier_visits SET visit_date = ?, advisor_name = ?, reason = ?, summary = ?,"
                             " agreements = ?, next_visit_date = ?, updated_at = ?, version = version + 1"
                             " WHERE id = ? AND supplier_id = ?", (*values.values(), now, visit_id, supplier_id))
                changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
                if changes:
                    record(conn, actor, "proveedor.visita_actualizar", "supplier_visit", visit_id,
                           {"proveedor": supplier_id, **changes})
            return dict(conn.execute("SELECT * FROM supplier_visits WHERE id = ?", (visit_id,)).fetchone())

    def delete_visit(self, actor: Actor, supplier_id: int, visit_id: int) -> None:
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            visit = self._child(conn, "supplier_visits", supplier_id, visit_id, "Visita")
            conn.execute("DELETE FROM supplier_visits WHERE id = ? AND supplier_id = ?", (visit_id, supplier_id))
            record(conn, actor, "proveedor.visita_eliminar", "supplier_visit", visit_id,
                   {"proveedor": supplier_id, "fecha": visit["visit_date"], "motivo": visit["reason"],
                    "resumen": visit["summary"], "acuerdos": visit["agreements"]})

    # ------------------------------------------------------------------ cotizaciones
    @staticmethod
    def _quote_sql() -> str:
        return ("SELECT q.*, f.id AS file_id, f.original_name AS file_name, f.size_bytes AS file_size"
                " FROM supplier_quotes q LEFT JOIN supplier_files f ON f.quote_id = q.id")

    def quotes(self, actor: Actor, supplier_id: int, status: str = "") -> list[dict]:
        actor.require("terceros.gestionar")
        where, params = ["q.supplier_id = ?"], [supplier_id]
        if status:
            where.append("q.status = ?")
            params.append(_choice(status, QUOTE_STATUSES, "status"))
        with self.db.read() as conn:
            self._supplier(conn, supplier_id)
            items = [dict(r) for r in conn.execute(self._quote_sql() + " WHERE " + " AND ".join(where) +
                                                   " ORDER BY q.issue_date DESC, q.id DESC", params)]
        return [_quote_flags(q) for q in items]

    def save_quote(self, actor: Actor, supplier_id: int, data: dict, quote_id: int | None = None) -> dict:
        """Registro informativo: no crea compras, cuentas por pagar ni movimientos de inventario."""
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            supplier = self._supplier(conn, supplier_id)
            current = self._child(conn, "supplier_quotes", supplier_id, quote_id, "Cotización") if quote_id else None
            merged = {**(current or {}), **data}
            issue = _date(merged.get("issue_date"), "issue_date", required=True)
            due = _date(merged.get("due_date"), "due_date")
            if due and due < issue:
                raise ValidationError("Fecha no válida.", {"due_date": "El vencimiento debe ser posterior a la emisión."})
            if "total" in data:
                total = None if data["total"] in (None, "") else to_cents(data["total"], "Valor total")
            else:
                total = current["total_cents"] if current else None
            if total is not None and total < 0:
                raise ValidationError("Valor no válido.", {"total": "El valor no puede ser negativo."})
            values = {"number": _text(merged, "number", "El número de cotización", required=True, max_len=60),
                      "issue_date": issue, "due_date": due,
                      "advisor_name": _text(merged, "advisor_name", "El asesor", max_len=120) or supplier["advisor_name"],
                      "description": _text(merged, "description", "La descripción", max_len=4000),
                      "total_cents": total,
                      "status": _choice(merged.get("status") or "pendiente", QUOTE_STATUSES, "status"),
                      "notes": _text(merged, "notes", "Las observaciones", max_len=4000)}
            dup = conn.execute("SELECT id FROM supplier_quotes WHERE supplier_id = ? AND number = ? COLLATE NOCASE"
                               " AND id IS NOT ?", (supplier_id, values["number"], quote_id)).fetchone()
            if dup:
                raise ConflictError("Ya existe una cotización con ese número para este proveedor.",
                                    {"number": "Número repetido."})
            now = iso()
            if current is None:
                quote_id = conn.execute("INSERT INTO supplier_quotes(supplier_id, number, issue_date, due_date, advisor_name,"
                                        " description, total_cents, status, notes, created_by, created_at, updated_at)"
                                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                        (supplier_id, *values.values(), actor.id, now, now)).lastrowid
                record(conn, actor, "proveedor.cotizacion_crear", "supplier_quote", quote_id,
                       {"proveedor": supplier_id, "numero": values["number"], "valor_centavos": total})
            else:
                _check_version(data, current)
                conn.execute("UPDATE supplier_quotes SET number = ?, issue_date = ?, due_date = ?, advisor_name = ?,"
                             " description = ?, total_cents = ?, status = ?, notes = ?, updated_at = ?, version = version + 1"
                             " WHERE id = ? AND supplier_id = ?", (*values.values(), now, quote_id, supplier_id))
                changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
                if changes:
                    record(conn, actor, "proveedor.cotizacion_actualizar", "supplier_quote", quote_id,
                           {"proveedor": supplier_id, **changes})
            return _quote_flags(dict(conn.execute(self._quote_sql() + " WHERE q.id = ?", (quote_id,)).fetchone()))

    def delete_quote(self, actor: Actor, supplier_id: int, quote_id: int) -> None:
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            quote = self._child(conn, "supplier_quotes", supplier_id, quote_id, "Cotización")
            attached = conn.execute("SELECT * FROM supplier_files WHERE quote_id = ? AND supplier_id = ?",
                                    (quote_id, supplier_id)).fetchone()
            if attached:
                conn.execute("DELETE FROM supplier_files WHERE id = ?", (attached["id"],))
            conn.execute("DELETE FROM supplier_quotes WHERE id = ? AND supplier_id = ?", (quote_id, supplier_id))
            record(conn, actor, "proveedor.cotizacion_eliminar", "supplier_quote", quote_id,
                   {"proveedor": supplier_id, "numero": quote["number"], "emision": quote["issue_date"],
                    "valor_centavos": quote["total_cents"], "estado": quote["status"],
                    "adjunto": attached["original_name"] if attached else None})
        if attached:   # el archivo se borra solo después de confirmar la transacción
            self._unlink(supplier_id, attached["stored_name"])

    # ------------------------------------------------------------------ archivos
    def product_files(self, actor: Actor, supplier_id: int) -> list[dict]:
        """Versiones de la lista de productos, la más reciente primero (es la vigente)."""
        actor.require("terceros.gestionar")
        with self.db.read() as conn:
            self._supplier(conn, supplier_id)
            items = [dict(r) for r in conn.execute(f"SELECT {FILE_COLUMNS} FROM supplier_files WHERE supplier_id = ?"
                                                   " AND kind = 'productos' ORDER BY uploaded_at DESC, id DESC",
                                                   (supplier_id,))]
        for i, item in enumerate(items):
            item["current"] = i == 0
            item["version"] = len(items) - i
            item["available"] = self._path(supplier_id, item.pop("stored_name")).is_file()
        return items

    def upload_product_file(self, actor: Actor, supplier_id: int, filename: str, content: bytes) -> dict:
        """Sube una versión nueva; las anteriores se conservan (no se sobrescribe ningún archivo)."""
        actor.require("terceros.gestionar")
        return self._store(actor, supplier_id, "productos", None, filename, content, PRODUCT_TYPES)

    def upload_quote_file(self, actor: Actor, supplier_id: int, quote_id: int, filename: str, content: bytes) -> dict:
        actor.require("terceros.gestionar")
        with self.db.read() as conn:
            self._child(conn, "supplier_quotes", supplier_id, quote_id, "Cotización")
            previous = conn.execute("SELECT id FROM supplier_files WHERE quote_id = ?", (quote_id,)).fetchone()
        stored = self._store(actor, supplier_id, "cotizacion", quote_id, filename, content, QUOTE_TYPES,
                             replace_id=previous["id"] if previous else None)
        return stored

    def file_for_download(self, actor: Actor, supplier_id: int, file_id: int) -> tuple[Path, str, str]:
        actor.require("terceros.gestionar")
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM supplier_files WHERE id = ? AND supplier_id = ?",
                               (file_id, supplier_id)).fetchone()
        if not row:
            raise NotFoundError("Archivo no encontrado.")
        path = self._path(supplier_id, row["stored_name"])
        if not path.is_file():
            raise NotFoundError("El archivo ya no está en el disco. Súbalo de nuevo o restaure la carpeta de proveedores.")
        return path, row["original_name"], row["content_type"]

    def delete_file(self, actor: Actor, supplier_id: int, file_id: int) -> None:
        actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM supplier_files WHERE id = ? AND supplier_id = ?",
                               (file_id, supplier_id)).fetchone()
            if not row:
                raise NotFoundError("Archivo no encontrado.")
            conn.execute("DELETE FROM supplier_files WHERE id = ?", (file_id,))
            record(conn, actor, "proveedor.archivo_eliminar", "supplier_file", file_id,
                   {"proveedor": supplier_id, "tipo": row["kind"], "archivo": row["original_name"], "sha256": row["sha256"]})
        self._unlink(supplier_id, row["stored_name"])

    def _store(self, actor: Actor, supplier_id: int, kind: str, quote_id: int | None, filename: str, content: bytes,
               allowed: dict[str, str], replace_id: int | None = None) -> dict:
        original = safe_filename(filename)
        suffix = Path(original).suffix.lower()
        if suffix not in allowed:
            raise ValidationError("Tipo de archivo no permitido.",
                                  {"file": "Formatos permitidos: " + ", ".join(sorted(allowed)) + "."})
        max_mb = self.settings.get("proveedores")["max_file_mb"]
        if not content:
            raise ValidationError("El archivo está vacío.", {"file": "Elija un archivo con contenido."})
        if len(content) > max_mb * 1024 * 1024:
            raise ValidationError("Archivo demasiado grande.", {"file": f"Máximo {max_mb} MB."})
        _check_signature(suffix, content)
        with self.db.read() as conn:
            self._supplier(conn, supplier_id)
        folder = self.root / str(int(supplier_id))
        folder.mkdir(parents=True, exist_ok=True)
        stored_name = f"{now_utc():%Y%m%d%H%M%S}-{secrets.token_hex(8)}{suffix}"
        target = folder / stored_name
        tmp = folder / f".subida-{secrets.token_hex(8)}"
        tmp.write_bytes(content)
        tmp.replace(target)          # escritura atómica; el nombre es nuevo, nunca pisa otro archivo
        digest = hashlib.sha256(content).hexdigest()
        old = None
        try:
            with self.db.tx() as conn:
                self._supplier(conn, supplier_id)
                if replace_id is not None:
                    old = conn.execute("SELECT * FROM supplier_files WHERE id = ? AND supplier_id = ?",
                                       (replace_id, supplier_id)).fetchone()
                    conn.execute("DELETE FROM supplier_files WHERE id = ?", (replace_id,))
                file_id = conn.execute("INSERT INTO supplier_files(supplier_id, kind, quote_id, original_name, stored_name,"
                                       " content_type, size_bytes, sha256, uploaded_by, uploaded_at)"
                                       " VALUES (?,?,?,?,?,?,?,?,?,?)",
                                       (supplier_id, kind, quote_id, original, stored_name, allowed[suffix], len(content),
                                        digest, actor.id, iso())).lastrowid
                record(conn, actor, "proveedor.archivo_subir", "supplier_file", file_id,
                       {"proveedor": supplier_id, "tipo": kind, "archivo": original, "bytes": len(content), "sha256": digest,
                        "reemplaza": old["original_name"] if old else None})
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        if old is not None:
            self._unlink(supplier_id, old["stored_name"])
        with self.db.read() as conn:
            row = dict(conn.execute(f"SELECT {FILE_COLUMNS} FROM supplier_files WHERE id = ?", (file_id,)).fetchone())
        row.pop("stored_name")
        return row

    def _path(self, supplier_id: int, stored_name: str) -> Path:
        folder = (self.root / str(int(supplier_id))).resolve()
        path = (folder / stored_name).resolve()
        if path.parent != folder:       # defensa adicional: nunca salir de la carpeta del proveedor
            raise NotFoundError("Archivo no encontrado.")
        return path

    def _unlink(self, supplier_id: int, stored_name: str) -> None:
        try:
            self._path(supplier_id, stored_name).unlink(missing_ok=True)
        except OSError:
            pass   # si Windows lo tiene abierto queda huérfano; no afecta a los datos

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _supplier(conn: sqlite3.Connection, supplier_id: int) -> dict:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not row:
            raise NotFoundError("Proveedor no encontrado.")
        return dict(row)

    @staticmethod
    def _child(conn: sqlite3.Connection, table: str, supplier_id: int, item_id: int | None, label: str) -> dict:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND supplier_id = ?", (item_id, supplier_id)).fetchone()
        if not row:
            raise NotFoundError(f"{label} no encontrada para este proveedor.")
        return dict(row)


FILE_COLUMNS = ("id, supplier_id, kind, quote_id, original_name, stored_name, content_type, size_bytes, sha256,"
                " uploaded_by, uploaded_at")


def safe_filename(name: str) -> str:
    """Nombre para mostrar y descargar: sin rutas, sin caracteres de control ni reservados de Windows."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = unicodedata.normalize("NFC", base)
    base = re.sub(r'[\x00-\x1f<>:"|?*]', "", base).strip().strip(".")
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = re.sub(r"\s+", " ", stem)[:120] or "archivo"
    if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                     *(f"LPT{i}" for i in range(1, 10))}:
        stem = f"_{stem}"
    return f"{stem}.{ext.lower()}" if ext else stem


def _check_signature(suffix: str, content: bytes) -> None:
    """Comprueba que el contenido corresponde de verdad a la extensión (no solo el nombre)."""
    bad = ValidationError("El archivo no corresponde a su formato.", {"file": "El archivo está dañado o tiene otra extensión."})
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            raise bad from None
        if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
            raise bad
    elif suffix == ".xls":
        if not content.startswith(OLE_MAGIC):
            raise bad
    elif suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise bad
    elif suffix == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise bad
    elif suffix in (".jpg", ".jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            raise bad


def _text(data: dict, key: str, label: str, required: bool = False, max_len: int = 200) -> str:
    value = data.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValidationError("Faltan datos.", {key: f"{label} es obligatorio."})
    if len(value) > max_len:
        raise ValidationError("Texto demasiado largo.", {key: f"{label}: máximo {max_len} caracteres."})
    return value


def _date(value, key: str, required: bool = False) -> str | None:
    text = (str(value).strip() if value is not None else "")
    if not text:
        if required:
            raise ValidationError("Faltan datos.", {key: "La fecha es obligatoria."})
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ValidationError("Fecha no válida.", {key: "Use el formato AAAA-MM-DD."}) from None


def _choice(value: str, options: tuple, key: str) -> str:
    if value not in options:
        raise ValidationError("Opción no válida.", {key: "Opción no válida."})
    return value


def _check_version(data: dict, current: dict) -> None:
    if "version" in data and data["version"] is not None and int(data["version"]) != current["version"]:
        raise ConflictError("Otra persona modificó este registro. Recargue y vuelva a intentarlo.")


def _one(cursor: sqlite3.Cursor) -> dict | None:
    row = cursor.fetchone()
    return dict(row) if row else None


def _quote_flags(quote: dict) -> dict:
    """Marca como vencida (solo para mostrar) una cotización pendiente cuyo vencimiento ya pasó."""
    quote["expired"] = bool(quote["status"] == "pendiente" and quote["due_date"]
                            and quote["due_date"] < date.today().isoformat())
    return quote
