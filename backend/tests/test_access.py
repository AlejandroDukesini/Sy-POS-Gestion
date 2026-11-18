"""Configuración inicial sin cuenta, inicio de sesión activable, empleados sin cuenta y tareas.

Escenarios del documento CORRECCION_CONFIGURACION_INICIAL_Y_EMPLEADOS.txt:
  A. primera ejecución · B. autenticación activada · C. autenticación desactivada · D. compatibilidad
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pospy import db as dbmod
from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext
from pospy.core import permissions as perms
from pospy.core.actor import Actor
from pospy.core.errors import AuthError, PermissionDenied, ValidationError
from pospy.core.security import hash_password
from pospy.migrations import MIGRATIONS

from .conftest import ADMIN_PASSWORD, EMPLOYEE_PASSWORD

ADMIN_NEW = "Dueña segura 2027"


def make(data_dir, **kw):
    return AppContext(Config.from_env(data_dir=data_dir, web_dist=data_dir / "no-dist", master_key="prueba", **kw))


def http(app, host="testclient"):
    c = TestClient(create_app(app), client=(host, 50000))
    c.headers.update({"X-Requested-With": "pos-py"})
    return c


def code_of(app) -> str:
    return app.auth.setup_file.read_text(encoding="utf-8").strip()


def users_snapshot(app):
    with app.db.read() as conn:
        users = [tuple(r) for r in conn.execute("SELECT id, username, full_name, role, active, password_hash FROM users ORDER BY id")]
        permissions = [tuple(r) for r in conn.execute("SELECT * FROM user_permissions ORDER BY user_id, permission")]
        tasks = [tuple(r) for r in conn.execute("SELECT t.id, a.user_id, t.status FROM tasks t JOIN task_assignees a"
                                                  " ON a.task_id = t.id ORDER BY t.id, a.user_id")]
    return users, permissions, tasks


def run_wizard(c, app, enable_login: bool):
    """Recorre el asistente completo por HTTP, como lo hace la interfaz."""
    assert c.post("/api/setup/start", json={"code": code_of(app)}).status_code == 200
    me = c.get("/api/me").json()["user"]
    assert c.put("/api/settings/empresa", json={"name": "Ferretería La 14", "city": "Cali"}).status_code == 200
    assert c.put("/api/setup/step", json={"step": "preferencias"}).status_code == 200
    assert c.put("/api/settings/ventas", json={"max_manual_discount_pct": 15}).status_code == 200
    assert c.put("/api/setup/step", json={"step": "seguridad"}).status_code == 200
    if enable_login:
        assert c.put(f"/api/users/{me['id']}", json={"username": "duena", "full_name": "Dueña"}).status_code == 200
        assert c.post("/api/auth/password", json={"current": "", "password": ADMIN_NEW}).status_code == 200
        assert c.put("/api/security/login", json={"enabled": True}).status_code == 200
    assert c.put("/api/setup/step", json={"step": "empleados"}).status_code == 200
    emp = c.post("/api/users", json={"full_name": "Ana María Pérez", "role": "employee"})
    assert emp.status_code == 200, emp.text
    task = c.post("/api/tasks", json={"title": "Contar bodega", "assignee_id": emp.json()["id"], "due_date": "2026-12-01"})
    assert task.status_code == 200, task.text
    assert c.post("/api/setup/complete").status_code == 200
    return emp.json(), task.json()


# ------------------------------------------------------------------ A. primera ejecución
def test_A_first_run_opens_without_account_and_persists(tmp_path):
    app = make(tmp_path / "data")
    c = http(app)
    status = c.get("/api/setup/status").json()
    assert status["needs_setup"] and not status["login_enabled"] and status["setup_step"] == "empresa"
    assert c.get("/api/me").status_code == 401                      # aún sin sesión
    assert c.post("/api/setup/start", json={"code": "MAL"}).status_code == 422
    assert c.post("/api/setup/start", json={"code": code_of(app)}).status_code == 200
    me = c.get("/api/me").json()
    assert me["user"]["role"] == "admin" and not me["must_change_password"] and me["direct_session"]

    # activar el inicio de sesión exige un administrador con contraseña
    r = c.put("/api/security/login", json={"enabled": True})
    assert r.status_code == 422 and "contraseña" in r.json()["detail"]

    assert c.put("/api/settings/empresa", json={"name": "Ferretería La 14"}).status_code == 200
    assert c.post("/api/auth/password", json={"current": "", "password": ADMIN_NEW}).status_code == 200
    assert c.put("/api/security/login", json={"enabled": True}).status_code == 200
    assert c.get("/api/me").status_code == 200                      # la sesión del asistente sigue durante la configuración
    emp = c.post("/api/users", json={"full_name": "Ana María Pérez"}).json()
    assert emp["username"] == "ana.maria.perez" and not emp["has_password"] and emp["role"] == "employee"
    assert c.post("/api/setup/complete").status_code == 200
    assert not app.auth.setup_file.exists()
    assert c.get("/api/me").status_code == 401                      # al terminar se pide iniciar sesión

    # «reinicio»: nuevo proceso sobre los mismos datos
    again = make(tmp_path / "data")
    status = http(again).get("/api/setup/status").json()
    assert not status["needs_setup"] and status["login_enabled"] and not status["direct_access"]
    assert again.settings.get("empresa")["name"] == "Ferretería La 14"
    assert not again.auth.setup_file.exists()


def test_A_wizard_resumes_from_last_step_and_never_duplicates_admin(tmp_path):
    app = make(tmp_path / "data")
    c = http(app)
    c.post("/api/setup/start", json={"code": code_of(app)})
    c.put("/api/setup/step", json={"step": "seguridad"})
    again = make(tmp_path / "data")                                 # se cerró la aplicación a mitad del asistente
    assert again.auth.setup_file.exists()
    c2 = http(again)
    assert c2.get("/api/setup/status").json()["setup_step"] == "seguridad"
    assert c2.post("/api/setup/start", json={"code": code_of(again)}).status_code == 200
    with again.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_A_setup_only_from_local_machine(tmp_path):
    app = make(tmp_path / "data")
    remote = http(app, host="192.168.1.50")
    assert remote.post("/api/setup/start", json={"code": code_of(app)}).status_code == 403
    assert remote.get("/api/setup/status").json()["code_file"] is None


def test_A_desktop_injected_code(tmp_path):
    app = make(tmp_path / "data", setup_code="AAAA-BBBB-CCCC")
    c = http(app)
    assert c.get("/api/setup/status").json()["code_injected"]
    assert c.post("/api/setup/start", json={"code": "aaaa-bbbb-cccc"}).status_code == 200


# ------------------------------------------------------------------ B. autenticación activada
@pytest.fixture()
def login_on(tmp_path):
    app = make(tmp_path / "data")
    c = http(app)
    emp, task = run_wizard(c, app, enable_login=True)
    admin = app.auth.login("duena", ADMIN_NEW).actor
    staff = app.users.create(admin, {"username": "caja1", "full_name": "Caja Uno", "password": EMPLOYEE_PASSWORD,
                                     "permissions": ["ventas.vender", "inventario.ver"]})
    return app, emp, task, staff


def test_B_login_required_and_credentials_checked(login_on):
    app, emp, _task, _staff = login_on
    c = http(app)
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/auth/profiles").status_code == 401           # sin acceso directo
    assert c.post("/api/auth/open", json={"user_id": emp["id"]}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "duena", "password": "otra cosa 123"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "duena", "password": ADMIN_NEW}).status_code == 200
    assert c.get("/api/me").json()["user"]["role"] == "admin"
    with pytest.raises(AuthError):                                  # empleado sin cuenta no puede iniciar sesión
        app.auth.login(emp["username"], "")


def test_B_permissions_and_settings_protected(login_on):
    app, _emp, _task, _staff = login_on
    c = http(app)
    r = c.post("/api/auth/login", json={"username": "caja1", "password": EMPLOYEE_PASSWORD})
    assert r.status_code == 200 and r.json()["must_change_password"]
    c.post("/api/auth/password", json={"current": EMPLOYEE_PASSWORD, "password": "Caja nueva 2027"})
    assert c.put("/api/settings/empresa", json={"name": "Hack"}).status_code == 403
    assert c.put("/api/security/login", json={"enabled": False}).status_code == 403
    assert c.get("/api/security").status_code == 403
    assert c.post("/api/users", json={"full_name": "Intruso", "role": "admin"}).status_code == 403
    assert c.get("/api/products").status_code == 200               # lo que sí tiene permitido
    assert app.settings.get("empresa")["name"] == "Ferretería La 14"


def test_B_cannot_leave_login_enabled_without_admin_password(login_on):
    app, _emp, _task, _staff = login_on
    admin = app.auth.login("duena", ADMIN_NEW).actor
    other = app.users.create(admin, {"full_name": "Socio", "role": "admin"})   # administrador sin contraseña
    as_other = Actor(other["id"], other["username"], "admin", perms.ALL)
    with pytest.raises(ValidationError):    # quedaría el inicio de sesión activo sin nadie que pueda entrar
        as_other.require("gestion.usuarios") or app.users.update(as_other, admin.id, {"active": False})
    with pytest.raises(ValidationError):
        app.users.update(as_other, admin.id, {"role": "employee"})


# ------------------------------------------------------------------ C. autenticación desactivada
def test_C_disable_login_keeps_everything_and_allows_direct_access(login_on, tmp_path):
    app, emp, task, staff = login_on
    before = users_snapshot(app)
    c = http(app)
    c.post("/api/auth/login", json={"username": "duena", "password": ADMIN_NEW})
    assert c.put("/api/security/login", json={"enabled": False}).status_code == 200
    assert users_snapshot(app) == before                            # no se borra ni cambia ninguna cuenta, clave o permiso

    again = make(tmp_path / "data")                                 # reinicio: persiste desactivado
    d = http(again)
    status = d.get("/api/setup/status").json()
    assert status["direct_access"] and not status["login_enabled"]
    profiles = {p["username"]: p for p in d.get("/api/auth/profiles").json()}
    assert profiles["duena"]["requires_password"] and not profiles[emp["username"]]["requires_password"]
    assert "password_hash" not in profiles["duena"]
    assert d.post("/api/auth/open", json={"user_id": profiles["duena"]["id"]}).status_code == 401  # admin: con contraseña

    # el empleado sin cuenta entra directo, con SUS permisos, y ve y actualiza sus tareas
    assert d.post("/api/auth/open", json={"user_id": emp["id"]}).status_code == 200
    me = d.get("/api/me").json()
    assert me["user"]["id"] == emp["id"] and me["direct_session"]
    mine = d.get("/api/tasks").json()
    assert [t["id"] for t in mine] == [task["id"]]
    assert d.put(f"/api/tasks/{task['id']}", json={"status": "completada"}).json()["status"] == "completada"
    assert d.put(f"/api/tasks/{task['id']}", json={"title": "Otra"}).status_code == 403
    assert d.post("/api/tasks", json={"title": "X", "assignee_id": emp["id"]}).status_code == 403
    assert d.put("/api/settings/empresa", json={"name": "Hack"}).status_code == 403
    assert d.put("/api/security/login", json={"enabled": True}).status_code == 403
    assert d.get(f"/api/tasks?assignee_id={staff['id']}").status_code == 403

    # el empleado con contraseña temporal entra directo sin que se le exija cambiarla
    e = http(again)
    assert e.post("/api/auth/open", json={"user_id": staff["id"]}).status_code == 200
    assert not e.get("/api/me").json()["must_change_password"]

    # acceso directo solo en el propio equipo
    assert http(again, host="10.1.1.9").get("/api/auth/profiles").status_code == 403


def test_C_reenabling_login_closes_direct_sessions(login_on):
    app, emp, _task, _staff = login_on
    admin = http(app)
    admin.post("/api/auth/login", json={"username": "duena", "password": ADMIN_NEW})
    admin.put("/api/security/login", json={"enabled": False})
    d = http(app)
    d.post("/api/auth/open", json={"user_id": emp["id"]})
    assert d.get("/api/me").status_code == 200
    assert admin.put("/api/security/login", json={"enabled": True}).status_code == 200
    assert d.get("/api/me").status_code == 401
    assert admin.get("/api/me").status_code == 200                  # la sesión con contraseña sigue


def test_C_login_disabled_from_the_start(tmp_path):
    app = make(tmp_path / "data")
    c = http(app)
    emp, task = run_wizard(c, app, enable_login=False)
    assert c.get("/api/me").status_code == 200                      # sigue dentro tras finalizar
    status = c.get("/api/setup/status").json()
    assert status["direct_access"] and not status["needs_setup"]
    assert app.tasks.list(app.auth.open_session(emp["id"]).actor)[0]["id"] == task["id"]


# ------------------------------------------------------------------ D. compatibilidad
def test_D_existing_installation_keeps_login_and_data(tmp_path, monkeypatch):
    """Base creada con la versión anterior (migraciones 1 y 2) que se actualiza a la 3."""
    data = tmp_path / "data"
    monkeypatch.setattr(dbmod, "MIGRATIONS", [m for m in MIGRATIONS if m[0] < 3])
    old = make(data)
    with old.db.tx() as conn:          # datos como los dejaba la versión anterior (sin fila «acceso»)
        for username, role, password in (("admin", "admin", ADMIN_PASSWORD), ("empleado", "employee", EMPLOYEE_PASSWORD)):
            cur = conn.execute("INSERT INTO users(username, full_name, role, password_hash, created_at, updated_at)"
                               " VALUES (?,?,?,?,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')",
                               (username, username.title(), role, hash_password(password)))
            if role == "employee":
                conn.execute("INSERT INTO user_permissions VALUES (?, 'ventas.vender')", (cur.lastrowid,))
    with old.db.read() as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]
        perms_before = [tuple(r) for r in conn.execute("SELECT * FROM user_permissions ORDER BY 1, 2")]
    monkeypatch.setattr(dbmod, "MIGRATIONS", MIGRATIONS)

    new = make(data)
    assert new.db.schema_version() >= 3
    assert new.access.state() == {"login_enabled": True, "setup_completed": True, "setup_step": "listo"}
    with new.db.read() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM users ORDER BY id")] == before
        assert [tuple(r) for r in conn.execute("SELECT * FROM user_permissions ORDER BY 1, 2")] == perms_before
    assert new.auth.login("admin", ADMIN_PASSWORD).actor.is_admin
    with pytest.raises(AuthError):
        new.auth.start_setup("cualquiera")


def test_D_tasks_survive_employee_deactivation(ctx, admin, employee):
    task = ctx.tasks.create(admin, {"title": "Revisar precios", "assignee_id": employee.id})
    ctx.users.update(admin, employee.id, {"active": False})
    listed = ctx.tasks.list(admin, assignee_id=employee.id)
    assert [t["id"] for t in listed] == [task["id"]] and listed[0]["assignees"][0]["user_active"] == 0
    with pytest.raises(ValidationError):                            # no se asignan tareas nuevas a inactivos
        ctx.tasks.create(admin, {"title": "Otra", "assignee_id": employee.id})
    with pytest.raises(PermissionDenied):                           # el responsable no borra tareas asignadas
        ctx.tasks.delete(employee, task["id"])
    assert ctx.tasks.list(admin, assignee_id=employee.id)           # desactivar no borra sus tareas


def test_D_employee_without_account_gets_one_later(ctx, admin):
    emp = ctx.users.create(admin, {"full_name": "Luis"})
    assert emp["username"] == "luis" and not emp["has_password"]
    assert ctx.users.create(admin, {"full_name": "Luis"})["username"] == "luis.2"   # sin duplicados
    ctx.users.reset_password(admin, emp["id"], EMPLOYEE_PASSWORD)
    assert ctx.auth.login("luis", EMPLOYEE_PASSWORD).must_change_password


def test_D_only_admins_toggle_login(ctx, admin, employee):
    with pytest.raises(PermissionDenied):
        ctx.access.set_login(employee, False)
    ctx.access.set_login(admin, False)
    assert not ctx.access.state()["login_enabled"]
