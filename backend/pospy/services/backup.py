"""Copias de seguridad verificables y restauración.

Copia: API de respaldo en caliente de SQLite (consistente aunque haya escrituras), verificación con
PRAGMA integrity_check sobre la copia y manifiesto JSON con SHA-256, tamaño y versión del esquema.
Restaurar: se verifica la copia, se hace una copia de seguridad del estado actual, se reemplaza el
contenido de la base en vivo con la API de respaldo (atómico), se aplican migraciones pendientes y
se cierran todas las sesiones.

Las copias contienen datos del negocio (no contraseñas en claro). Guárdelas en un disco cifrado o
cópielas a un medio externo; las credenciales OAuth guardadas están cifradas y en Windows solo las
puede descifrar la misma cuenta de Windows.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__
from ..core.actor import SYSTEM, Actor
from ..core.audit import record
from ..core.clock import iso, now_utc, parse_iso
from ..core.errors import NotFoundError, ValidationError

NAME = re.compile(r"^pospy-\d{8}-\d{6}(-[a-z0-9_]{1,20})?\.db$")
MAX_UPLOAD = 2 * 1024 ** 3


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_db(path: Path) -> dict:
    """Comprueba que el archivo es una base POS-PY íntegra; devuelve versión de esquema y conteos."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValidationError(f"El archivo no es una base de datos válida: {exc}") from None
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValidationError(f"La copia está dañada: {result}")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"schema_migrations", "users", "products", "journal_entries"} <= tables:
            raise ValidationError("El archivo no es una copia de POS-PY.")
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("users", "products", "sales", "inventory_movements", "journal_entries")}
        return {"schema_version": version, "counts": counts}
    except sqlite3.DatabaseError as exc:
        raise ValidationError(f"El archivo no es una base de datos válida: {exc}") from None
    finally:
        conn.close()


class BackupService:
    def __init__(self, db, settings, backups_dir: Path):
        self.db = db
        self.settings = settings
        self.dir = Path(backups_dir)
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        if not NAME.match(name or ""):
            raise NotFoundError("Copia no encontrada.")
        path = self.dir / name
        if not path.exists():
            raise NotFoundError("Copia no encontrada.")
        return path

    def create(self, actor: Actor, label: str = "manual") -> dict:
        if actor is not SYSTEM:
            actor.require("gestion.respaldos")
        label = re.sub(r"[^a-z0-9_]", "_", label.lower())[:20] or "manual"
        with self._lock:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            target = self.dir / f"pospy-{stamp}-{label}.db"
            n = 1
            while target.exists():
                target = self.dir / f"pospy-{stamp}-{label}{n}.db"
                n += 1
            src = self.db.connect()
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode = DELETE")   # copia autocontenida en un solo archivo
            finally:
                dst.close()
                src.close()
            info = inspect_db(target)
            manifest = {"file": target.name, "sha256": _sha256(target), "size": target.stat().st_size,
                        "created_at": iso(), "app_version": __version__, "label": label, **info}
            target.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with self.db.tx() as conn:
                record(conn, actor, "respaldo.crear", "backup", target.name, {"tamano": manifest["size"]})
            self._prune()
        return manifest

    def _prune(self) -> None:
        keep = int(self.settings.get("respaldos")["keep"])
        files = sorted((p for p in self.dir.glob("pospy-*.db") if NAME.match(p.name) and "antes_de_restaurar" not in p.name),
                       key=lambda p: p.name)
        for old in files[:-keep]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)

    def list(self, actor: Actor) -> list[dict]:
        actor.require("gestion.respaldos")
        out = []
        for p in sorted(self.dir.glob("pospy-*.db"), key=lambda p: p.name, reverse=True):
            if not NAME.match(p.name):
                continue
            meta_file = p.with_suffix(".json")
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {"file": p.name}
            meta["size"] = p.stat().st_size
            out.append(meta)
        return out

    def verify(self, actor: Actor, name: str) -> dict:
        actor.require("gestion.respaldos")
        path = self._path(name)
        meta_file = path.with_suffix(".json")
        expected = json.loads(meta_file.read_text(encoding="utf-8")).get("sha256") if meta_file.exists() else None
        actual = _sha256(path)
        info = inspect_db(path)
        ok = expected is None or expected == actual
        return {"file": name, "ok": ok, "sha256": actual, "sha256_matches": ok if expected else None, **info,
                "detail": "Copia íntegra." if ok else "La huella no coincide con el manifiesto: el archivo cambió después de"
                                                    " crearse."}

    def file(self, actor: Actor, name: str) -> Path:
        actor.require("gestion.respaldos")
        return self._path(name)

    def store_upload(self, actor: Actor, content: bytes) -> str:
        actor.require("gestion.respaldos")
        if len(content) > MAX_UPLOAD:
            raise ValidationError("Archivo demasiado grande.")
        if not content.startswith(b"SQLite format 3\x00"):
            raise ValidationError("El archivo no es una copia de POS-PY (.db).")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = self.dir / f"pospy-{stamp}-subida.db"
        target.write_bytes(content)
        try:
            info = inspect_db(target)
        except ValidationError:
            target.unlink(missing_ok=True)
            raise
        manifest = {"file": target.name, "sha256": _sha256(target), "size": target.stat().st_size, "created_at": iso(),
                    "label": "subida", **info}
        target.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return target.name

    def restore(self, actor: Actor, name: str) -> dict:
        actor.require("gestion.respaldos")
        source = self._path(name)
        check = self.verify(actor, name)
        if not check["ok"]:
            raise ValidationError(check["detail"])
        current_version = self.db.schema_version()
        if check["schema_version"] > current_version:
            raise ValidationError("La copia es de una versión más nueva de POS-PY. Actualice la aplicación antes de restaurar.")
        safety = self.create(actor, "antes_de_restaurar")
        with self.db.write_lock:
            src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            dst = self.db.connect()
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
            applied = self.db.migrate()
            with self.db.tx() as conn:
                conn.execute("UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL", (iso(),))
                record(conn, None, "respaldo.restaurar", "backup", name,
                       {"por": actor.username, "copia_previa": safety["file"], "migraciones": applied})
        return {"restored": name, "safety_backup": safety["file"], "migrations_applied": applied}

    def auto_backup_if_due(self) -> dict | None:
        if not self.settings.get("respaldos")["auto_daily"]:
            return None
        latest = None
        for p in self.dir.glob("pospy-*-auto.db"):
            meta = p.with_suffix(".json")
            if meta.exists():
                created = parse_iso(json.loads(meta.read_text(encoding="utf-8"))["created_at"])
                latest = max(latest, created) if latest else created
        if latest and (now_utc() - latest).total_seconds() < 23 * 3600:
            return None
        return self.create(SYSTEM, "auto")
