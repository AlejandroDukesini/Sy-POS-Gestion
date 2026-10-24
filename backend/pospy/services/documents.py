"""Documentos comerciales (cotizaciones, órdenes y los tipos que el administrador cree).

Un tipo de documento define: nombre, plantilla Excel, mapeo de campos, campos adicionales,
numeración, vigencia, impresora y configuración de página. Los documentos usan el mismo motor de
precios que el punto de venta. Generar, imprimir y reimprimir queda registrado.
Un documento NO mueve inventario: solo una venta lo hace.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import from_cents, from_milli
from ..core.query import like, paginate, slug
from ..documents import com_excel, templates
from ..documents.excel_safety import ExcelError, ensure_workbook, sha256, unsupported_parts
from . import pricing

PAGE_DEFAULTS = {"paper": "letter", "orientation": "portrait", "margins_cm": 1.5, "fit_width": True, "scale": 100}
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024


def _page_setup(raw: dict) -> dict:
    setup = {**PAGE_DEFAULTS, **{k: v for k, v in (raw or {}).items() if k in PAGE_DEFAULTS}}
    errors = {}
    if setup["paper"] not in templates.PAPER:
        errors["paper"] = "Tamaño de papel no válido."
    if setup["orientation"] not in ("portrait", "landscape"):
        errors["orientation"] = "Orientación no válida."
    try:
        setup["margins_cm"] = float(setup["margins_cm"])
        if not 0 <= setup["margins_cm"] <= 5:
            raise ValueError
    except (TypeError, ValueError):
        errors["margins_cm"] = "Márgenes entre 0 y 5 cm."
    try:
        setup["scale"] = int(setup["scale"])
        if not 10 <= setup["scale"] <= 400:
            raise ValueError
    except (TypeError, ValueError):
        errors["scale"] = "Escala entre 10 % y 400 %."
    setup["fit_width"] = bool(setup["fit_width"])
    if errors:
        raise ValidationError("Revise la configuración de página.", errors)
    return setup


def _extra_fields(raw) -> list[dict]:
    fields, seen = [], set()
    for f in raw or []:
        key = re.sub(r"[^a-z0-9_]", "_", str(f.get("key") or f.get("label") or "").strip().lower())[:30].strip("_")
        label = str(f.get("label") or "").strip()[:60]
        if not key or not label:
            raise ValidationError("Cada campo adicional necesita un nombre.", {"fields": "Campo sin nombre."})
        if key in seen:
            raise ValidationError("Campos adicionales repetidos.", {"fields": f"El campo «{key}» está repetido."})
        seen.add(key)
        fields.append({"key": key, "label": label, "required": bool(f.get("required"))})
    if len(fields) > 20:
        raise ValidationError("Máximo 20 campos adicionales.")
    return fields


class DocumentService:
    def __init__(self, db, settings, config, printing):
        self.db = db
        self.settings = settings
        self.templates_dir: Path = config.templates_dir
        self.output_dir: Path = config.output_dir
        self.printing = printing

    def _tz(self) -> str:
        return self.settings.get("empresa")["timezone"]

    # ------------------------------------------------------------------ tipos de documento
    def types(self, actor: Actor, include_inactive: bool = False) -> list[dict]:
        if not (actor.can("documentos.ver") or actor.can("gestion.configuracion")):
            actor.require("documentos.ver")
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT t.*, (SELECT COUNT(*) FROM commercial_documents d WHERE d.type_id = t.id) AS documents,"
                " (SELECT COUNT(*) FROM document_outputs o JOIN commercial_documents d ON d.id = o.document_id"
                "   WHERE d.type_id = t.id) AS generated,"
                " (SELECT COUNT(*) FROM print_jobs j JOIN commercial_documents d ON d.id = j.target_id"
                "   WHERE j.target_type = 'documento' AND j.status = 'ok' AND d.type_id = t.id) AS printed,"
                " (SELECT MAX(d.created_at) FROM commercial_documents d WHERE d.type_id = t.id) AS last_used_at,"
                " (SELECT COUNT(*) FROM commercial_documents d WHERE d.type_id = t.id"
                "   AND d.created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')) AS last_30_days"
                " FROM document_types t" + ("" if include_inactive else " WHERE t.active = 1") + " ORDER BY t.name").fetchall()
        return [self._type_public(dict(r)) for r in rows]

    def _type_public(self, t: dict) -> dict:
        t["mapping"] = json.loads(t["mapping"] or "{}")
        t["fields"] = json.loads(t["fields"] or "[]")
        t["page_setup"] = {**PAGE_DEFAULTS, **json.loads(t["page_setup"] or "{}")}
        t["has_template"] = bool(t["template_file"]) and (self.templates_dir / t["template_file"]).exists()
        t["template_problems"] = []
        if t["has_template"]:
            try:
                t["template_problems"] = templates.validate(self.templates_dir / t["template_file"],
                                                            templates.Mapping.from_dict(t["mapping"]))
                t["template_needs_excel"] = unsupported_parts(self.templates_dir / t["template_file"])
            except ExcelError as exc:
                t["template_problems"] = [exc.detail]
        elif t["template_file"]:
            t["template_problems"] = ["El archivo de la plantilla no se encuentra en la carpeta de datos."]
        t["available_fields"] = {"header": templates.HEADER_FIELDS, "line": templates.LINE_FIELDS,
                                 "extra": {f"extra.{f['key']}": f["label"] for f in t["fields"]}}
        return t

    def get_type(self, actor: Actor, type_id: int) -> dict:
        for t in self.types(actor, include_inactive=True):
            if t["id"] == type_id:
                return t
        raise NotFoundError("Tipo de documento no encontrado.")

    def save_type(self, actor: Actor, data: dict, type_id: int | None = None) -> dict:
        actor.require("gestion.configuracion")
        name = (data.get("name") or "").strip()
        if not name or len(name) > 60:
            raise ValidationError("Revise el nombre.", {"name": "Nombre obligatorio (máximo 60 caracteres)."})
        prefix = (data.get("prefix") or "").strip()[:10]
        if prefix and not re.fullmatch(r"[A-Za-z0-9\-_/]+", prefix):
            raise ValidationError("Prefijo no válido.", {"prefix": "Use letras, números, guion o barra."})
        try:
            validity = int(data.get("validity_days") or 0)
            next_no = int(data.get("next_number") or 1)
        except (TypeError, ValueError):
            raise ValidationError("Revise los números.", {"validity_days": "Número entero."}) from None
        if not 0 <= validity <= 365:
            raise ValidationError("Vigencia no válida.", {"validity_days": "Entre 0 y 365 días."})
        page = _page_setup(data.get("page_setup") or {})
        fields = _extra_fields(data.get("fields"))
        printer = (data.get("printer") or "").strip()[:200]
        numbering = int(bool(data.get("numbering", True)))
        active = int(bool(data.get("active", True)))
        with self.db.tx() as conn:
            now = iso()
            if type_id is None:
                code = slug(data.get("code") or name)
                if len(code) < 2 or conn.execute("SELECT 1 FROM document_types WHERE code = ?", (code,)).fetchone():
                    raise ConflictError("Ya existe un tipo con ese código.", {"code": "Código repetido o muy corto."})
                type_id = conn.execute(
                    "INSERT INTO document_types(code, name, prefix, next_number, numbering, validity_days, printer, page_setup,"
                    " fields, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (code, name, prefix, max(1, next_no), numbering, validity, printer, json.dumps(page),
                     json.dumps(fields, ensure_ascii=False), active, now, now)).lastrowid
                record(conn, actor, "tipo_documento.crear", "document_type", type_id, {"nombre": name})
            else:
                current = conn.execute("SELECT * FROM document_types WHERE id = ?", (type_id,)).fetchone()
                if not current:
                    raise NotFoundError("Tipo de documento no encontrado.")
                if "version" in data and int(data["version"]) != current["version"]:
                    raise ConflictError("Otra persona modificó este tipo. Recargue y vuelva a intentarlo.")
                last = conn.execute("SELECT COUNT(*) FROM commercial_documents WHERE type_id = ?", (type_id,)).fetchone()[0]
                if next_no < current["next_number"] and last:
                    raise ValidationError("El consecutivo no puede retroceder si ya hay documentos.",
                                          {"next_number": f"Mínimo {current['next_number']}."})
                conn.execute("UPDATE document_types SET name = ?, prefix = ?, next_number = ?, numbering = ?, validity_days = ?,"
                             " printer = ?, page_setup = ?, fields = ?, active = ?, updated_at = ?, version = version + 1"
                             " WHERE id = ?", (name, prefix, max(1, next_no), numbering, validity, printer, json.dumps(page),
                                               json.dumps(fields, ensure_ascii=False), active, now, type_id))
                record(conn, actor, "tipo_documento.actualizar", "document_type", type_id,
                       {"nombre": name, "impresora": printer, "activo": active, "pagina": page})
            # Si cambian los campos adicionales, se vuelve a analizar la plantilla.
            row = conn.execute("SELECT * FROM document_types WHERE id = ?", (type_id,)).fetchone()
            if row["template_file"] and (self.templates_dir / row["template_file"]).exists():
                previous = templates.Mapping.from_dict(json.loads(row["mapping"]))
                mapping = templates.scan(self.templates_dir / row["template_file"], {f["key"] for f in fields}, previous)
                conn.execute("UPDATE document_types SET mapping = ? WHERE id = ?", (json.dumps(mapping.to_dict(), default=str), type_id))
        return self.get_type(actor, type_id)

    def upload_template(self, actor: Actor, type_id: int, filename: str, content: bytes) -> dict:
        actor.require("gestion.configuracion")
        suffix = Path(filename or "").suffix.lower()
        if suffix not in (".xlsx", ".xlsm"):
            raise ValidationError("Formato no soportado.", {"file": "Suba un archivo .xlsx o .xlsm."})
        if len(content) > MAX_TEMPLATE_BYTES:
            raise ValidationError("Archivo demasiado grande.", {"file": "Máximo 10 MB."})
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM document_types WHERE id = ?", (type_id,)).fetchone()
        if not row:
            raise NotFoundError("Tipo de documento no encontrado.")
        tmp = self.templates_dir / f".subida-{type_id}{suffix}"
        tmp.write_bytes(content)
        try:
            ensure_workbook(tmp)
            digest = sha256(tmp)
            target = self.templates_dir / f"{row['code']}-{digest[:10]}{suffix}"
            extra = {f["key"] for f in json.loads(row["fields"] or "[]")}
            previous = templates.Mapping.from_dict(json.loads(row["mapping"] or "{}"))
            mapping = templates.scan(tmp, extra, previous)
            tmp.replace(target)
        finally:
            if tmp.exists():
                tmp.unlink()
        mapping.fingerprint = digest
        with self.db.tx() as conn:
            conn.execute("UPDATE document_types SET template_file = ?, template_sha256 = ?, mapping = ?, updated_at = ?,"
                         " version = version + 1 WHERE id = ?",
                         (target.name, digest, json.dumps(mapping.to_dict(), default=str), iso(), type_id))
            record(conn, actor, "tipo_documento.plantilla", "document_type", type_id,
                   {"archivo": filename, "sha256": digest, "campos": sorted(mapping.fields), "filas": mapping.capacity})
        return self.get_type(actor, type_id)

    def sample_template(self, actor: Actor, type_id: int) -> tuple[bytes, str]:
        actor.require("gestion.configuracion")
        t = self.get_type(actor, type_id)
        path = self.output_dir / f"plantilla-base-{t['code']}.xlsx"
        templates.create_sample(t["name"], path, t["fields"])
        data = path.read_bytes()
        path.unlink()
        return data, f"plantilla-{t['code']}.xlsx"

    def template_file(self, actor: Actor, type_id: int) -> tuple[Path, str]:
        actor.require("gestion.configuracion")
        t = self.get_type(actor, type_id)
        if not t["has_template"]:
            raise NotFoundError("Este tipo de documento no tiene plantilla.")
        return self.templates_dir / t["template_file"], t["template_file"]

    def assign_field(self, actor: Actor, type_id: int, field_name: str, cell: str | None) -> dict:
        actor.require("gestion.configuracion")
        t = self.get_type(actor, type_id)
        if not t["has_template"]:
            raise ValidationError("Primero suba la plantilla.")
        mapping = templates.Mapping.from_dict(t["mapping"])
        extra = {f["key"] for f in t["fields"]}
        if cell:
            templates.assign(mapping, self.templates_dir / t["template_file"], field_name, cell, extra)
        else:
            templates.unassign(mapping, field_name)
        with self.db.tx() as conn:
            conn.execute("UPDATE document_types SET mapping = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (json.dumps(mapping.to_dict(), default=str), iso(), type_id))
            record(conn, actor, "tipo_documento.mapeo", "document_type", type_id, {"campo": field_name, "celda": cell})
        return self.get_type(actor, type_id)

    def set_capacity(self, actor: Actor, type_id: int, capacity: int) -> dict:
        actor.require("gestion.configuracion")
        t = self.get_type(actor, type_id)
        mapping = templates.Mapping.from_dict(t["mapping"])
        if not mapping.line_row:
            raise ValidationError("La plantilla no tiene fila de productos.")
        if not 1 <= int(capacity) <= 500:
            raise ValidationError("Capacidad no válida.", {"capacity": "Entre 1 y 500 filas."})
        mapping.capacity = int(capacity)
        with self.db.tx() as conn:
            conn.execute("UPDATE document_types SET mapping = ?, version = version + 1 WHERE id = ?",
                         (json.dumps(mapping.to_dict(), default=str), type_id))
            record(conn, actor, "tipo_documento.capacidad", "document_type", type_id, {"filas": mapping.capacity})
        return self.get_type(actor, type_id)

    # ------------------------------------------------------------------ documentos
    def list(self, actor: Actor, type_id: int | None = None, q: str = "", status: str = "", page: int = 1,
             page_size: int = 50) -> dict:
        actor.require("documentos.ver")
        where, params = [], []
        if type_id:
            where.append("d.type_id = ?")
            params.append(type_id)
        if status:
            where.append("d.status = ?")
            params.append(status)
        if q:
            where.append("(d.number LIKE ? ESCAPE '\\' OR d.customer_name LIKE ? ESCAPE '\\'"
                         " OR d.customer_identification LIKE ? ESCAPE '\\')")
            params += [like(q)] * 3
        sql = ("SELECT d.id, d.number, d.status, d.customer_name, d.total_cents, d.doc_date, d.valid_until, d.created_at,"
               " t.name AS type_name, t.code AS type_code, u.username,"
               " (SELECT COUNT(*) FROM print_jobs j WHERE j.target_type = 'documento' AND j.target_id = d.id"
               "  AND j.status = 'ok') AS prints"
               " FROM commercial_documents d JOIN document_types t ON t.id = d.type_id JOIN users u ON u.id = d.user_id"
               + (" WHERE " + " AND ".join(where) if where else ""))
        with self.db.read() as conn:
            return paginate(conn, sql, params, sort="id", direction="desc", default_sort="id",
                            tiebreak="d.id", sortable={"id": "d.id"}, page=page, page_size=page_size)

    def get(self, actor: Actor, doc_id: int) -> dict:
        actor.require("documentos.ver")
        with self.db.read() as conn:
            return self._detail(conn, doc_id)

    def _detail(self, conn: sqlite3.Connection, doc_id: int) -> dict:
        row = conn.execute("SELECT d.*, t.name AS type_name, t.code AS type_code, u.username, u.full_name AS user_full_name"
                           " FROM commercial_documents d JOIN document_types t ON t.id = d.type_id"
                           " JOIN users u ON u.id = d.user_id WHERE d.id = ?", (doc_id,)).fetchone()
        if not row:
            raise NotFoundError("Documento no encontrado.")
        doc = dict(row)
        doc["extra"] = json.loads(doc["extra"] or "{}")
        doc["lines"] = [dict(r) for r in conn.execute("SELECT * FROM commercial_document_lines WHERE document_id = ?"
                                                      " ORDER BY line_no", (doc_id,))]
        doc["outputs"] = [dict(r) for r in conn.execute("SELECT o.*, u.username FROM document_outputs o LEFT JOIN users u"
                                                        " ON u.id = o.user_id WHERE document_id = ? ORDER BY o.id DESC",
                                                        (doc_id,))]
        doc["prints"] = [dict(r) for r in conn.execute("SELECT j.*, u.username FROM print_jobs j LEFT JOIN users u"
                                                       " ON u.id = j.user_id WHERE target_type = 'documento'"
                                                       " AND target_id = ? ORDER BY j.id DESC", (doc_id,))]
        return doc

    def _customer_fields(self, conn: sqlite3.Connection, data: dict) -> dict:
        out = {k: (data.get(k) or "").strip()[:200] for k in ("customer_name", "customer_identification", "customer_phone",
                                                               "customer_email", "customer_address")}
        customer_id = data.get("customer_id") or None
        if customer_id:
            c = conn.execute("SELECT * FROM customers WHERE id = ?", (int(customer_id),)).fetchone()
            if not c:
                raise ValidationError("Cliente no encontrado.", {"customer_id": "Seleccione un cliente válido."})
            out = {"customer_name": c["name"], "customer_identification": c["identification"] or "",
                   "customer_phone": c["phone"], "customer_email": c["email"], "customer_address": c["address"]}
        if not out["customer_name"]:
            raise ValidationError("Faltan datos del cliente.", {"customer_name": "El nombre del cliente es obligatorio."})
        out["customer_id"] = int(customer_id) if customer_id else None
        return out

    def _extra_values(self, type_row, data: dict) -> dict:
        fields = json.loads(type_row["fields"] or "[]")
        raw = data.get("extra") or {}
        values, errors = {}, {}
        for f in fields:
            value = str(raw.get(f["key"]) or "").strip()[:300]
            if f["required"] and not value:
                errors[f"extra.{f['key']}"] = f"{f['label']} es obligatorio."
            values[f["key"]] = value
        if errors:
            raise ValidationError("Faltan datos del documento.", errors)
        return values

    def create(self, actor: Actor, data: dict, idempotency_key: str | None = None) -> dict:
        actor.require("documentos.crear")
        with self.db.tx() as conn:
            if idempotency_key:
                done = conn.execute("SELECT id FROM commercial_documents WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if done:
                    return {"duplicate": True, **self._detail(conn, done[0])}
            t = conn.execute("SELECT * FROM document_types WHERE id = ?", (int(data.get("type_id") or 0),)).fetchone()
            if not t or not t["active"]:
                raise ValidationError("Seleccione un tipo de documento activo.", {"type_id": "Tipo no válido."})
            lines, totals = pricing.price_items(conn, actor, data.get("lines") or [], self.settings.get("ventas", conn))
            customer = self._customer_fields(conn, data)
            extra = self._extra_values(t, data)
            today = local_today(self._tz())
            if t["numbering"]:
                number = f"{t['prefix']}{t['next_number']:06d}"
                conn.execute("UPDATE document_types SET next_number = next_number + 1 WHERE id = ?", (t["id"],))
            else:
                number = (data.get("number") or "").strip()[:40]
                if not number:
                    raise ValidationError("Escriba el número del documento.", {"number": "Número obligatorio."})
            if conn.execute("SELECT 1 FROM commercial_documents WHERE type_id = ? AND number = ?", (t["id"], number)).fetchone():
                raise ConflictError("Ya existe un documento con ese número.", {"number": "Número repetido."})
            valid_until = str(today + timedelta(days=t["validity_days"])) if t["validity_days"] else None
            now = iso()
            doc_id = conn.execute(
                "INSERT INTO commercial_documents(type_id, number, idempotency_key, customer_id, customer_name,"
                " customer_identification, customer_phone, customer_email, customer_address, notes, extra, doc_date,"
                " valid_until, gross_cents, discount_cents, tax_cents, total_cents, user_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["id"], number, idempotency_key, customer["customer_id"], customer["customer_name"],
                 customer["customer_identification"], customer["customer_phone"], customer["customer_email"],
                 customer["customer_address"], (data.get("notes") or "").strip()[:1000], json.dumps(extra, ensure_ascii=False),
                 str(today), valid_until, totals.gross_cents, totals.discount_cents, totals.tax_cents, totals.total_cents,
                 actor.id, now, now)).lastrowid
            self._insert_lines(conn, doc_id, lines)
            record(conn, actor, "documento.crear", "document", doc_id, {"tipo": t["name"], "numero": number,
                                                                        "total": totals.total_cents})
            return {"duplicate": False, **self._detail(conn, doc_id)}

    @staticmethod
    def _insert_lines(conn: sqlite3.Connection, doc_id: int, lines: list[pricing.PricedLine]) -> None:
        conn.executemany(
            "INSERT INTO commercial_document_lines(document_id, line_no, product_id, code, description, qty_milli,"
            " list_price_cents, unit_price_cents, manual_discount_bp, gross_cents, discount_cents, net_cents, tax_rate_bp,"
            " tax_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(doc_id, ln.line_no, ln.product_id, ln.code, ln.description, ln.qty_milli, ln.list_price_cents,
              ln.unit_price_cents, ln.manual_discount_bp, ln.gross_cents, ln.discount_cents, ln.net_cents, ln.tax_rate_bp,
              ln.tax_cents) for ln in lines])

    def update(self, actor: Actor, doc_id: int, data: dict) -> dict:
        actor.require("documentos.crear")
        with self.db.tx() as conn:
            doc = conn.execute("SELECT * FROM commercial_documents WHERE id = ?", (doc_id,)).fetchone()
            if not doc:
                raise NotFoundError("Documento no encontrado.")
            if doc["status"] != "vigente":
                raise ValidationError("Un documento anulado no se puede modificar.")
            if int(data.get("version") or 0) != doc["version"]:
                raise ConflictError("Otra persona modificó este documento. Recargue y vuelva a intentarlo.")
            t = conn.execute("SELECT * FROM document_types WHERE id = ?", (doc["type_id"],)).fetchone()
            lines, totals = pricing.price_items(conn, actor, data.get("lines") or [], self.settings.get("ventas", conn))
            customer = self._customer_fields(conn, data)
            extra = self._extra_values(t, data)
            conn.execute("DELETE FROM commercial_document_lines WHERE document_id = ?", (doc_id,))
            self._insert_lines(conn, doc_id, lines)
            conn.execute(
                "UPDATE commercial_documents SET customer_id = ?, customer_name = ?, customer_identification = ?,"
                " customer_phone = ?, customer_email = ?, customer_address = ?, notes = ?, extra = ?, gross_cents = ?,"
                " discount_cents = ?, tax_cents = ?, total_cents = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (customer["customer_id"], customer["customer_name"], customer["customer_identification"],
                 customer["customer_phone"], customer["customer_email"], customer["customer_address"],
                 (data.get("notes") or "").strip()[:1000], json.dumps(extra, ensure_ascii=False), totals.gross_cents,
                 totals.discount_cents, totals.tax_cents, totals.total_cents, iso(), doc_id))
            record(conn, actor, "documento.actualizar", "document", doc_id, {"numero": doc["number"],
                                                                             "total": totals.total_cents})
            return self._detail(conn, doc_id)

    def void(self, actor: Actor, doc_id: int, reason: str) -> dict:
        actor.require("documentos.anular")
        if not (reason or "").strip():
            raise ValidationError("Indique el motivo.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            doc = conn.execute("SELECT * FROM commercial_documents WHERE id = ?", (doc_id,)).fetchone()
            if not doc:
                raise NotFoundError("Documento no encontrado.")
            if doc["status"] == "anulado":
                raise ValidationError("El documento ya estaba anulado.")
            conn.execute("UPDATE commercial_documents SET status = 'anulado', updated_at = ?, version = version + 1 WHERE id = ?",
                         (iso(), doc_id))
            record(conn, actor, "documento.anular", "document", doc_id, {"numero": doc["number"], "motivo": reason.strip()})
            return self._detail(conn, doc_id)

    # ------------------------------------------------------------------ generación, vista previa e impresión
    def _values(self, doc: dict) -> tuple[dict, list[dict]]:
        company = self.settings.get("empresa")
        header = {
            "tipo_documento": doc["type_name"].upper(), "numero": doc["number"],
            "fecha": parse_date(doc["doc_date"]).strftime("%d/%m/%Y"),
            "fecha_validez": parse_date(doc["valid_until"]).strftime("%d/%m/%Y") if doc["valid_until"] else "",
            "cliente_nombre": doc["customer_name"], "cliente_identificacion": doc["customer_identification"],
            "cliente_telefono": doc["customer_phone"], "cliente_email": doc["customer_email"],
            "cliente_direccion": doc["customer_address"], "observaciones": doc["notes"],
            "subtotal": float(from_cents(doc["gross_cents"])), "descuento": float(from_cents(doc["discount_cents"])),
            "base": float(from_cents(doc["total_cents"] - doc["tax_cents"])), "iva": float(from_cents(doc["tax_cents"])),
            "total": float(from_cents(doc["total_cents"])), "vendedor": doc["user_full_name"] or doc["username"],
            "empresa_nombre": company["name"], "empresa_nit": company["tax_id"], "empresa_direccion": company["address"],
            "empresa_telefono": company["phone"], "empresa_email": company["email"], "empresa_pie": company["document_footer"],
        }
        header.update({f"extra.{k}": v for k, v in doc["extra"].items()})
        lines = [{"n": i, "codigo": ln["code"], "descripcion": ln["description"], "unidad": "",
                  "cantidad": float(from_milli(ln["qty_milli"])), "precio_lista": float(from_cents(ln["list_price_cents"])),
                  "precio": float(from_cents(ln["unit_price_cents"])), "descuento": float(from_cents(ln["discount_cents"])),
                  "iva_pct": ln["tax_rate_bp"] / 100, "total": float(from_cents(ln["net_cents"]))}
                 for i, ln in enumerate(doc["lines"], start=1)]
        return header, lines

    def generate(self, actor: Actor, doc_id: int) -> Path:
        actor.require("documentos.ver")
        doc = self.get(actor, doc_id)
        t = self.get_type(actor, doc["type_id"])
        if not t["has_template"]:
            raise ValidationError(f"El tipo «{t['name']}» no tiene plantilla. Súbala en Gestión › Tipos de documento.")
        template = self.templates_dir / t["template_file"]
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", doc["number"])
        out = self.output_dir / t["code"] / f"{t['code']}-{safe}{template.suffix}"
        header, lines = self._values(doc)
        templates.render(template, templates.Mapping.from_dict(t["mapping"]), out, header, lines, t["page_setup"])
        with self.db.tx() as conn:
            conn.execute("INSERT INTO document_outputs(document_id, file_name, template_sha256, user_id, created_at)"
                         " VALUES (?,?,?,?,?)", (doc_id, out.name, t["template_sha256"], actor.id, iso()))
            record(conn, actor, "documento.generar", "document", doc_id, {"archivo": out.name})
        return out

    def preview(self, actor: Actor, doc_id: int) -> dict:
        path = self.generate(actor, doc_id)
        t = self.get_type(actor, self.get(actor, doc_id)["type_id"])
        return {"html": templates.preview_html(path, templates.Mapping.from_dict(t["mapping"]).sheet),
                "file_name": path.name, "page_setup": t["page_setup"], "printer": t["printer"],
                "direct_print": com_excel.com_available()}

    def pdf(self, actor: Actor, doc_id: int) -> Path:
        path = self.generate(actor, doc_id)
        return com_excel.export_pdf(path, path.with_suffix(".pdf"))

    def print(self, actor: Actor, doc_id: int, printer: str | None = None, copies: int = 1) -> dict:
        actor.require("documentos.imprimir")
        doc = self.get(actor, doc_id)
        if doc["status"] == "anulado":
            raise ValidationError("El documento está anulado.")
        t = self.get_type(actor, doc["type_id"])
        target = (printer or "").strip() or t["printer"]
        copies = max(1, min(20, int(copies or 1)))
        error = None
        try:
            path = self.generate(actor, doc_id)
            com_excel.print_workbook(path, target, copies, t["page_setup"])
        except (ExcelError, ValidationError) as exc:
            error = exc.detail
        with self.db.tx() as conn:
            self.printing.log(conn, actor, "documento", doc_id, f"{t['name']} {doc['number']}", target or "", "excel",
                              copies, error)
            record(conn, actor, "documento.imprimir", "document", doc_id,
                   {"impresora": target, "copias": copies, "error": error, "reimpresion": bool(doc["prints"])})
        if error:
            raise ExcelError(error)
        return {"printed": True, "printer": target, "copies": copies}
