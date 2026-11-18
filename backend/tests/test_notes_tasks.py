"""Notas y tareas: los 12 escenarios de validación del módulo, por servicio y por HTTP."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext
from pospy.core.errors import NotFoundError, PermissionDenied, ValidationError

from .conftest import EMPLOYEE_PASSWORD, login

OTHER_PASSWORD = "Almacen firme 77y"


@pytest.fixture()
def other(ctx, admin):
    ctx.users.create(admin, {"username": "segundo", "full_name": "Empleado Dos", "role": "employee",
                             "password": OTHER_PASSWORD})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE username = 'segundo'")
    return ctx.auth.login("segundo", OTHER_PASSWORD).actor


def test_1_2_notes_are_private_and_searchable(ctx, admin, employee, other):
    a = ctx.notes.create(admin, {"title": "Proveedores", "content": "Llamar a Andina el lunes"})
    e = ctx.notes.create(employee, {"title": "Caja", "content": "Revisar cambio de 50.000"})
    assert [n["id"] for n in ctx.notes.list(admin)] == [a["id"]]                 # 1: el admin la consulta
    assert [n["id"] for n in ctx.notes.list(employee)] == [e["id"]]              # 2: cada quien ve solo las suyas
    assert ctx.notes.list(other) == []
    assert [n["id"] for n in ctx.notes.list(admin, "andina")] == [a["id"]]       # búsqueda en el contenido
    assert [n["id"] for n in ctx.notes.list(employee, "caja")] == [e["id"]]      # y en el título
    assert ctx.notes.list(employee, "%") == []                                   # comodines escapados
    for actor in (admin, other):                                                 # ni el admin ve las de otros
        with pytest.raises(NotFoundError):
            ctx.notes.update(actor, e["id"], {"title": "x"})
        with pytest.raises(NotFoundError):
            ctx.notes.delete(actor, e["id"])
    edited = ctx.notes.update(employee, e["id"], {"content": "Cambio revisado", "version": e["version"]})
    assert edited["title"] == "Caja" and edited["version"] == 2 and edited["updated_at"] >= e["created_at"]
    with pytest.raises(ValidationError):
        ctx.notes.create(employee, {"title": "  ", "content": ""})
    ctx.notes.delete(employee, e["id"])
    assert ctx.notes.list(employee) == []


def test_3_4_personal_tasks_stay_private(ctx, admin, employee):
    mine = ctx.tasks.create(employee, {"title": "Ordenar vitrina", "personal": True, "assignee_id": admin.id})
    own = ctx.tasks.create(admin, {"title": "Pagar arriendo", "personal": True, "due_date": "2026-12-01"})
    assert mine["assignee_id"] == employee.id and mine["personal"] == 1          # siempre de quien la crea
    assert [t["id"] for t in ctx.tasks.list(employee, scope="personales")] == [mine["id"]]
    assert [t["id"] for t in ctx.tasks.list(admin, scope="personales")] == [own["id"]]
    # Las personales no se mezclan con las asignadas, ni para el admin ni en la ficha del empleado.
    assert ctx.tasks.list(admin) == [] and ctx.tasks.list(admin, assignee_id=employee.id) == []
    assert ctx.tasks.list(employee) == []
    with pytest.raises(NotFoundError):
        ctx.tasks.update(admin, mine["id"], {"status": "completada"})
    with pytest.raises(NotFoundError):
        ctx.tasks.delete(employee, own["id"])
    with pytest.raises(PermissionDenied):
        ctx.tasks.list(admin, assignee_id=employee.id, scope="personales")
    with pytest.raises(PermissionDenied):
        ctx.tasks.update(employee, mine["id"], {"assignee_id": admin.id})
    edited = ctx.tasks.update(employee, mine["id"], {"title": "Ordenar vitrina 2", "status": "en_curso"})
    assert edited["status"] == "en_curso"
    with ctx.db.read() as conn:                                                  # no van al historial de actividad
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE entity = 'task'").fetchone()[0] == 0
    ctx.tasks.delete(employee, mine["id"])
    assert ctx.tasks.list(employee, scope="personales") == []


def test_5_to_11_assigned_task_lifecycle(ctx, admin, employee, other):
    task = ctx.tasks.create(admin, {"title": "Contar bodega", "description": "Pasillo 3", "assignee_id": employee.id,
                                    "due_date": "2026-11-30"})
    assert task["personal"] == 0 and task["created_by"] == admin.id               # 5
    assert [t["id"] for t in ctx.tasks.list(employee)] == [task["id"]]            # 6
    t = ctx.tasks.update(employee, task["id"], {"status": "en_curso", "version": task["version"]})
    assert t["status"] == "en_curso"                                              # 7
    t = ctx.tasks.update(employee, task["id"], {"status": "completada", "version": t["version"]})
    assert t["status"] == "completada" and t["completed_at"]                      # 8
    assert ctx.tasks.list(admin)[0]["status"] == "completada"                     # 9
    assert ctx.tasks.list(other) == []                                            # 10
    with pytest.raises(NotFoundError):
        ctx.tasks.update(other, task["id"], {"status": "pendiente"})
    with pytest.raises(PermissionDenied):
        ctx.tasks.list(other, assignee_id=employee.id)
    with pytest.raises(PermissionDenied):                                         # 11
        ctx.tasks.update(employee, task["id"], {"assignee_id": other.id})
    with pytest.raises(PermissionDenied):
        ctx.tasks.update(employee, task["id"], {"title": "Otra"})
    with pytest.raises(PermissionDenied):
        ctx.tasks.delete(employee, task["id"])
    with pytest.raises(PermissionDenied):
        ctx.tasks.create(employee, {"title": "Para otro", "assignee_id": other.id})
    with pytest.raises(ValidationError):                                          # con avance no se elimina:
        ctx.tasks.delete(admin, task["id"])
    assert ctx.tasks.update(admin, task["id"], {"status": "cancelada"})["status"] == "cancelada"   # se cancela
    fresh = ctx.tasks.create(admin, {"title": "Sin avance", "assignee_id": employee.id})
    ctx.tasks.delete(admin, fresh["id"])                                          # sin avance, el admin la elimina
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'tarea.eliminar'").fetchone()[0] == 1


def test_legacy_cancelled_tasks_keep_working(ctx, admin, employee):
    task = ctx.tasks.create(admin, {"title": "Antigua", "assignee_id": employee.id})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE tasks SET status = 'cancelada' WHERE id = ?", (task["id"],))
    assert ctx.tasks.list(admin, status="cancelada")[0]["id"] == task["id"]
    assert ctx.tasks.update(admin, task["id"], {"title": "Antigua (revisada)"})["status"] == "cancelada"
    assert ctx.tasks.update(admin, task["id"], {"status": "pendiente"})["status"] == "pendiente"


def test_admin_sees_status_change_live(ctx, admin, employee):
    task = ctx.tasks.create(admin, {"title": "Limpiar caja", "assignee_id": employee.id})
    loop = asyncio.new_event_loop()
    try:
        sub, _ = ctx.realtime.subscribe(admin.id, loop)
        ctx.tasks.update(employee, task["id"], {"status": "en_curso"})
        loop.run_until_complete(asyncio.sleep(0))
        assert sub.queue.get_nowait() == {"type": "tarea", "task": task["id"]}
        spy, _ = ctx.realtime.subscribe(admin.id, loop)                          # las personales no avisan a otros
        ctx.tasks.create(employee, {"title": "Mía", "personal": True})
        loop.run_until_complete(asyncio.sleep(0))
        assert spy.queue.empty()
    finally:
        loop.close()


def test_12_everything_survives_a_restart(tmp_path, ctx, admin, employee):
    ctx.notes.create(employee, {"title": "Recordatorio", "content": "Pedir bolsas"})
    ctx.tasks.create(employee, {"title": "Personal", "personal": True})
    ctx.tasks.create(admin, {"title": "Asignada", "assignee_id": employee.id})
    restarted = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    emp = restarted.auth.login("empleado", EMPLOYEE_PASSWORD).actor
    assert [n["title"] for n in restarted.notes.list(emp)] == ["Recordatorio"]
    assert [t["title"] for t in restarted.tasks.list(emp, scope="personales")] == ["Personal"]
    assert [t["title"] for t in restarted.tasks.list(emp)] == ["Asignada"]


def test_http_contract_for_both_roles(ctx, admin, employee, other):
    app = create_app(ctx)
    adm, emp, oth = (TestClient(app) for _ in range(3))
    for c in (adm, emp, oth):
        c.headers.update({"X-Requested-With": "pos-py"})
    login(adm)
    login(emp, "empleado", EMPLOYEE_PASSWORD)
    login(oth, "segundo", OTHER_PASSWORD)

    note = emp.post("/api/notes", json={"title": "Mi nota", "content": "Privada"}).json()
    assert [n["id"] for n in emp.get("/api/notes?q=priv").json()] == [note["id"]]
    assert adm.get("/api/notes").json() == [] and oth.get("/api/notes").json() == []
    assert oth.put(f"/api/notes/{note['id']}", json={"title": "hack"}).status_code == 404
    assert adm.delete(f"/api/notes/{note['id']}").status_code == 404
    assert emp.post("/api/notes", json={"title": "x", "owner_id": admin.id}).status_code == 422   # sin campos extra

    personal = emp.post("/api/tasks", json={"title": "Mi tarea", "personal": True}).json()
    assert adm.get("/api/tasks?scope=personales").json() == []
    assert adm.put(f"/api/tasks/{personal['id']}", json={"status": "completada"}).status_code == 404

    task = adm.post("/api/tasks", json={"title": "Inventario", "assignee_id": employee.id}).json()
    assert [t["id"] for t in emp.get("/api/tasks").json()] == [task["id"]]
    assert oth.get("/api/tasks").json() == []
    assert oth.get(f"/api/tasks?assignee_id={employee.id}").status_code == 403
    assert emp.put(f"/api/tasks/{task['id']}", json={"status": "en_curso"}).status_code == 200
    assert emp.put(f"/api/tasks/{task['id']}", json={"assignee_id": other.id}).status_code == 403
    assert emp.delete(f"/api/tasks/{task['id']}").status_code == 403
    assert emp.post("/api/tasks", json={"title": "Para Dos", "assignee_id": other.id}).status_code == 403
    assert adm.get("/api/tasks").json()[0]["status"] == "en_curso"
    assert emp.delete(f"/api/tasks/{personal['id']}").status_code == 200
    assert adm.delete(f"/api/tasks/{task['id']}").status_code == 422            # tiene avance: se cancela
    assert adm.put(f"/api/tasks/{task['id']}", json={"status": "cancelada"}).json()["status"] == "cancelada"
    anon = TestClient(app)
    assert anon.get("/api/notes").status_code == 401 and anon.get("/api/tasks").status_code == 401
