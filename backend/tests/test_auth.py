"""1. Inicio y cierre de sesión · 2. Permisos administrador / empleado · autorización."""
from __future__ import annotations

from datetime import timedelta

import pytest

from pospy.config import Config
from pospy.context import AppContext
from pospy.core.clock import iso, now_utc
from pospy.core.errors import AuthError, PermissionDenied, ValidationError
from pospy.core.security import token_hash

from .conftest import ADMIN_PASSWORD, EMPLOYEE_PASSWORD, login


def test_setup_requires_code_and_runs_once(tmp_path):
    app = AppContext(Config.from_env(data_dir=tmp_path, master_key="x"))
    assert app.auth.needs_setup()
    with pytest.raises(ValidationError):
        app.auth.setup_admin("MAL-COD-IGO", "jefe", "Jefe", ADMIN_PASSWORD)
    code = app.auth.setup_file.read_text(encoding="utf-8").strip()
    with pytest.raises(ValidationError):  # política de contraseñas
        app.auth.setup_admin(code, "jefe", "Jefe", "corta")
    app.auth.setup_admin(code, "jefe", "Jefe", ADMIN_PASSWORD)
    assert not app.auth.setup_file.exists()
    with pytest.raises(AuthError):
        app.auth.setup_admin(code, "otro", "Otro", ADMIN_PASSWORD)
    with app.db.read() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("scrypt$") and ADMIN_PASSWORD not in stored


def test_login_logout_and_session(ctx):
    result = ctx.auth.login("admin", ADMIN_PASSWORD)
    actor, must_change = ctx.auth.resolve(result.token)
    assert actor.is_admin and not must_change
    ctx.auth.logout(result.token)
    with pytest.raises(AuthError):
        ctx.auth.resolve(result.token)


def test_wrong_password_is_generic_and_locks_account(ctx):
    for _ in range(4):
        with pytest.raises(AuthError, match="incorrectos"):
            ctx.auth.login("admin", "otra cosa 123")
    with pytest.raises(AuthError, match="incorrectos"):
        ctx.auth.login("nadie", "otra cosa 123")
    with pytest.raises(AuthError):
        ctx.auth.login("admin", "otra cosa 123")   # quinto intento: bloquea
    with pytest.raises(AuthError, match="bloqueada"):
        ctx.auth.login("admin", ADMIN_PASSWORD)
    with ctx.db.read() as conn:
        failures = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'sesion.fallida'").fetchone()[0]
    assert failures == 6   # los fallos quedan auditados (no se pierden con el error)


def test_idle_and_absolute_expiry(ctx):
    token = ctx.auth.login("admin", ADMIN_PASSWORD).token
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                     (iso(now_utc() - timedelta(minutes=31)), token_hash(token)))
    with pytest.raises(AuthError, match="expiró"):
        ctx.auth.resolve(token)
    token = ctx.auth.login("admin", ADMIN_PASSWORD).token
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (iso(now_utc()), token_hash(token)))
    with pytest.raises(AuthError):
        ctx.auth.resolve(token)


def test_new_user_must_change_temporary_password(ctx, admin):
    ctx.users.create(admin, {"username": "caja2", "full_name": "Caja dos", "password": EMPLOYEE_PASSWORD})
    result = ctx.auth.login("caja2", EMPLOYEE_PASSWORD)
    assert result.must_change_password
    ctx.auth.change_password(result.actor, EMPLOYEE_PASSWORD, "Nueva clave 2027", result.token)
    actor, must_change = ctx.auth.resolve(result.token)   # la sesión actual sigue válida
    assert not must_change and actor.username == "caja2"


def test_employee_permissions_are_limited(ctx, admin, employee):
    assert employee.can("ventas.vender") and not employee.can("finanzas.ver")
    with pytest.raises(PermissionDenied):
        ctx.finance.balance_sheet(employee)
    with pytest.raises(PermissionDenied):
        ctx.users.list(employee)
    with pytest.raises(PermissionDenied):
        ctx.settings.update("empresa", {"name": "X"}, employee)
    with pytest.raises(PermissionDenied):
        ctx.backups.list(employee)


def test_admin_only_permissions_cannot_be_granted_to_employee(ctx, admin, employee):
    with pytest.raises(ValidationError, match="exclusivos"):
        ctx.users.update(admin, employee.id, {"permissions": ["ventas.vender", "gestion.usuarios"]})
    with pytest.raises(ValidationError, match="desconocidos"):
        ctx.users.update(admin, employee.id, {"permissions": ["*"]})


def test_permission_change_revokes_sessions(ctx, admin):
    ctx.users.create(admin, {"username": "temporal", "full_name": "T", "password": EMPLOYEE_PASSWORD})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE username = 'temporal'")
    token = ctx.auth.login("temporal", EMPLOYEE_PASSWORD).token
    uid = ctx.auth.resolve(token)[0].id
    ctx.users.update(admin, uid, {"permissions": ["inventario.ver", "finanzas.ver"]})
    with pytest.raises(AuthError, match="cambio en la cuenta"):
        ctx.auth.resolve(token)
    actor = ctx.auth.login("temporal", EMPLOYEE_PASSWORD).actor
    assert actor.can("finanzas.ver") and not actor.can("ventas.vender")


def test_admin_cannot_demote_or_deactivate_self(ctx, admin, employee):
    with pytest.raises(ValidationError, match="propio rol"):
        ctx.users.update(admin, admin.id, {"active": False})
    with pytest.raises(ValidationError, match="propio rol"):
        ctx.users.update(admin, admin.id, {"role": "employee"})
    ctx.users.update(admin, employee.id, {"role": "admin"})
    second = ctx.auth.login("empleado", EMPLOYEE_PASSWORD).actor
    assert second.is_admin
    ctx.users.update(second, admin.id, {"role": "employee"})   # con otro administrador activo sí se permite
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0] == 1


def test_inactive_user_cannot_login(ctx, admin, employee):
    ctx.users.update(admin, employee.id, {"active": False})
    with pytest.raises(AuthError, match="desactivada"):
        ctx.auth.login("empleado", EMPLOYEE_PASSWORD)


# ------------------------------------------------------------------ API
def test_api_requires_session_and_csrf(client):
    assert client.get("/api/products").status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD},
                    headers={"X-Requested-With": ""})
    assert r.status_code == 403
    data = login(client)
    assert data["user"]["role"] == "admin"
    assert "pospy_session" in client.cookies
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
    assert r.status_code == 422   # campos extra rechazados: el rol nunca viene del cliente
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/products").status_code == 401


def test_api_employee_gets_403_on_admin_routes(client, ctx, employee):
    login(client, "empleado", EMPLOYEE_PASSWORD)
    for path in ("/api/users", "/api/settings", "/api/finance/balance-sheet", "/api/backups", "/api/integrations",
                 "/api/activity?user_id=1"):
        r = client.get(path)
        if path.startswith("/api/activity"):
            assert r.status_code == 200 and all(i["user_id"] == employee.id for i in r.json()["items"])
        else:
            assert r.status_code == 403, path
    assert client.get("/api/products").status_code == 200


def test_must_change_password_blocks_api(client, ctx, admin):
    ctx.users.create(admin, {"username": "nuevo", "full_name": "N", "password": EMPLOYEE_PASSWORD})
    login(client, "nuevo", EMPLOYEE_PASSWORD)
    assert client.get("/api/products").status_code == 403
    assert client.get("/api/me").json()["must_change_password"] is True
    r = client.post("/api/auth/password", json={"current": EMPLOYEE_PASSWORD, "password": "Otra clave 2028"})
    assert r.status_code == 200
    assert client.get("/api/products").status_code == 200
