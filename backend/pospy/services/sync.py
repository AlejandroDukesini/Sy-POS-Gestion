"""Conexiones de inventario, importación con vista previa y conciliación.

Autoridad sobre las existencias (regla explícita):
  * POS-PY es la autoridad por defecto. Su existencia es la suma de movimientos y nunca se
    sobrescribe con un número externo.
  * Una fuente externa puede declararse «fuente maestra». Solo entonces, y solo si su política de
    existencias es «ajustar», las diferencias se aplican como movimientos de CONCILIACIÓN (con su
    asiento contable y en la auditoría), conservando todo el historial local.
  * Con la política «informar», las diferencias de existencias solo se reportan como conflictos.
  * El costo de productos existentes no se toma de la fuente externa: lo mantiene el costo promedio
    de los movimientos locales (se informa la diferencia).

Toda importación pasa por una vista previa que queda guardada (archivo y huella SHA-256). Aplicar
exige que el archivo sea exactamente el revisado; si la fuente cambió, hay que generar otra vista
previa. Una importación manual de archivo es eso, una importación: no crea sincronización automática.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as pysecrets
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

from ..core.actor import SYSTEM, Actor
from ..core.audit import record
from ..core.clock import iso, now_utc, parse_iso
from ..core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from ..core.money import from_cents, from_milli, to_bp, to_cents, to_milli
from ..integrations import tabular
from ..integrations.sources import ADAPTERS, PROVIDER_LABELS, OAuthAdapter, SourceFile
from .inventory import UNITS, InventoryService

log = logging.getLogger("pospy.sync")
DETAIL_LIMIT = 1000


class SyncService:
    def __init__(self, db, settings, secrets, inventory: InventoryService, imports_dir: Path):
        self.db = db
        self.settings = settings
        self.secrets = secrets
        self.inventory = inventory
        self.imports_dir = Path(imports_dir)
        self._pending_oauth: dict[str, dict] = {}
        self._oauth_lock = threading.Lock()

    # ------------------------------------------------------------------ conexiones
    def _row(self, conn: sqlite3.Connection, connection_id: int) -> dict:
        row = conn.execute("SELECT * FROM integration_connections WHERE id = ?", (connection_id,)).fetchone()
        if not row:
            raise NotFoundError("Conexión no encontrada.")
        c = dict(row)
        c["config"] = json.loads(c["config"] or "{}")
        return c

    def _adapter(self, connection: dict):
        return ADAPTERS[connection["provider"]](connection, self.secrets, self.settings, self.db)

    def _public(self, c: dict) -> dict:
        adapter = self._adapter(c)
        c["provider_label"] = PROVIDER_LABELS[c["provider"]]
        c["needs_oauth"] = adapter.needs_oauth
        c["authorized"] = self.secrets.has(adapter.secret_name) if adapter.needs_oauth else None
        c["source"] = adapter.describe()
        return c

    def connections(self, actor: Actor) -> list[dict]:
        actor.require("gestion.integraciones")
        with self.db.read() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM integration_connections ORDER BY name")]
            return [self._public(self._row(conn, i)) for i in ids]

    def get(self, actor: Actor, connection_id: int) -> dict:
        actor.require("gestion.integraciones")
        with self.db.read() as conn:
            c = self._public(self._row(conn, connection_id))
            c["runs"] = [self._run_public(dict(r)) for r in conn.execute(
                "SELECT r.*, u.username FROM sync_runs r LEFT JOIN users u ON u.id = r.user_id WHERE connection_id = ?"
                " ORDER BY r.id DESC LIMIT 20", (connection_id,))]
        return c

    def save(self, actor: Actor, data: dict, connection_id: int | None = None) -> dict:
        actor.require("gestion.integraciones")
        name = (data.get("name") or "").strip()[:80]
        if not name:
            raise ValidationError("Escriba un nombre para la conexión.", {"name": "Nombre obligatorio."})
        provider = data.get("provider")
        if provider not in ADAPTERS:
            raise ValidationError("Proveedor no válido.", {"provider": "Elija el tipo de fuente."})
        allowed = {"path", "folder", "pattern", "item_path", "file_id", "sheet", "header_row", "columns"}
        config = {k: v for k, v in (data.get("config") or {}).items() if k in allowed}
        if "columns" in config:
            config["columns"] = {k: str(v) for k, v in (config["columns"] or {}).items() if k in tabular.FIELDS and v}
        try:
            config["header_row"] = int(config.get("header_row") or 0)
        except (TypeError, ValueError):
            raise ValidationError("Fila de encabezados no válida.", {"header_row": "Número entero."}) from None
        values = {
            "name": name, "provider": provider, "config": json.dumps(config, ensure_ascii=False),
            "is_master": int(bool(data.get("is_master"))),
            "sync_mode": data.get("sync_mode") if data.get("sync_mode") in ("manual", "intervalo") else "manual",
            "sync_interval_min": int(data.get("sync_interval_min") or 60),
            "stock_policy": data.get("stock_policy") if data.get("stock_policy") in ("informar", "ajustar") else "informar",
            "update_catalog": int(bool(data.get("update_catalog", True))),
            "create_missing": int(bool(data.get("create_missing", True))),
            "active": int(bool(data.get("active", True))),
        }
        if not 5 <= values["sync_interval_min"] <= 1440:
            raise ValidationError("Intervalo no válido.", {"sync_interval_min": "Entre 5 y 1440 minutos."})
        if values["stock_policy"] == "ajustar" and not values["is_master"]:
            raise ValidationError("Solo una fuente maestra puede ajustar existencias.",
                                  {"stock_policy": "Marque la conexión como fuente maestra o use «informar»."})
        self._adapter({"id": connection_id or 0, "provider": provider, "config": config}).validate_config()
        with self.db.tx() as conn:
            if conn.execute("SELECT 1 FROM integration_connections WHERE name = ? AND id IS NOT ?", (name, connection_id)).fetchone():
                raise ConflictError("Ya existe una conexión con ese nombre.", {"name": "Nombre repetido."})
            if values["is_master"]:
                conn.execute("UPDATE integration_connections SET is_master = 0, stock_policy = 'informar' WHERE id IS NOT ?",
                             (connection_id,))
            now = iso()
            if connection_id is None:
                cols = ", ".join(values)
                connection_id = conn.execute(f"INSERT INTO integration_connections({cols}, created_at, updated_at)"
                                             f" VALUES ({', '.join('?' * len(values))}, ?, ?)",
                                             (*values.values(), now, now)).lastrowid
                record(conn, actor, "integracion.crear", "integration", connection_id, {"nombre": name, "proveedor": provider})
            else:
                current = self._row(conn, connection_id)
                if current["provider"] != provider:
                    raise ValidationError("No se puede cambiar el proveedor de una conexión; cree una nueva.")
                if "version" in data and int(data["version"]) != current["version"]:
                    raise ConflictError("Otra persona modificó esta conexión. Recargue y vuelva a intentarlo.")
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE integration_connections SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",
                             (*values.values(), now, connection_id))
                record(conn, actor, "integracion.actualizar", "integration", connection_id,
                       {k: v for k, v in values.items() if k != "config"} | {"config": config})
        return self.get(actor, connection_id)

    def deactivate(self, actor: Actor, connection_id: int) -> dict:
        actor.require("gestion.integraciones")
        with self.db.tx() as conn:
            c = self._row(conn, connection_id)
            conn.execute("UPDATE integration_connections SET active = 0, is_master = 0, stock_policy = 'informar',"
                         " sync_mode = 'manual', updated_at = ? WHERE id = ?", (iso(), connection_id))
            if c["provider"] in ("onedrive", "gdrive"):
                self.secrets.delete(conn, f"integration.{connection_id}.oauth")
            record(conn, actor, "integracion.desactivar", "integration", connection_id, {"nombre": c["name"]})
        return self.get(actor, connection_id)

    # ------------------------------------------------------------------ credenciales OAuth del proveedor
    def oauth_credentials_status(self, actor: Actor) -> dict:
        actor.require("gestion.integraciones")
        o = self.settings.get("oauth")
        return {"microsoft_client_id": o["microsoft_client_id"], "microsoft_tenant": o["microsoft_tenant"],
                "google_client_id": o["google_client_id"], "google_client_secret_set": self.secrets.has("oauth.google_client_secret")}

    def set_google_secret(self, actor: Actor, secret: str) -> None:
        actor.require("gestion.integraciones")
        secret = (secret or "").strip()
        with self.db.tx() as conn:
            if secret:
                self.secrets.set(conn, "oauth.google_client_secret", secret)
            else:
                self.secrets.delete(conn, "oauth.google_client_secret")
            record(conn, actor, "integracion.secreto_google", "settings", "oauth", {"configurado": bool(secret)})

    def oauth_start(self, actor: Actor, connection_id: int, base_url: str) -> dict:
        actor.require("gestion.integraciones")
        with self.db.read() as conn:
            c = self._row(conn, connection_id)
        adapter = self._adapter(c)
        if not isinstance(adapter, OAuthAdapter):
            raise ValidationError("Esta conexión no usa autorización en línea.")
        port = base_url.rstrip("/").rsplit(":", 1)[-1] if base_url.count(":") >= 2 else "80"
        redirect_uri = f"http://{adapter.redirect_host}:{port}/api/integrations/oauth/callback"
        verifier = pysecrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = pysecrets.token_urlsafe(24)
        client = adapter.client()
        params = {"client_id": client["client_id"], "response_type": "code", "redirect_uri": redirect_uri,
                  "scope": adapter.scopes, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                  **adapter.extra_authorize_params()}
        with self._oauth_lock:
            now = time.time()
            self._pending_oauth = {k: v for k, v in self._pending_oauth.items() if v["expires"] > now}
            self._pending_oauth[state] = {"connection_id": connection_id, "verifier": verifier, "redirect_uri": redirect_uri,
                                          "expires": now + 600, "user_id": actor.id, "username": actor.username}
        return {"authorize_url": f"{adapter.authorize_endpoint()}?{urlencode(params)}", "redirect_uri": redirect_uri}

    def oauth_callback(self, state: str, code: str | None, error: str | None) -> int:
        with self._oauth_lock:
            pending = self._pending_oauth.pop(state or "", None)
        if not pending or pending["expires"] < time.time():
            raise ValidationError("La solicitud de autorización expiró o no es válida. Inicie la autorización de nuevo.")
        if error or not code:
            raise ValidationError(f"El proveedor no autorizó el acceso ({error or 'sin código'}).")
        with self.db.read() as conn:
            c = self._row(conn, pending["connection_id"])
        adapter = self._adapter(c)
        tokens = adapter.exchange(code, pending["verifier"], pending["redirect_uri"])
        actor = Actor(pending["user_id"], pending["username"], "admin")
        with self.db.tx() as conn:
            self.secrets.set(conn, adapter.secret_name, json.dumps(tokens))
            record(conn, actor, "integracion.autorizada", "integration", c["id"], {"proveedor": c["provider"]})
        return c["id"]

    def test(self, actor: Actor, connection_id: int) -> dict:
        actor.require("gestion.integraciones")
        with self.db.read() as conn:
            c = self._row(conn, connection_id)
        started = time.monotonic()
        try:
            source = self._adapter(c).fetch()
            table = tabular.read_table(source.content, source.name, c["config"].get("sheet", ""),
                                       int(c["config"].get("header_row") or 0))
        except DomainError as exc:
            return {"ok": False, "message": exc.detail}
        return {"ok": True, "message": f"Conexión correcta: {source.name}, {len(table.rows)} filas.",
                "file": source.name, "modified": source.modified, "sheets": table.sheets, "sheet": table.sheet,
                "header_row": table.header_row, "headers": table.headers,
                "suggested_columns": tabular.suggest_columns(table.headers),
                "sample": [[_cell(v) for v in row] for row in table.rows[:8]],
                "elapsed_ms": int((time.monotonic() - started) * 1000)}

    # ------------------------------------------------------------------ vista previa
    def inspect_upload(self, actor: Actor, filename: str, content: bytes, sheet: str = "", header_row: int = 0) -> dict:
        actor.require("inventario.importar")
        table = tabular.read_table(content, filename, sheet, header_row)
        return {"file": filename, "sheets": table.sheets, "sheet": table.sheet, "header_row": table.header_row,
                "headers": table.headers, "suggested_columns": tabular.suggest_columns(table.headers),
                "sample": [[_cell(v) for v in row] for row in table.rows[:8]], "rows": len(table.rows),
                "fields": tabular.FIELDS, "required": list(tabular.REQUIRED)}

    def preview_upload(self, actor: Actor, filename: str, content: bytes, options: dict) -> dict:
        actor.require("inventario.importar")
        if not actor.can("inventario.editar"):
            actor.require("inventario.editar")
        opts = {"sheet": options.get("sheet", ""), "header_row": int(options.get("header_row") or 0),
                "columns": options.get("columns") or {}, "create_missing": bool(options.get("create_missing", True)),
                "update_catalog": bool(options.get("update_catalog", True)),
                "adjust_stock": bool(options.get("adjust_stock", False))}
        if opts["adjust_stock"]:
            actor.require("inventario.movimientos")
        return self._preview(actor, None, SourceFile(Path(filename).name, content), opts, "archivo",
                             f"Archivo {Path(filename).name}")

    def preview_connection(self, actor: Actor, connection_id: int, trigger: str = "manual") -> dict:
        if actor is not SYSTEM:
            actor.require("gestion.integraciones")
        with self.db.read() as conn:
            c = self._row(conn, connection_id)
        if not c["active"]:
            raise ValidationError("La conexión está desactivada.")
        try:
            source = self._adapter(c).fetch()
        except DomainError as exc:
            self._mark(connection_id, "error", exc.detail)
            raise
        opts = {"sheet": c["config"].get("sheet", ""), "header_row": int(c["config"].get("header_row") or 0),
                "columns": c["config"].get("columns") or {}, "create_missing": bool(c["create_missing"]),
                "update_catalog": bool(c["update_catalog"]),
                "adjust_stock": bool(c["is_master"]) and c["stock_policy"] == "ajustar"}
        return self._preview(actor, c, source, opts, trigger, c["name"])

    def _preview(self, actor: Actor, connection: dict | None, source: SourceFile, opts: dict, trigger: str,
                 label: str) -> dict:
        table = tabular.read_table(source.content, source.name, opts["sheet"], opts["header_row"])
        columns = opts["columns"] or tabular.suggest_columns(table.headers)
        records = tabular.to_records(table, columns)
        with self.db.read() as conn:
            diff = self._diff(conn, records, opts)
        summary = {"file": source.name, "modified": source.modified, "sheet": table.sheet, "header_row": table.header_row,
                   "columns": columns, "options": opts, **diff}
        with self.db.tx() as conn:
            run_id = conn.execute("INSERT INTO sync_runs(connection_id, source_label, started_at, status, trigger,"
                                  " source_sha256, summary, user_id) VALUES (?,?,?,?,?,?,?,?)",
                                  (connection["id"] if connection else None, label, iso(), "vista_previa", trigger,
                                   source.sha256, json.dumps(summary, ensure_ascii=False, default=str), actor.id)).lastrowid
        suffix = Path(source.name).suffix.lower() or ".xlsx"
        (self.imports_dir / f"run-{run_id}{suffix}").write_bytes(source.content)
        return self.run(actor, run_id)

    def _diff(self, conn: sqlite3.Connection, records: list[tabular.Record], opts: dict) -> dict:
        counts = Counter(r.code.lower() for r in records if r.code)
        new, changes, stock_diff, cost_diff, invalid, duplicates, unchanged = [], [], [], [], [], [], 0
        for rec in records:
            if rec.errors:
                invalid.append({"row": rec.row, "code": rec.code, "errors": rec.errors})
                continue
            if counts[rec.code.lower()] > 1:
                duplicates.append({"row": rec.row, "code": rec.code})
                continue
            v = rec.values
            product = conn.execute("SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c"
                                   " ON c.id = p.category_id WHERE p.code = ?", (rec.code,)).fetchone()
            if v.get("unit") and v["unit"] not in UNITS:
                invalid.append({"row": rec.row, "code": rec.code, "errors": [f"Unidad «{v['unit']}» no reconocida."]})
                continue
            if product is None:
                new.append({"row": rec.row, "code": rec.code, "description": v["description"],
                            "price": str(v["price"]), "stock": str(v.get("stock", 0))})
                continue
            fields = {}
            compare = {"description": (product["description"], v.get("description")),
                       "price": (str(from_cents(product["price_cents"])), _money(v.get("price"))),
                       "discount_price": (str(from_cents(product["discount_price_cents"]))
                                          if product["discount_price_cents"] is not None else None,
                                          _money(v.get("discount_price")) if "discount_price" in v else "__omit__"),
                       "min_stock": (str(from_milli(product["min_stock_milli"])),
                                     str(from_milli(to_milli(v["min_stock"]))) if "min_stock" in v else "__omit__"),
                       "tax_rate": (str(product["tax_rate_bp"] / 100), str(to_bp(v["tax_rate"]) / 100)
                                    if "tax_rate" in v else "__omit__"),
                       "category": (product["category"], v.get("category", "__omit__"))}
            for key, (old, newv) in compare.items():
                if newv != "__omit__" and newv is not None and str(old) != str(newv):
                    fields[key] = {"antes": old, "despues": newv}
            if fields:
                changes.append({"row": rec.row, "code": rec.code, "product_id": product["id"], "fields": fields})
            stock_changed = False
            if "stock" in v:
                external = to_milli(v["stock"])
                if external != product["stock_milli"]:
                    stock_changed = True
                    stock_diff.append({"row": rec.row, "code": rec.code, "product_id": product["id"],
                                       "local": str(from_milli(product["stock_milli"])),
                                       "external": str(from_milli(external)),
                                       "difference": str(from_milli(external - product["stock_milli"]))})
            if "cost" in v and to_cents(v["cost"]) != product["cost_cents"]:
                cost_diff.append({"row": rec.row, "code": rec.code, "local": str(from_cents(product["cost_cents"])),
                                  "external": _money(v["cost"])})
            if not fields and not stock_changed:
                unchanged += 1
        return {
            "counts": {"rows": len(records), "new": len(new), "changes": len(changes), "stock_differences": len(stock_diff),
                       "cost_differences": len(cost_diff), "invalid": len(invalid), "duplicates": len(duplicates),
                       "unchanged": unchanged},
            "new": new[:DETAIL_LIMIT], "changes": changes[:DETAIL_LIMIT], "stock_differences": stock_diff[:DETAIL_LIMIT],
            "cost_differences": cost_diff[:DETAIL_LIMIT], "invalid": invalid[:DETAIL_LIMIT],
            "duplicates": duplicates[:DETAIL_LIMIT],
            "will": {"create": opts["create_missing"], "update_catalog": opts["update_catalog"],
                     "adjust_stock": opts["adjust_stock"]},
        }

    def runs(self, actor: Actor, limit: int = 50) -> list[dict]:
        if not (actor.can("gestion.integraciones") or actor.can("inventario.importar")):
            actor.require("inventario.importar")
        with self.db.read() as conn:
            return [self._run_public(dict(r), brief=True) for r in conn.execute(
                "SELECT r.*, u.username FROM sync_runs r LEFT JOIN users u ON u.id = r.user_id ORDER BY r.id DESC LIMIT ?",
                (min(200, limit),))]

    def run(self, actor: Actor, run_id: int) -> dict:
        if not (actor.can("gestion.integraciones") or actor.can("inventario.importar")):
            actor.require("inventario.importar")
        with self.db.read() as conn:
            row = conn.execute("SELECT r.*, u.username FROM sync_runs r LEFT JOIN users u ON u.id = r.user_id WHERE r.id = ?",
                               (run_id,)).fetchone()
        if not row:
            raise NotFoundError("Proceso de importación no encontrado.")
        return self._run_public(dict(row))

    @staticmethod
    def _run_public(r: dict, brief: bool = False) -> dict:
        r["summary"] = json.loads(r["summary"] or "{}")
        if brief:
            r["summary"] = {k: r["summary"].get(k) for k in ("file", "counts", "applied", "error")}
        return r

    # ------------------------------------------------------------------ aplicar
    def apply(self, actor: Actor, run_id: int) -> dict:
        with self.db.read() as conn:
            run = conn.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            raise NotFoundError("Proceso de importación no encontrado.")
        if actor is not SYSTEM:
            actor.require("gestion.integraciones" if run["connection_id"] else "inventario.importar")
        if run["status"] != "vista_previa":
            raise ValidationError("Esta vista previa ya fue aplicada o descartada. Genere otra.")
        summary = json.loads(run["summary"])
        opts = summary["options"]
        if opts.get("create_missing") or opts.get("update_catalog"):
            if actor is not SYSTEM:
                actor.require("inventario.editar")
        files = list(self.imports_dir.glob(f"run-{run_id}.*"))
        if not files:
            raise ValidationError("No se encuentra el archivo de la vista previa. Genere otra.")
        content = files[0].read_bytes()
        if hashlib.sha256(content).hexdigest() != run["source_sha256"]:
            raise ValidationError("El archivo cambió desde la vista previa. Genere otra vista previa.")
        if run["connection_id"]:
            # Si la fuente cambió desde la vista previa, no se aplica: se exige revisar de nuevo.
            with self.db.read() as conn:
                c = self._row(conn, run["connection_id"])
            current = self._adapter(c).fetch()
            if current.sha256 != run["source_sha256"]:
                raise ValidationError("La fuente cambió desde la vista previa. Genere otra vista previa antes de aplicar.")
        table = tabular.read_table(content, summary["file"], summary["sheet"], summary["header_row"])
        records = tabular.to_records(table, summary["columns"])
        counts = Counter(r.code.lower() for r in records if r.code)
        applied = {"created": 0, "updated": 0, "stock_adjusted": 0, "stock_reported": 0, "skipped": 0, "errors": []}
        label = run["source_label"] or summary["file"]
        with self.db.tx() as conn:
            for rec in records:
                if rec.errors or counts[rec.code.lower()] > 1:
                    applied["skipped"] += 1
                    continue
                try:
                    conn.execute("SAVEPOINT fila")
                    self._apply_record(conn, actor, rec, opts, label, applied)
                    conn.execute("RELEASE fila")
                except DomainError as exc:
                    conn.execute("ROLLBACK TO fila")
                    conn.execute("RELEASE fila")
                    applied["errors"].append({"row": rec.row, "code": rec.code, "error": exc.detail,
                                              "fields": exc.fields})
            summary["applied"] = applied
            conn.execute("UPDATE sync_runs SET status = 'aplicada', finished_at = ?, summary = ? WHERE id = ?",
                         (iso(), json.dumps(summary, ensure_ascii=False, default=str), run_id))
            if run["connection_id"]:
                msg = (f"{applied['created']} nuevos, {applied['updated']} actualizados, {applied['stock_adjusted']} ajustes,"
                       f" {applied['stock_reported']} diferencias informadas, {len(applied['errors'])} errores")
                conn.execute("UPDATE integration_connections SET last_sync_at = ?, last_status = ?, last_message = ? WHERE id = ?",
                             (iso(), "ok" if not applied["errors"] else "con_errores", msg, run["connection_id"]))
            record(conn, actor, "inventario.importacion_aplicada", "sync_run", run_id,
                   {"fuente": label, **{k: v for k, v in applied.items() if k != "errors"}, "errores": len(applied["errors"])})
        return self.run(actor, run_id)

    def _apply_record(self, conn: sqlite3.Connection, actor: Actor, rec: tabular.Record, opts: dict, label: str,
                      applied: dict) -> None:
        v = rec.values
        product = conn.execute("SELECT * FROM products WHERE code = ?", (rec.code,)).fetchone()
        category_id = self._category(conn, v["category"]) if v.get("category") else None
        if product is None:
            if not opts["create_missing"]:
                applied["skipped"] += 1
                return
            data = {"code": rec.code, "description": v["description"], "price": v["price"],
                    "discount_price": v.get("discount_price"), "cost": v.get("cost", 0), "tax_rate": v.get("tax_rate", 0),
                    "min_stock": v.get("min_stock"), "unit": v.get("unit") or "und", "category_id": category_id}
            pid = self.inventory.create_conn(conn, actor, data)
            stock = v.get("stock")
            if stock is not None and stock > 0:
                p = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
                self.inventory._entry(conn, actor, p, to_milli(stock), p["cost_cents"], f"Existencia inicial importada de {label}",
                                      "inventario_inicial", {}, None, kind="inicial")
            elif stock is not None and stock < 0:
                applied["errors"].append({"row": rec.row, "code": rec.code,
                                          "error": "Producto creado sin existencia: la fuente indica cantidad negativa."})
            applied["created"] += 1
            return
        if opts["update_catalog"]:
            data = {"description": v["description"], "price": v["price"]}
            for key in ("discount_price", "min_stock", "tax_rate", "unit"):
                if key in v:
                    data[key] = v[key]
            if category_id:
                data["category_id"] = category_id
            if self.inventory.update_conn(conn, actor, product["id"], data):
                applied["updated"] += 1
        if "stock" in v:
            product = conn.execute("SELECT * FROM products WHERE id = ?", (product["id"],)).fetchone()
            delta = to_milli(v["stock"]) - product["stock_milli"]
            if delta:
                if opts["adjust_stock"]:
                    self.inventory._adjust(conn, actor, product, delta, f"Conciliación con {label}", None, kind="conciliacion")
                    applied["stock_adjusted"] += 1
                else:
                    applied["stock_reported"] += 1

    def _category(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
        now = iso()
        return conn.execute("INSERT INTO categories(name, created_at, updated_at) VALUES (?,?,?)", (name, now, now)).lastrowid

    def discard(self, actor: Actor, run_id: int) -> dict:
        if not (actor.can("gestion.integraciones") or actor.can("inventario.importar")):
            actor.require("inventario.importar")
        with self.db.tx() as conn:
            if not conn.execute("UPDATE sync_runs SET status = 'descartada', finished_at = ? WHERE id = ? AND status = 'vista_previa'",
                                (iso(), run_id)).rowcount:
                raise ValidationError("Solo se descartan vistas previas pendientes.")
        for f in self.imports_dir.glob(f"run-{run_id}.*"):
            f.unlink(missing_ok=True)
        return self.run(actor, run_id)

    def _mark(self, connection_id: int, status: str, message: str) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE integration_connections SET last_sync_at = ?, last_status = ?, last_message = ? WHERE id = ?",
                         (iso(), status, message[:500], connection_id))

    # ------------------------------------------------------------------ sincronización programada
    def tick(self) -> list[int]:
        """Sincroniza las conexiones con intervalo vencido. Lo llama el planificador del servidor."""
        done = []
        with self.db.read() as conn:
            due = [dict(r) for r in conn.execute("SELECT id, last_sync_at, sync_interval_min FROM integration_connections"
                                                 " WHERE active = 1 AND sync_mode = 'intervalo'")]
        for c in due:
            if c["last_sync_at"] and (now_utc() - parse_iso(c["last_sync_at"])).total_seconds() < c["sync_interval_min"] * 60:
                continue
            try:
                run = self.preview_connection(SYSTEM, c["id"], trigger="automatica")
                self.apply(SYSTEM, run["id"])
                done.append(c["id"])
            except DomainError as exc:
                log.warning("Sincronización %s falló: %s", c["id"], exc.detail)
                self._mark(c["id"], "error", exc.detail)
            except Exception:  # noqa: BLE001 - el planificador nunca debe detenerse
                log.exception("Error inesperado al sincronizar la conexión %s", c["id"])
                self._mark(c["id"], "error", "Error inesperado; revise el registro del servidor.")
        return done


def _money(value) -> str | None:
    return None if value is None else str(from_cents(to_cents(value)))


def _cell(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if isinstance(value, (int, float, str)) else str(value)
