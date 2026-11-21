"""Plantillas de impresión: importar un Excel o diseñar desde el POS, vincular celdas con datos del POS,
tabla de productos dinámica, cálculos, versiones y documentos emitidos (PDF).

- Administrar plantillas exige gestion.configuracion. Usarlas para generar un documento exige el
  permiso de esa operación (documentos.ver / ventas.historial o ventas.vender).
- Cada plantilla pertenece a un inventario (general o de un grupo): la de un grupo solo la ven y usan
  quienes entran a ese inventario (InventoryScopes); para los demás no existe (404).
- Guardar crea una versión nueva e inmutable. Cada documento emitido guarda la versión usada, el PDF
  y los datos, así que editar una plantilla no cambia lo ya emitido.
- El Excel importado se guarda intacto (también sus macros, que nunca se ejecutan).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, parse_date
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..documents import canvas as canvas_mod
from ..documents import engine, xlsx_import
from ..documents.excel_safety import ExcelError
from ..documents.layout import LayoutError, empty_layout, sanitize_layout
from ..documents.layout_pdf import ImageError, _jpeg_info, _png_objects, page_count, render_pdf
from ..documents.layout_xlsx import write_xlsx
from ..printing.printers import PrintError, list_printers
from .scopes import InventoryScopes

KINDS = {"documento": "Documento comercial", "venta": "Venta", "recibo": "Recibo"}
MAX_EXCEL = 10 * 1024 * 1024
MAX_IMAGE = 3 * 1024 * 1024
MAX_IMAGE_PX = 6000
STAGING_TTL_FILES = 50


def _dec(cents: int | None) -> Decimal:
    return Decimal(int(cents or 0)) / 100


def _id_type(identification: str) -> str:
    ident = (identification or "").strip()
    if not ident:
        return ""
    return "NIT" if "-" in ident or len(re.sub(r"\D", "", ident)) == 9 else "CC"


class PrintTemplateService:
    def __init__(self, db, settings, config, scopes: InventoryScopes):
        self.db = db
        self.settings = settings
        self.scopes = scopes
        self.root: Path = config.data_dir / "print_templates"
        self.staging: Path = config.data_dir / "print_templates" / "_importaciones"
        self.output_dir: Path = config.output_dir / "plantillas"
        for d in (self.root, self.staging, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ utilidades
    def _now_local(self) -> datetime:
        tz = self.settings.get("empresa")["timezone"]
        return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)

    def _dir(self, public_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", public_id or ""):
            raise NotFoundError("Plantilla no encontrada.")
        return self.root / public_id

    def _row(self, conn, actor: Actor, public_id: str):
        row = conn.execute("SELECT * FROM print_templates WHERE public_id = ? AND deleted_at IS NULL", (public_id,)).fetchone()
        if not row:
            raise NotFoundError("Plantilla no encontrada.")
        self.scopes.check(conn, actor, row["inventory_id"], "Plantilla")
        return row

    def _version(self, conn, template_id: int, number: int) -> dict:
        v = conn.execute("SELECT * FROM print_template_versions WHERE template_id = ? AND number = ?",
                         (template_id, number)).fetchone()
        if not v:
            raise NotFoundError("Versión de plantilla no encontrada.")
        return {"id": v["id"], "number": v["number"], "layout": json.loads(v["layout"]), "bindings": json.loads(v["bindings"]),
                "note": v["note"], "created_at": v["created_at"]}

    def _images(self, public_id: str, layout: dict) -> dict[str, bytes]:
        folder = self._dir(public_id)
        out = {}
        for img in layout.get("images", []):
            path = folder / img["file"]
            if path.is_file() and path.parent == folder:
                out[img["file"]] = path.read_bytes()
        return out

    def _image_files(self, public_id: str) -> set[str]:
        folder = self._dir(public_id)
        if not folder.exists():
            return set()
        return {p.name for p in folder.iterdir() if re.fullmatch(r"img[-A-Za-z0-9]*\.(jpg|png)", p.name)}

    @staticmethod
    def _design(layout: dict, bindings: dict) -> tuple[dict, dict, list[str]]:
        """Diseño listo para el motor: un lienzo se compila a cuadrícula; una cuadrícula se usa tal cual."""
        if isinstance(layout, dict) and layout.get("kind") == "canvas":
            return canvas_mod.compile_canvas(layout)
        return layout, bindings, []

    @staticmethod
    def catalog() -> dict:
        return {
            "fields": [{"group": g, "fields": [{"key": k, "label": lbl, "type": t} for k, (lbl, t) in items.items()]}
                       for g, items in engine.FIELDS.items()],
            "line_fields": [{"key": k, "label": lbl, "type": t} for k, (lbl, t) in engine.LINE_FIELDS.items()],
            "functions": ["SUMA", "REDONDEAR", "MAX", "MIN", "ABS", "SI_CERO"],
            "kinds": KINDS,
        }

    def _public(self, conn, row) -> dict:
        t = dict(row)
        t.pop("id")
        t.pop("original_file", None)
        t["inventory"] = self.scopes.describe(conn, row["inventory_id"])
        t.pop("inventory_id")
        t["document_type"] = None
        if row["document_type_id"]:
            dt = conn.execute("SELECT id, code, name FROM document_types WHERE id = ?", (row["document_type_id"],)).fetchone()
            t["document_type"] = dict(dt) if dt else None
        t["has_original"] = bool(row["original_file"])
        kind = conn.execute("SELECT json_extract(layout, '$.kind') FROM print_template_versions WHERE template_id = ? AND number = ?",
                            (row["id"], row["current_version"])).fetchone()
        t["designer"] = "canvas" if kind and kind[0] == "canvas" else "grid"
        t["outputs"] = conn.execute("SELECT COUNT(*) FROM print_outputs o JOIN print_template_versions v"
                                    " ON v.id = o.template_version_id WHERE v.template_id = ?", (row["id"],)).fetchone()[0]
        return t

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor, inventory: str | None = None, kind: str = "", document_type_id: int | None = None,
             only_active: bool = False) -> list[dict]:
        if not any(actor.can(p) for p in ("gestion.configuracion", "documentos.ver", "ventas.historial", "ventas.vender")):
            actor.require("gestion.configuracion")
        with self.db.read() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            where, params = ["deleted_at IS NULL", "inventory_id IS ?"], [inventory_id]
            if kind:
                where.append("kind = ?")
                params.append(kind)
            if document_type_id:
                where.append("document_type_id = ?")
                params.append(document_type_id)
            if only_active or not actor.can("gestion.configuracion"):
                where.append("active = 1")
            rows = conn.execute("SELECT * FROM print_templates WHERE " + " AND ".join(where)
                                + " ORDER BY kind, document_type_id, is_default DESC, name COLLATE NOCASE", params).fetchall()
            return [self._public(conn, r) for r in rows]

    def get(self, actor: Actor, public_id: str, version: int | None = None) -> dict:
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            row = self._row(conn, actor, public_id)
            t = self._public(conn, row)
            v = self._version(conn, row["id"], version or row["current_version"])
            t["versions"] = [dict(x) for x in conn.execute(
                "SELECT v.number, v.note, v.created_at, u.full_name AS created_by_name FROM print_template_versions v"
                " LEFT JOIN users u ON u.id = v.created_by WHERE v.template_id = ? ORDER BY v.number DESC", (row["id"],))]
        t["layout"], t["bindings"], t["loaded_version"] = v["layout"], v["bindings"], v["number"]
        compiled, cbind, notes = self._design(v["layout"], v["bindings"])
        t["designer"] = "canvas" if v["layout"].get("kind") == "canvas" else "grid"
        t["problems"] = engine.validate(compiled, cbind)
        t["design_notes"] = notes
        t["catalog"] = self.catalog()
        return t

    # ------------------------------------------------------------------ importar un Excel (2 pasos)
    def inspect_upload(self, actor: Actor, filename: str, content: bytes) -> dict:
        actor.require("gestion.configuracion")
        suffix = Path(filename or "").suffix.lower()
        if suffix not in (".xlsx", ".xlsm"):
            raise ValidationError("Formato no soportado.", {"file": "Suba un archivo .xlsx o .xlsm."})
        if len(content) > MAX_EXCEL:
            raise ValidationError("Archivo demasiado grande.", {"file": "Máximo 10 MB."})
        if content[:2] != b"PK":
            raise ValidationError("El archivo no es un libro de Excel válido.", {"file": "Archivo dañado o de otro tipo."})
        self._clean_staging()
        token = secrets.token_urlsafe(18)
        path = self.staging / f"{token}{suffix}"
        path.write_bytes(content)
        try:
            info = xlsx_import.inspect(path)
        except (ExcelError, KeyError, ValueError, OSError) as exc:
            path.unlink(missing_ok=True)
            detail = exc.detail if isinstance(exc, ExcelError) else "No se pudo leer el archivo de Excel."
            raise ValidationError(detail, {"file": detail}) from None
        (self.staging / f"{token}.json").write_text(json.dumps({"name": Path(filename).name[:120], "suffix": suffix,
                                                                 "user": actor.id}), encoding="utf-8")
        return {"token": token, "file_name": Path(filename).name, **info}

    def _clean_staging(self) -> None:
        files = sorted(self.staging.glob("*"), key=lambda p: p.stat().st_mtime)
        for old in files[:-STAGING_TTL_FILES]:
            old.unlink(missing_ok=True)

    def import_excel(self, actor: Actor, data: dict, inventory: str | None = None) -> dict:
        actor.require("gestion.configuracion")
        token = str(data.get("token") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,40}", token):
            raise ValidationError("Vuelva a subir el archivo.", {"file": "La importación venció."})
        meta_path = self.staging / f"{token}.json"
        if not meta_path.exists():
            raise ValidationError("Vuelva a subir el archivo.", {"file": "La importación venció."})
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("user") != actor.id:
            raise NotFoundError("Importación no encontrada.")
        source = self.staging / f"{token}{meta['suffix']}"
        sheet = str(data.get("sheet") or "")
        if not sheet:
            raise ValidationError("Elija la hoja que se usará como plantilla.", {"sheet": "Seleccione una hoja."})
        kind, doc_type = self._kind(data)
        try:
            layout, images, notes = xlsx_import.import_sheet(source, sheet)
        except ExcelError as exc:
            raise ValidationError(exc.detail, {"sheet": exc.detail}) from None
        with self.db.read() as conn:
            code = conn.execute("SELECT code FROM document_types WHERE id = ?", (doc_type,)).fetchone()[0] if doc_type else kind
        bindings, hints = xlsx_import.suggest_bindings(layout, "orden" if code == "orden" else "")
        name = (data.get("name") or Path(meta["name"]).stem).strip()[:80]
        public_id = secrets.token_urlsafe(12)
        folder = self._dir(public_id)
        folder.mkdir(parents=True)
        original = f"original{meta['suffix']}"
        shutil.copyfile(source, folder / original)
        for fname, content in images.items():
            (folder / fname).write_bytes(content)
        layout = sanitize_layout(layout, set(images))
        digest = hashlib.sha256((folder / original).read_bytes()).hexdigest()
        template = self._insert(actor, inventory, name, kind, doc_type, "excel", layout, bindings,
                                "Importada de Excel", public_id, original=(original, meta["name"], digest, sheet))
        source.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        template["import_notes"] = notes + hints
        return template

    def create_blank(self, actor: Actor, data: dict, inventory: str | None = None) -> dict:
        actor.require("gestion.configuracion")
        kind, doc_type = self._kind(data)
        name = (data.get("name") or "").strip()[:80]
        if not name:
            raise ValidationError("Escriba el nombre de la plantilla.", {"name": "Nombre obligatorio."})
        if data.get("designer") == "canvas":     # editor visual libre (lienzo físico, 80 mm por defecto)
            layout = canvas_mod.sanitize_canvas(canvas_mod.default_canvas(data.get("paper") or "roll80"), set())
            layout["discount_pct"] = "20" if data.get("discount_pct") == "20" else "0"
            bindings: dict = {}
        else:
            layout = empty_layout(6, 30)
            layout["cols"] = [8.0, 12.0, 34.0, 10.0, 14.0, 16.0]
            bindings = {"cells": {}, "products": None, "discount_pct": "20" if data.get("discount_pct") == "20" else "0"}
        public_id = secrets.token_urlsafe(12)
        self._dir(public_id).mkdir(parents=True)
        return self._insert(actor, inventory, name, kind, doc_type, "editor", layout, bindings, "Plantilla nueva", public_id)

    def _kind(self, data: dict) -> tuple[str, int | None]:
        kind = data.get("kind") or "documento"
        if kind not in KINDS:
            raise ValidationError("Tipo de plantilla no válido.", {"kind": "Elija documento, venta o recibo."})
        doc_type = None
        if kind == "documento":
            try:
                doc_type = int(data.get("document_type_id") or 0)
            except (TypeError, ValueError):
                doc_type = 0
            with self.db.read() as conn:
                if not conn.execute("SELECT 1 FROM document_types WHERE id = ?", (doc_type,)).fetchone():
                    raise ValidationError("Elija el tipo de documento (cotización, orden…).", {"document_type_id": "Obligatorio."})
        return kind, doc_type

    def _insert(self, actor: Actor, inventory: str | None, name: str, kind: str, doc_type: int | None, source: str,
                layout: dict, bindings: dict, note: str, public_id: str, original: tuple | None = None) -> dict:
        now = iso()
        with self.db.tx() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            tid = conn.execute(
                "INSERT INTO print_templates(public_id, inventory_id, kind, document_type_id, name, source, active, original_file,"
                " original_name, original_sha256, sheet, created_by, updated_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)",
                (public_id, inventory_id, kind, doc_type, name, source, *(original or (None, None, None, None)), actor.id, actor.id,
                 now, now)).lastrowid
            conn.execute("INSERT INTO print_template_versions(template_id, number, layout, bindings, note, created_by, created_at)"
                         " VALUES (?,?,?,?,?,?,?)", (tid, 1, json.dumps(layout, ensure_ascii=False),
                                                     json.dumps(bindings, ensure_ascii=False), note, actor.id, now))
            record(conn, actor, "plantilla.crear", "print_template", tid,
                   {"nombre": name, "origen": source, "archivo": original[1] if original else None,
                    "hoja": original[3] if original else None})
        return self.get(actor, public_id)

    # ------------------------------------------------------------------ guardar, administrar
    def save(self, actor: Actor, public_id: str, data: dict) -> dict:
        """Guarda el diseño y las vinculaciones como una versión nueva."""
        actor.require("gestion.configuracion")
        layout, bindings = self._clean_design(public_id, data.get("layout"), data.get("bindings"))
        compiled, cbind, _ = self._design(layout, bindings)
        problems = engine.validate(compiled, cbind)
        if problems:
            raise ValidationError("Revise las vinculaciones: " + problems[0], {"bindings": " ".join(problems)})
        activate = bool(data.get("activate"))
        with self.db.tx() as conn:
            row = self._row(conn, actor, public_id)
            if "version" in data and int(data["version"]) != row["version"]:
                raise ConflictError("Otra persona modificó esta plantilla. Recargue y vuelva a intentarlo.")
            number = row["current_version"] + 1
            conn.execute("INSERT INTO print_template_versions(template_id, number, layout, bindings, note, created_by, created_at)"
                         " VALUES (?,?,?,?,?,?,?)", (row["id"], number, json.dumps(layout, ensure_ascii=False),
                                                     json.dumps(bindings, ensure_ascii=False),
                                                     str(data.get("note") or "")[:200], actor.id, iso()))
            conn.execute("UPDATE print_templates SET current_version = ?, active = CASE WHEN ? THEN 1 ELSE active END,"
                         " updated_by = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (number, activate, actor.id, iso(), row["id"]))
            record(conn, actor, "plantilla.guardar", "print_template", row["id"], {"version": number, "activar": activate})
        return self.get(actor, public_id)

    def _clean_design(self, public_id: str, raw_layout: Any, raw_bindings: Any) -> tuple[dict, dict]:
        """Valida el diseño recibido: lienzo (editor visual) o cuadrícula (Excel importado o diseñado en celdas)."""
        files = self._image_files(public_id)
        try:
            if isinstance(raw_layout, dict) and raw_layout.get("kind") == "canvas":
                return canvas_mod.sanitize_canvas(raw_layout, files), {}
            layout = sanitize_layout(raw_layout, files)
        except LayoutError as exc:
            raise ValidationError("Revise el diseño: " + exc.problems[0], {"layout": " ".join(exc.problems)}) from None
        return layout, self._clean_bindings(raw_bindings)

    @staticmethod
    def _clean_bindings(raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ValidationError("Vinculaciones no válidas.")
        out: dict[str, Any] = {"cells": {}, "products": None, "discount_pct": str(raw.get("discount_pct") or "0")[:10]}

        def one(b: Any) -> dict:
            if not isinstance(b, dict):
                return {}
            e = {}
            if b.get("expr"):
                e["expr"] = str(b["expr"])[:300]
            elif b.get("field"):
                e["field"] = str(b["field"])[:40]
            if b.get("fallback"):
                e["fallback"] = str(b["fallback"])[:200]
            if b.get("format"):
                e["format"] = str(b["format"])[:80]
            return e
        cells = raw.get("cells") or {}
        if not isinstance(cells, dict) or len(cells) > 300:
            raise ValidationError("Demasiadas celdas vinculadas (máximo 300).")
        for ref, b in cells.items():
            e = one(b)
            if e:
                out["cells"][str(ref).upper()[:10]] = e
        p = raw.get("products")
        if isinstance(p, dict) and p.get("columns"):
            try:
                out["products"] = {"start": int(p["start"]), "end": int(p["end"]),
                                   "header_row": int(p.get("header_row") or 0),
                                   "columns": {str(k).upper()[:3]: one(v) for k, v in dict(p["columns"]).items() if one(v)}}
            except (KeyError, TypeError, ValueError):
                raise ValidationError("La tabla de productos necesita fila inicial y final.") from None
        return out

    def update_meta(self, actor: Actor, public_id: str, data: dict) -> dict:
        actor.require("gestion.configuracion")
        with self.db.tx() as conn:
            row = self._row(conn, actor, public_id)
            name = (data.get("name") if "name" in data else row["name"]) or ""
            name = name.strip()[:80]
            if not name:
                raise ValidationError("Escriba el nombre.", {"name": "Nombre obligatorio."})
            printer = (data.get("printer") if "printer" in data else row["printer"]) or ""
            printer = printer.strip()[:200]
            active = int(bool(data["active"])) if "active" in data else row["active"]
            is_default = int(bool(data["is_default"])) if "is_default" in data else row["is_default"]
            if is_default and not active:
                raise ValidationError("Una plantilla predeterminada debe estar activa.")
            if is_default:
                v = self._version(conn, row["id"], row["current_version"])
                compiled, cbind, _ = self._design(v["layout"], v["bindings"])
                problems = engine.validate(compiled, cbind)
                if problems:
                    raise ValidationError("Antes de usarla como predeterminada corrija: " + problems[0])
                conn.execute("UPDATE print_templates SET is_default = 0 WHERE inventory_id IS ? AND kind = ? AND document_type_id IS ?"
                             " AND deleted_at IS NULL AND id <> ?", (row["inventory_id"], row["kind"], row["document_type_id"], row["id"]))
            conn.execute("UPDATE print_templates SET name = ?, active = ?, is_default = ?, printer = ?, updated_by = ?,"
                         " updated_at = ?, version = version + 1 WHERE id = ?",
                         (name, active, is_default, printer, actor.id, iso(), row["id"]))
            record(conn, actor, "plantilla.actualizar", "print_template", row["id"],
                   {"nombre": name, "activa": active, "predeterminada": is_default, "impresora": printer})
        return self.get(actor, public_id)

    def duplicate(self, actor: Actor, public_id: str, name: str = "") -> dict:
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            row = self._row(conn, actor, public_id)
            v = self._version(conn, row["id"], row["current_version"])
            inv = self.scopes.describe(conn, row["inventory_id"])["key"]
        new_id = secrets.token_urlsafe(12)
        src, dst = self._dir(public_id), self._dir(new_id)
        dst.mkdir(parents=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copyfile(f, dst / f.name)
        original = None
        if row["original_file"]:
            original = (row["original_file"], row["original_name"], row["original_sha256"], row["sheet"])
        return self._insert(actor, inv, (name or f"{row['name']} (copia)")[:80], row["kind"], row["document_type_id"],
                            row["source"], v["layout"], v["bindings"], f"Copia de «{row['name']}»", new_id, original)

    def delete(self, actor: Actor, public_id: str) -> None:
        actor.require("gestion.configuracion")
        with self.db.tx() as conn:
            row = self._row(conn, actor, public_id)
            conn.execute("UPDATE print_templates SET deleted_at = ?, is_default = 0, active = 0, updated_by = ?,"
                         " version = version + 1 WHERE id = ?", (iso(), actor.id, row["id"]))
            record(conn, actor, "plantilla.eliminar", "print_template", row["id"], {"nombre": row["name"]})

    def original(self, actor: Actor, public_id: str) -> tuple[Path, str]:
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            row = self._row(conn, actor, public_id)
        if not row["original_file"]:
            raise NotFoundError("Esta plantilla no se importó de un archivo.")
        return self._dir(public_id) / row["original_file"], row["original_name"] or row["original_file"]

    def add_image(self, actor: Actor, public_id: str, filename: str, content: bytes) -> dict:
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            self._row(conn, actor, public_id)
        if len(content) > MAX_IMAGE:
            raise ValidationError("Imagen demasiado grande.", {"file": "Máximo 3 MB."})
        if Path(filename or "").suffix.lower() not in ("", ".png", ".jpg", ".jpeg"):
            raise ValidationError("Use una imagen JPG o PNG.", {"file": "Extensión no permitida."})
        try:
            if content[:2] == b"\xff\xd8":
                w, h, _, _ = _jpeg_info(content)
                ext = ".jpg"
            elif content[:8] == b"\x89PNG\r\n\x1a\n":
                info, _ = _png_objects(content)
                w, h, ext = info["w"], info["h"], ".png"
            else:
                raise ImageError("formato")
        except (ImageError, ValueError, IndexError):
            raise ValidationError("Use una imagen JPG o PNG (8 bits, sin entrelazado).", {"file": "Imagen no válida."}) from None
        if not (1 <= w <= MAX_IMAGE_PX and 1 <= h <= MAX_IMAGE_PX):
            raise ValidationError(f"La imagen debe medir como máximo {MAX_IMAGE_PX} × {MAX_IMAGE_PX} píxeles.", {"file": "Dimensiones no válidas."})
        name = f"img-{hashlib.sha256(content).hexdigest()[:16]}{ext}"
        (self._dir(public_id) / name).write_bytes(content)
        scale = min(1.0, 200 / max(w, h))           # tamaño inicial razonable (máx. 200 pt)
        return {"file": name, "w": round(w * scale, 2), "h": round(h * scale, 2)}

    def add_company_logo(self, actor: Actor, public_id: str, data_dir: Path) -> dict:
        """Copia el logotipo configurado de la empresa a la plantilla (Gestión › Empresa)."""
        for suffix in (".png", ".jpg", ".jpeg"):
            path = data_dir / f"logo{suffix}"
            if path.is_file():
                return self.add_image(actor, public_id, path.name, path.read_bytes())
        raise ValidationError("La empresa no tiene logotipo. Súbalo en Gestión › Empresa.")

    def template_xlsx(self, actor: Actor, public_id: str) -> tuple[bytes, str]:
        """Plantilla Excel generada desde el diseño: campos como {Nombre del campo} y una fila modelo de productos."""
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            row = self._row(conn, actor, public_id)
            v = self._version(conn, row["id"], row["current_version"])
        compiled, cbind, _ = self._design(v["layout"], v["bindings"])
        final = json.loads(json.dumps(compiled))
        if cbind.get("products"):
            p = cbind["products"]
            labels = {k: lbl for k, (lbl, _) in engine.LINE_FIELDS.items()}
            for letter, b in p["columns"].items():
                ref = f"{letter}{p['start']}"
                final["cells"].setdefault(ref, {})["v"] = "{" + (labels.get(b.get("field", ""), "") or "Valor") + "}"
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", row["name"])[:50] or "plantilla"
        return write_xlsx(final, self._images(public_id, final), row["name"]), f"{name}.xlsx"

    def image(self, actor: Actor, public_id: str, name: str) -> tuple[bytes, str]:
        if not any(actor.can(p) for p in ("gestion.configuracion", "documentos.ver", "ventas.historial")):
            actor.require("gestion.configuracion")
        with self.db.read() as conn:
            self._row(conn, actor, public_id)
        if not re.fullmatch(r"img[-A-Za-z0-9]*\.(jpg|png)", name or ""):
            raise NotFoundError("Imagen no encontrada.")
        path = self._dir(public_id) / name
        if not path.is_file():
            raise NotFoundError("Imagen no encontrada.")
        return path.read_bytes(), "image/png" if name.endswith(".png") else "image/jpeg"

    # ------------------------------------------------------------------ vista previa (demostración)
    def _preview_final(self, actor: Actor, public_id: str, data: dict):
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            row = self._row(conn, actor, public_id)
            v = self._version(conn, row["id"], row["current_version"])
        layout, bindings = v["layout"], v["bindings"]
        if data.get("layout") is not None:
            layout, bindings = self._clean_design(public_id, data["layout"],
                                                  data.get("bindings") if data.get("bindings") is not None else bindings)
        elif data.get("bindings") is not None:
            bindings = self._clean_bindings(data["bindings"])
        compiled, cbind, design_notes = self._design(layout, bindings)
        if data.get("doc_id"):
            with self.db.read() as conn:
                _, header, real_lines = self._doc_data(conn, actor, int(data["doc_id"]))
            demo = engine.DocData(header=header, lines=real_lines, printed_at=self._now_local())
        elif data.get("sale_id"):
            # Vista previa con una venta REAL autorizada: solo lectura, no registra emisión ni toca la venta.
            if not (actor.can("ventas.historial") or actor.can("ventas.vender")):
                actor.require("ventas.historial")
            with self.db.read() as conn:
                _, header, real_lines = self._sale_data(conn, actor, int(data["sale_id"]))
            demo = engine.DocData(header=header, lines=real_lines, printed_at=self._now_local())
        else:
            lines = max(0, min(200, int(data.get("lines") or 3)))
            demo = engine.demo_data(lines, self._now_local())
        try:
            final, totals = engine.render(compiled, cbind, demo)
        except engine.BindingError as exc:
            raise ValidationError("Revise las vinculaciones: " + exc.problems[0], {"bindings": " ".join(exc.problems)}) from None
        return row, final, totals, design_notes

    def preview(self, actor: Actor, public_id: str, data: dict) -> tuple[bytes, dict]:
        """PDF de prueba con datos de demostración claramente identificados. Acepta un diseño sin guardar."""
        row, final, totals, design_notes = self._preview_final(actor, public_id, data)
        pdf, notes = render_pdf(final, self._images(public_id, final), f"Vista previa {row['name']}")
        return pdf, {"pages": page_count(pdf), "notes": design_notes + notes, "totals": {k: str(v) for k, v in totals.items()}}

    def preview_xlsx(self, actor: Actor, public_id: str, data: dict) -> tuple[bytes, str]:
        """Excel de prueba generado con el MISMO diseño final que la vista previa en PDF."""
        row, final, _, _ = self._preview_final(actor, public_id, data)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", row["name"])[:50] or "plantilla"
        return write_xlsx(final, self._images(public_id, final), row["name"]), f"{name}-demostracion.xlsx"

    # ------------------------------------------------------------------ generación real
    def _choose(self, conn, actor: Actor, inventory_id: int | None, kind: str, doc_type: int | None, public_id: str | None):
        if public_id:
            row = self._row(conn, actor, public_id)
            if row["inventory_id"] != inventory_id or row["kind"] != kind or row["document_type_id"] != doc_type:
                raise ValidationError("Esa plantilla no corresponde a este tipo de documento o inventario.")
            if not row["active"]:
                raise ValidationError("La plantilla está inactiva.")
            return row
        return conn.execute("SELECT * FROM print_templates WHERE inventory_id IS ? AND kind = ? AND document_type_id IS ?"
                            " AND is_default = 1 AND active = 1 AND deleted_at IS NULL", (inventory_id, kind, doc_type)).fetchone()

    def has_template(self, conn, inventory_id: int | None, kind: str, doc_type: int | None) -> bool:
        return bool(conn.execute("SELECT 1 FROM print_templates WHERE inventory_id IS ? AND kind = ? AND document_type_id IS ?"
                                 " AND active = 1 AND deleted_at IS NULL", (inventory_id, kind, doc_type)).fetchone())

    def _company(self) -> dict:
        c = self.settings.get("empresa")
        return {"empresa_nombre": c["name"], "empresa_razon_social": c.get("legal_name", ""), "empresa_nit": c["tax_id"],
                "empresa_direccion": c["address"], "empresa_ciudad": c.get("city", ""), "empresa_telefono": c["phone"],
                "empresa_email": c["email"], "empresa_pie": c["document_footer"]}

    @staticmethod
    def _lines(rows) -> list[dict]:
        return [{"cantidad": Decimal(r["qty_milli"]) / 1000, "codigo": r["code"], "descripcion": r["description"], "unidad": "",
                 "precio": _dec(r["unit_price_cents"]), "precio_lista": _dec(r["list_price_cents"]),
                 "descuento_linea": _dec(r["discount_cents"]), "iva_pct": Decimal(r["tax_rate_bp"]) / 100} for r in rows]

    def _doc_data(self, conn, actor: Actor, doc_id: int):
        """Datos REALES de un documento comercial (solo lectura). Los datos que falten quedan vacíos."""
        actor.require("documentos.ver")
        doc = conn.execute("SELECT d.*, t.name AS type_name, t.printer AS type_printer, u.full_name AS user_name"
                           " FROM commercial_documents d JOIN document_types t ON t.id = d.type_id"
                           " JOIN users u ON u.id = d.user_id WHERE d.id = ?", (doc_id,)).fetchone()
        if not doc:
            raise NotFoundError("Documento no encontrado.")
        self.scopes.check(conn, actor, doc["inventory_id"], "Documento")
        lines = self._lines(conn.execute("SELECT * FROM commercial_document_lines WHERE document_id = ? ORDER BY line_no",
                                         (doc_id,)).fetchall())
        header = {**self._company(), "tipo_documento": doc["type_name"].upper(), "numero": doc["number"],
                  "fecha": parse_date(doc["doc_date"]), "valido_hasta": parse_date(doc["valid_until"]) if doc["valid_until"] else "",
                  "cliente_nombre": doc["customer_name"], "cliente_identificacion": doc["customer_identification"],
                  "cliente_tipo_documento": _id_type(doc["customer_identification"]),
                  "cliente_direccion": doc["customer_address"], "cliente_telefono": doc["customer_phone"],
                  "cliente_email": doc["customer_email"], "vendedor": doc["user_name"], "observaciones": doc["notes"],
                  "metodo_pago": "", "iva_incluido": _dec(doc["tax_cents"])}
        return doc, header, lines

    def document_template(self, actor: Actor, doc_id: int) -> dict | None:
        """Plantilla de impresión predeterminada (activa) del documento, o None si el tipo no tiene."""
        with self.db.read() as conn:
            doc, _, _ = self._doc_data(conn, actor, doc_id)
            row = self._choose(conn, actor, doc["inventory_id"], "documento", doc["type_id"], None)
        if not row:
            return None
        return {"public_id": row["public_id"], "name": row["name"], "printer": self.resolve_printer(None, row["printer"],
                                                                                                    doc["type_printer"])}

    def document_preview(self, actor: Actor, doc_id: int, public_id: str | None = None) -> tuple[bytes, dict]:
        """Vista previa en PDF del documento con su plantilla. Solo lectura: no registra emisión."""
        with self.db.read() as conn:
            doc, header, lines = self._doc_data(conn, actor, doc_id)
            row = self._choose(conn, actor, doc["inventory_id"], "documento", doc["type_id"], public_id)
            if not row:
                raise ValidationError(f"El tipo «{doc['type_name']}» no tiene una plantilla de impresión predeterminada.")
            v = self._version(conn, row["id"], row["current_version"])
        compiled, cbind, _ = self._design(v["layout"], v["bindings"])
        final, _ = engine.render(compiled, cbind, engine.DocData(header=header, lines=lines, printed_at=self._now_local()))
        pdf, notes = render_pdf(final, self._images(row["public_id"], final), f"{doc['type_name']} {doc['number']}")
        return pdf, {"pages": page_count(pdf), "notes": notes}

    def render_document(self, actor: Actor, doc_id: int, public_id: str | None = None, *, required: bool = True,
                        fmt: str = "pdf", printer: str | None = None, copies: int = 1) -> dict | None:
        """PDF, Excel o impresión directa de una cotización, orden u otro documento con su plantilla."""
        if fmt == "print":
            actor.require("documentos.imprimir")
        with self.db.read() as conn:
            doc, header, lines = self._doc_data(conn, actor, doc_id)
            row = self._choose(conn, actor, doc["inventory_id"], "documento", doc["type_id"], public_id)
            if not row:
                if required:
                    raise ValidationError(f"El tipo «{doc['type_name']}» no tiene una plantilla de impresión predeterminada.")
                return None
            v = self._version(conn, row["id"], row["current_version"])
        target = self.resolve_printer(printer, row["printer"], doc["type_printer"]) if fmt == "print" else None
        return self._emit(actor, row, v, "documento", doc_id, f"{doc['type_name']}-{doc['number']}", header, lines, fmt,
                          printer=target, copies=copies)

    def _sale_data(self, conn, actor: Actor, sale_id: int):
        """Datos REALES de una venta (solo lectura). Valida inventario y permisos de quien la consulta."""
        sale = conn.execute("SELECT s.*, u.full_name AS user_name FROM sales s JOIN users u ON u.id = s.user_id"
                            " WHERE s.id = ?", (sale_id,)).fetchone()
        if not sale:
            raise NotFoundError("Venta no encontrada.")
        self.scopes.check(conn, actor, sale["inventory_id"], "Venta")
        if not actor.can("ventas.historial") and sale["user_id"] != actor.id:
            actor.require("ventas.historial")
        lines = self._lines(conn.execute("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY line_no", (sale_id,)).fetchall())
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (sale["customer_id"],)).fetchone() if sale["customer_id"] else None
        methods = ", ".join(r[0] for r in conn.execute(
            "SELECT DISTINCT m.name FROM sale_payments p JOIN payment_methods m ON m.id = p.method_id WHERE p.sale_id = ?"
            " ORDER BY m.sort_order", (sale_id,)))
        header = {**self._company(), "tipo_documento": "VENTA" + (" ANULADA" if sale["status"] == "anulada" else ""),
                  "numero": sale["number"], "fecha": parse_date(sale["sale_date"]), "valido_hasta": "",
                  "cliente_nombre": sale["customer_name"], "cliente_identificacion": sale["customer_identification"],
                  "cliente_tipo_documento": _id_type(sale["customer_identification"]),
                  "cliente_direccion": customer["address"] if customer else "", "cliente_telefono": customer["phone"] if customer else "",
                  "cliente_email": customer["email"] if customer else "", "vendedor": sale["user_name"], "observaciones": sale["notes"],
                  "metodo_pago": methods, "iva_incluido": _dec(sale["tax_cents"])}
        return sale, header, lines

    def render_sale(self, actor: Actor, sale_id: int, public_id: str | None = None, kind: str = "venta",
                    fmt: str = "pdf", printer: str | None = None, copies: int = 1) -> dict:
        if not (actor.can("ventas.historial") or actor.can("ventas.vender")):
            actor.require("ventas.historial")
        if kind not in ("venta", "recibo"):
            raise ValidationError("Tipo de plantilla no válido.")
        with self.db.read() as conn:
            sale, header, lines = self._sale_data(conn, actor, sale_id)
            row = self._choose(conn, actor, sale["inventory_id"], kind, None, public_id)
            if not row:
                raise ValidationError(f"No hay una plantilla de {KINDS[kind].lower()} predeterminada para este inventario.")
            v = self._version(conn, row["id"], row["current_version"])
        target = self.resolve_printer(printer, row["printer"]) if fmt == "print" else None
        return self._emit(actor, row, v, "venta", sale_id, f"venta-{sale['number']}", header, lines, fmt,
                          printer=target, copies=copies)

    def sale_template(self, actor: Actor, sale_id: int, kind: str) -> dict | None:
        """Plantilla predeterminada (activa) de venta o recibo para el inventario de la venta, o None."""
        with self.db.read() as conn:
            sale, _, _ = self._sale_data(conn, actor, sale_id)
            row = self._choose(conn, actor, sale["inventory_id"], kind, None, None)
        if not row:
            return None
        return {"public_id": row["public_id"], "name": row["name"], "printer": self.resolve_printer(None, row["printer"])}

    def resolve_printer(self, explicit: str | None, template_printer: str = "", type_printer: str = "") -> str:
        """Impresora a usar: la elegida → la de la plantilla → la del tipo de documento → la predeterminada de
        Configuración › Impresión → la predeterminada de Windows."""
        for name in (explicit, template_printer, type_printer, self.settings.get("impresion").get("default_printer")):
            if name and str(name).strip():
                return str(name).strip()
        info = list_printers()
        if info.get("default"):
            return info["default"]
        raise PrintError("No hay impresora predeterminada. Elija una en Gestión › Configuración › Impresión.")

    def _emit(self, actor: Actor, row, v: dict, target_type: str, target_id: int, label: str, header: dict,
              lines: list[dict], fmt: str = "pdf", printer: str | None = None, copies: int = 1) -> dict:
        data = engine.DocData(header=header, lines=lines, printed_at=self._now_local())
        compiled, cbind, _ = self._design(v["layout"], v["bindings"])
        try:
            final, totals = engine.render(compiled, cbind, data)
        except engine.BindingError as exc:
            raise ValidationError("La plantilla tiene vinculaciones con errores: " + exc.problems[0]) from None
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:60]
        if fmt == "xlsx":                       # Excel real del documento con el mismo diseño final que el PDF
            xlsx = write_xlsx(final, self._images(row["public_id"], final), label)
            with self.db.tx() as conn:
                record(conn, actor, "plantilla.excel", target_type, target_id, {"plantilla": row["name"], "version": v["number"]})
            return {"xlsx": xlsx, "file_name": f"{safe}.xlsx", "template": row["name"], "version": v["number"]}
        pdf, notes = render_pdf(final, self._images(row["public_id"], final), label)
        stamp = data.printed_at.strftime("%Y%m%d-%H%M%S")
        folder = self.output_dir / data.printed_at.strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe}-{stamp}-{secrets.token_hex(3)}.pdf"
        path.write_bytes(pdf)
        snapshot = json.dumps({"header": header, "lines": lines, "printed_at": data.printed_at,
                               "totals": totals}, default=_json_default, ensure_ascii=False)
        pages = page_count(pdf)
        with self.db.tx() as conn:
            out_id = conn.execute(
                "INSERT INTO print_outputs(template_version_id, target_type, target_id, file_name, sha256, pages, data, user_id,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (v["id"], target_type, target_id, f"{path.parent.name}/{path.name}", hashlib.sha256(pdf).hexdigest(), pages,
                 snapshot, actor.id, iso())).lastrowid
            record(conn, actor, "plantilla.emitir", target_type, target_id,
                   {"plantilla": row["name"], "version": v["number"], "paginas": pages, "salida": out_id})
        result = {"path": path, "output_id": out_id, "pages": pages, "notes": notes, "template": row["name"],
                  "version": v["number"], "totals": {k: str(x) for k, x in totals.items()}}
        if fmt == "print":
            # Impresión directa en la impresora de Windows (sin Excel ni visor de PDF), con el mismo diseño del PDF.
            from ..printing.gdi import print_layout
            copies = max(1, min(20, int(copies or 1)))
            error = None
            try:
                printed = print_layout(final, self._images(row["public_id"], final), printer or "", copies, label)
                result.update(printed=True, printer=printed["printer"], copies=copies)
            except PrintError as exc:
                error = exc.detail
            with self.db.tx() as conn:
                conn.execute("INSERT INTO print_jobs(created_at, user_id, target_type, target_id, target_label, printer, mode,"
                             " copies, status, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (iso(), actor.id, target_type, target_id, label[:80], printer or "", "directa", copies,
                              "error" if error else "ok", error))
                record(conn, actor, "plantilla.imprimir", target_type, target_id,
                       {"plantilla": row["name"], "impresora": printer, "copias": copies, "error": error})
            if error:
                raise PrintError(error)
        return result

    def outputs(self, actor: Actor, target_type: str, target_id: int) -> list[dict]:
        if target_type == "documento":
            actor.require("documentos.ver")
        else:
            actor.require("ventas.historial")
        with self.db.read() as conn:
            table = "commercial_documents" if target_type == "documento" else "sales"
            target = conn.execute(f"SELECT inventory_id FROM {table} WHERE id = ?", (target_id,)).fetchone()  # noqa: S608 - tabla fija
            if not target:
                raise NotFoundError("Operación no encontrada.")
            self.scopes.check(conn, actor, target["inventory_id"], "Operación")
            return [dict(r) for r in conn.execute(
                "SELECT o.id, o.pages, o.created_at, t.name AS template_name, v.number AS template_version, u.full_name AS user_name"
                " FROM print_outputs o JOIN print_template_versions v ON v.id = o.template_version_id"
                " JOIN print_templates t ON t.id = v.template_id LEFT JOIN users u ON u.id = o.user_id"
                " WHERE o.target_type = ? AND o.target_id = ? ORDER BY o.id DESC", (target_type, target_id))]

    def output_file(self, actor: Actor, output_id: int) -> Path:
        with self.db.read() as conn:
            o = conn.execute("SELECT * FROM print_outputs WHERE id = ?", (output_id,)).fetchone()
        if not o:
            raise NotFoundError("Documento emitido no encontrado.")
        self.outputs(actor, o["target_type"], o["target_id"])   # valida permisos e inventario
        path = (self.output_dir / o["file_name"]).resolve()
        if self.output_dir.resolve() not in path.parents or not path.is_file():
            raise NotFoundError("El archivo del documento emitido no está disponible.")
        return path


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
