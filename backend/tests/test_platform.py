"""11. Persistencia de preferencias · 13. Migraciones y restauración de copias · configuración y auditoría."""
from __future__ import annotations

import json
import sqlite3

import pytest

from pospy.config import Config
from pospy.context import AppContext
from pospy.core.errors import PermissionDenied, ValidationError
from pospy.db import Database
from pospy.migrations import MIGRATIONS

from .conftest import ADMIN_PASSWORD, key


def test_migrations_are_idempotent_and_versioned(tmp_path):
    db = Database(tmp_path / "x.db")
    assert db.migrate() == [v for v, _, _ in MIGRATIONS]
    assert db.migrate() == []
    assert db.schema_version() == MIGRATIONS[-1][0]
    with db.read() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_prefs_persist_per_user_and_validate(ctx, admin, employee):
    saved = ctx.prefs.save(admin, {"theme": "dark", "font_size": 20, "preferred_printer": "DIGITALPOS"})
    assert saved["theme"] == "dark" and saved["font_size"] == 20
    assert ctx.prefs.get(employee)["theme"] == "light"           # independiente por usuario
    again = AppContext(ctx.config)                               # tras reiniciar el servidor
    assert again.prefs.get(admin)["font_size"] == 20
    with pytest.raises(ValidationError):
        ctx.prefs.save(admin, {"font_size": 99})
    with pytest.raises(ValidationError):
        ctx.prefs.save(admin, {"token": "x"})


def test_company_settings_validation_and_audit(ctx, admin):
    with pytest.raises(ValidationError) as exc:
        ctx.settings.update("empresa", {"email": "no-es-correo", "primary_color": "azul"}, admin)
    assert "email" in exc.value.fields or "primary_color" in exc.value.fields
    ctx.settings.update("empresa", {"name": "Ferretería Central", "timezone": "America/Bogota"}, admin)
    assert ctx.settings.get("empresa")["name"] == "Ferretería Central"
    with pytest.raises(ValidationError):
        ctx.settings.update("empresa", {"desconocido": 1}, admin)
    log = ctx.catalog.activity(admin, q="configuracion")["items"]
    assert log and "Ferretería Central" in log[0]["details"]


def test_audit_never_stores_secrets(ctx, admin):
    ctx.sync.set_google_secret(admin, "super-secreto-123")
    with ctx.db.read() as conn:
        dump = " ".join(r[0] or "" for r in conn.execute("SELECT details FROM audit_log"))
        raw = conn.execute("SELECT ciphertext FROM secrets").fetchone()[0]
    assert "super-secreto-123" not in dump and b"super-secreto-123" not in bytes(raw)
    assert ctx.secrets.get("oauth.google_client_secret") == "super-secreto-123"
    assert ADMIN_PASSWORD not in dump
    with ctx.db.tx() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_log")


def test_backup_verify_and_restore(ctx, admin, product, cash_id):
    backup = ctx.backups.create(admin)
    assert ctx.backups.verify(admin, backup["file"])["ok"]
    ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "4"}],
                               "payments": [{"method_id": cash_id, "amount": "72000"}]}, key())
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 6000
    token = ctx.auth.login("admin", ADMIN_PASSWORD).token
    result = ctx.backups.restore(admin, backup["file"])
    assert result["safety_backup"].endswith("antes_de_restaurar.db")
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 10000
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    from pospy.core.errors import AuthError
    with pytest.raises(AuthError):
        ctx.auth.resolve(token)                                  # la restauración cierra sesiones
    assert ctx.finance.integrity(admin)["ok"]
    assert any(b["file"] == result["safety_backup"] for b in ctx.backups.list(admin))


def test_tampered_or_foreign_backup_is_rejected(ctx, admin, tmp_path):
    backup = ctx.backups.create(admin)
    path = ctx.config.backups_dir / backup["file"]
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE intruso(x)")
    assert not ctx.backups.verify(admin, backup["file"])["ok"]
    with pytest.raises(ValidationError):
        ctx.backups.restore(admin, backup["file"])
    with pytest.raises(ValidationError):
        ctx.backups.store_upload(admin, b"no es sqlite")
    other = tmp_path / "otra.db"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE t(x)")
    with pytest.raises(ValidationError, match="no es una copia"):
        ctx.backups.store_upload(admin, other.read_bytes())


def test_restore_rejects_newer_schema(ctx, admin):
    backup = ctx.backups.create(admin)
    path = ctx.config.backups_dir / backup["file"]
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO schema_migrations(version, name) VALUES (999, 'futuro')")
    meta = path.with_suffix(".json")
    data = json.loads(meta.read_text())
    from pospy.services.backup import _sha256
    data["sha256"] = _sha256(path)
    meta.write_text(json.dumps(data))
    with pytest.raises(ValidationError, match="más nueva"):
        ctx.backups.restore(admin, backup["file"])


def test_backup_names_cannot_escape_folder(ctx, admin):
    from pospy.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        ctx.backups.file(admin, "../pospy.db")


def test_auto_backup_runs_once_a_day(ctx):
    assert ctx.backups.auto_backup_if_due() is not None
    assert ctx.backups.auto_backup_if_due() is None


def test_employee_cannot_backup(ctx, employee):
    with pytest.raises(PermissionDenied):
        ctx.backups.create(employee)


def test_secrets_require_key_outside_windows(tmp_path, monkeypatch):
    import sys

    from pospy.core import secrets_store
    monkeypatch.setattr(sys, "platform", "linux")
    app = AppContext(Config.from_env(data_dir=tmp_path))
    store = secrets_store.SecretStore(app.db, tmp_path, "")
    with app.db.tx() as conn, pytest.raises(secrets_store.SecretStoreError):
        store.set(conn, "x", "y")
