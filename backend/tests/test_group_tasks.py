"""Tareas de grupos de trabajo: varios responsables, estado individual y general, prioridad, comentarios,
historial, permisos del servidor, sincronización en vivo y persistencia (escenarios 1 a 10)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext
from pospy.core.errors import NotFoundError, PermissionDenied, ValidationError

from .conftest import ADMIN_PASSWORD, EMPLOYEE_PASSWORD, login
from .test_groups import _employee, _token

PASSWORD_2 = "Almacen firme 77y"
PASSWORD_3 = "Vitrina clara 55z"


@pytest.fixture()
def team(ctx, admin, employee):
    """Grupo del admin con Ana (empleado) y Beto como integrantes; Caro existe pero no está en el grupo."""
    beto = _employee(ctx, admin, "beto", "Beto Bodega", PASSWORD_2)
    caro = _employee(ctx, admin, "caro", "Caro Caja", PASSWORD_3)
    g = ctx.groups.create(admin, {"name": "Turno mañana"})
    gid = g["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, gid, {"max_uses": 5})["url"])
    ctx.groups.accept(employee, token)
    ctx.groups.accept(beto, token)
    return gid, employee, beto, caro


def test_1_to_8_admin_assigns_to_several_members_and_tracks_individual_progress(ctx, admin, team):
    gid, ana, beto, caro = team
    groups = ctx.tasks.groups(admin)
    assert [g["public_id"] for g in groups] == [gid]
    assert {m["full_name"] for m in groups[0]["members"]} == {"Empleado Uno", "Beto Bodega"}   # consulta integrantes

    # 1-3: crear y asignar a uno y a varios
    solo = ctx.tasks.create(admin, {"title": "Cuadrar caja", "group": gid, "assignee_ids": [ana.id], "priority": "alta"})
    both = ctx.tasks.create(admin, {"title": "Inventario de bodega", "description": "Pasillos 1 a 4", "group": gid,
                                    "assignee_ids": [ana.id, beto.id], "priority": "urgente", "due_date": "2026-11-30",
                                    "notes": "Usar el lector de códigos"})
    assert both["group_name"] == "Turno mañana" and both["priority"] == "urgente" and both["status"] == "pendiente"
    assert both["progress"] == {"done": 0, "total": 2} and {a["full_name"] for a in both["assignees"]} == {"Empleado Uno", "Beto Bodega"}
    with pytest.raises(ValidationError):                                   # no integrante del grupo
        ctx.tasks.create(admin, {"title": "X", "group": gid, "assignee_ids": [caro.id]})
    with pytest.raises(ValidationError):
        ctx.tasks.create(admin, {"title": "X", "group": gid, "assignee_ids": []})

    # 4-5: cada empleado recibe solo lo suyo; Caro (fuera del grupo) nada
    assert {t["id"] for t in ctx.tasks.list(ana)} == {solo["id"], both["id"]}
    assert [t["id"] for t in ctx.tasks.list(beto)] == [both["id"]]
    assert ctx.tasks.list(caro) == []
    for actor in (caro,):
        with pytest.raises(NotFoundError):
            ctx.tasks.get(actor, both["id"])
        with pytest.raises(NotFoundError):
            ctx.tasks.set_my_status(actor, both["id"], "completada")
    with pytest.raises(NotFoundError):                                     # Beto no ve la tarea solo de Ana
        ctx.tasks.get(beto, solo["id"])
    with pytest.raises(PermissionDenied):
        ctx.tasks.list(beto, assignee_id=ana.id)

    # 6: el empleado actualiza SU estado; 8: estados individuales y general
    t = ctx.tasks.set_my_status(ana, both["id"], "en_curso")
    assert t["my_status"] == "en_curso" and t["status"] == "en_curso"
    t = ctx.tasks.set_my_status(ana, both["id"], "completada")
    assert t["status"] == "en_curso" and t["progress"] == {"done": 1, "total": 2}   # uno solo no completa la tarea
    states = {a["full_name"]: a["status"] for a in ctx.tasks.get(admin, both["id"])["assignees"]}
    assert states == {"Empleado Uno": "completada", "Beto Bodega": "pendiente"}      # quién terminó y quién no
    t = ctx.tasks.set_my_status(beto, both["id"], "completada")
    assert t["status"] == "completada" and t["completed_at"]
    assert [x["status"] for x in ctx.tasks.list(ana, my_status="completada")] == ["completada"]

    # el empleado no edita, no reasigna, no cambia prioridad ni fechas, no elimina
    for change in ({"title": "Otra"}, {"assignee_ids": [ana.id]}, {"priority": "baja"}, {"due_date": "2027-01-01"}):
        with pytest.raises(PermissionDenied):
            ctx.tasks.update(ana, both["id"], change)
    with pytest.raises(PermissionDenied):
        ctx.tasks.delete(ana, solo["id"])
    with pytest.raises(PermissionDenied):
        ctx.tasks.create(ana, {"title": "Para Beto", "group": gid, "assignee_ids": [beto.id]})

    # comentarios y solicitudes de cambio; historial
    ctx.tasks.comment(ana, solo["id"], "La caja 2 no enciende, ¿puedo usar la 1?", request_change=True)
    detail = ctx.tasks.comment(admin, solo["id"], "Sí, use la caja 1.")
    kinds = [e["kind"] for e in detail["events"]]
    assert kinds[:3] == ["comentario", "solicitud", "creada"]
    assert detail["events"][1]["user_name"] == "Empleado Uno"

    # 7: el administrador gestiona: cambia responsables, fechas, prioridad, cancela
    t = ctx.tasks.update(admin, solo["id"], {"assignee_ids": [beto.id], "priority": "media", "due_date": "2026-12-05",
                                             "version": solo["version"]})
    assert [a["full_name"] for a in t["assignees"]] == ["Beto Bodega"] and t["priority"] == "media"
    assert ctx.tasks.list(ana, status="abiertas") == []                     # Ana ya no la tiene
    with pytest.raises(ValidationError):                                   # con comentarios: no se elimina, se cancela
        ctx.tasks.delete(admin, solo["id"])
    t = ctx.tasks.update(admin, solo["id"], {"status": "cancelada"})
    with pytest.raises(ValidationError):
        ctx.tasks.set_my_status(beto, solo["id"], "en_curso")
    review = ctx.tasks.update(admin, both["id"], {"status": "en_revision"})
    assert review["status"] == "en_revision"
    history = [e["kind"] for e in ctx.tasks.get(admin, solo["id"])["events"]]
    assert "responsables" in history and "estado" in history
    assert {t["id"] for t in ctx.tasks.list(admin, group=gid)} == {solo["id"], both["id"]}   # las completadas no desaparecen
    assert [t["id"] for t in ctx.tasks.list(admin, priority="urgente")] == [both["id"]]
    assert [t["id"] for t in ctx.tasks.list(admin, assignee_id=beto.id, status="cancelada")] == [solo["id"]]
    assert [t["id"] for t in ctx.tasks.list(admin, due_from="2026-12-01")] == [solo["id"]]


def test_foreign_groups_and_removed_members(ctx, admin, team):
    gid, ana, beto, _caro = team
    other_admin = ctx.users.create(admin, {"username": "socio", "full_name": "Socio", "role": "admin",
                                           "password": PASSWORD_3 + "x"})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE id = ?", (other_admin["id"],))
    socio = ctx.auth.login("socio", PASSWORD_3 + "x").actor
    task = ctx.tasks.create(admin, {"title": "Del grupo", "group": gid, "assignee_ids": [ana.id, beto.id]})
    # Otro administrador no ve ni gestiona tareas de un grupo ajeno, ni asigna en él
    assert ctx.tasks.list(socio) == [] and ctx.tasks.groups(socio) == []
    for call in (lambda: ctx.tasks.get(socio, task["id"]), lambda: ctx.tasks.update(socio, task["id"], {"title": "x"}),
                 lambda: ctx.tasks.delete(socio, task["id"]),
                 lambda: ctx.tasks.create(socio, {"title": "x", "group": gid, "assignee_ids": [ana.id]})):
        with pytest.raises(NotFoundError):
            call()
    # Retirada del grupo: deja de ver la tarea; el admin ve que ya no es integrante
    ctx.groups.member_action(admin, gid, ana.id, "retirar")
    assert ctx.tasks.list(ana) == []
    with pytest.raises(NotFoundError):
        ctx.tasks.set_my_status(ana, task["id"], "en_curso")
    flags = {a["full_name"]: a["in_group"] for a in ctx.tasks.get(admin, task["id"])["assignees"]}
    assert flags == {"Empleado Uno": 0, "Beto Bodega": 1}
    with pytest.raises(ValidationError):                                   # no se asignan tareas nuevas a quien salió
        ctx.tasks.create(admin, {"title": "x", "group": gid, "assignee_ids": [ana.id]})
    ctx.groups.set_open(admin, gid, False)
    with pytest.raises(ValidationError):                                   # grupo cerrado: sin tareas nuevas
        ctx.tasks.create(admin, {"title": "x", "group": gid, "assignee_ids": [beto.id]})
    assert ctx.tasks.list(beto)[0]["id"] == task["id"]                     # la existente sigue visible


def test_10_live_sync_reaches_only_the_people_involved(ctx, admin, team):
    gid, ana, beto, caro = team
    loop = asyncio.new_event_loop()
    try:
        subs = {name: ctx.realtime.subscribe(actor.id, loop)[0] for name, actor in
                (("admin", admin), ("ana", ana), ("beto", beto), ("caro", caro))}
        task = ctx.tasks.create(admin, {"title": "Vitrinas", "group": gid, "assignee_ids": [ana.id]})
        loop.run_until_complete(asyncio.sleep(0))
        assert subs["ana"].queue.get_nowait() == {"type": "tarea", "task": task["id"]}    # el empleado recibe la tarea
        ctx.tasks.set_my_status(ana, task["id"], "en_curso")
        loop.run_until_complete(asyncio.sleep(0))
        events = []
        while not subs["admin"].queue.empty():
            events.append(subs["admin"].queue.get_nowait())
        assert {"type": "tarea", "task": task["id"]} in events                           # el admin ve el cambio
        assert subs["beto"].queue.empty() and subs["caro"].queue.empty()                 # nadie más se entera
    finally:
        loop.close()


def test_9_tasks_persist_after_logout_and_restart(tmp_path, ctx, admin, team):
    gid, ana, beto, _caro = team
    task = ctx.tasks.create(admin, {"title": "Persistente", "group": gid, "assignee_ids": [ana.id, beto.id],
                                    "priority": "alta"})
    ctx.tasks.set_my_status(beto, task["id"], "completada")
    ctx.tasks.comment(ana, task["id"], "Empiezo mañana")
    restarted = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    a = restarted.auth.login("empleado", EMPLOYEE_PASSWORD).actor
    adm = restarted.auth.login("admin", ADMIN_PASSWORD).actor
    t = restarted.tasks.get(a, task["id"])
    assert t["priority"] == "alta" and t["group_public_id"] == gid and t["my_status"] == "pendiente"
    assert {x["full_name"]: x["status"] for x in restarted.tasks.get(adm, task["id"])["assignees"]} == {
        "Empleado Uno": "pendiente", "Beto Bodega": "completada"}
    assert t["events"][0]["comment"] == "Empiezo mañana"


def test_http_from_independent_devices(ctx, admin, team):
    gid, ana, beto, caro = team
    app = create_app(ctx)
    adm, a, b, c = (TestClient(app) for _ in range(4))
    for cl in (adm, a, b, c):
        cl.headers.update({"X-Requested-With": "pos-py"})
    login(adm)
    login(a, "empleado", EMPLOYEE_PASSWORD)
    login(b, "beto", PASSWORD_2)
    login(c, "caro", PASSWORD_3)
    created = adm.post("/api/tasks", json={"title": "Etiquetar", "group": gid, "assignee_ids": [ana.id, beto.id],
                                           "priority": "media"})
    assert created.status_code == 200, created.text
    task = created.json()
    assert adm.post("/api/tasks", json={"title": "x", "group": gid, "assignee_ids": [caro.id]}).status_code == 422
    assert a.post("/api/tasks", json={"title": "x", "group": gid, "assignee_ids": [beto.id]}).status_code == 403
    assert [t["id"] for t in a.get(f"/api/tasks?group={gid}").json()] == [task["id"]]
    assert c.get(f"/api/tasks/{task['id']}").status_code == 404 and c.get("/api/tasks").json() == []
    assert a.put(f"/api/tasks/{task['id']}/mine", json={"status": "completada"}).json()["my_status"] == "completada"
    assert a.put(f"/api/tasks/{task['id']}", json={"priority": "baja"}).status_code == 403
    assert a.put(f"/api/tasks/{task['id']}", json={"assignee_ids": [ana.id]}).status_code == 403
    assert a.delete(f"/api/tasks/{task['id']}").status_code == 403
    assert a.post(f"/api/tasks/{task['id']}/comments", json={"comment": "Listo mi parte", "request_change": False}).status_code == 200
    assert a.post("/api/tasks", json={"title": "x", "assignee_ids": [ana.id], "user_id": 1}).status_code == 422
    seen = adm.get(f"/api/tasks/{task['id']}").json()
    assert seen["progress"] == {"done": 1, "total": 2} and seen["status"] == "en_curso"
    assert seen["events"][0]["comment"] == "Listo mi parte"
    assert b.get("/api/tasks?my_status=pendiente").json()[0]["id"] == task["id"]
