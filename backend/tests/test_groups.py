"""Grupos de trabajo e invitaciones por enlace: reglas del servicio y contrato HTTP."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.core.clock import iso, now_utc
from pospy.core.errors import ConflictError, NotFoundError, PermissionDenied
from pospy.core.ratelimit import TooManyRequests
from pospy.core.security import token_hash
from pospy.services.groups import InvitationGone

from .conftest import ADMIN_PASSWORD, EMPLOYEE_PASSWORD, login

PASSWORD_2 = "Almacen firme 77y"


def _employee(ctx, admin, username, full_name, password=EMPLOYEE_PASSWORD):
    ctx.users.create(admin, {"username": username, "full_name": full_name, "role": "employee", "password": password})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE username = ?", (username,))
    return ctx.auth.login(username, password).actor


def _token(url: str) -> str:
    return url.rsplit("/unirse/", 1)[1]


@pytest.fixture()
def group(ctx, admin):
    return ctx.groups.create(admin, {"name": "Turno mañana", "description": "Caja y bodega"})


# ------------------------------------------------------------------ escenario A: creación
def test_admin_creates_group_and_invitation_is_stored_hashed(ctx, admin, group):
    assert group["view"] == "admin" and group["group"]["public_id"].startswith("G-")
    assert group["group"]["owner_name"] == "Administradora" and group["group"]["status"] == "activo"
    inv = ctx.groups.create_invitation(admin, group["group"]["public_id"], {"expires_in_hours": 24, "max_uses": 3},
                                       "https://pos.ejemplo.com")
    token = _token(inv["url"])
    assert inv["url"].startswith("https://pos.ejemplo.com/unirse/") and len(token) >= 40
    with ctx.db.read() as conn:
        row = conn.execute("SELECT token_hash, hint FROM work_group_invitations").fetchone()
        dump = "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM work_group_invitations"))
    assert row["token_hash"] == token_hash(token) and token not in dump   # el token en claro no se guarda
    assert inv["invitation"]["status"] == "vigente" and inv["invitation"]["max_uses"] == 3


# ------------------------------------------------------------------ escenarios B y C: incorporación
def test_several_employees_join_with_same_link_without_duplicates(ctx, admin, employee, group):
    gid = group["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, gid, {"max_uses": 5})["url"])
    other = _employee(ctx, admin, "bodega", "Bodeguero Dos", PASSWORD_2)

    preview = ctx.groups.preview(employee, token)
    assert preview["group"]["name"] == "Turno mañana" and preview["group"]["owner_name"] == "Administradora"
    assert preview["my_status"] is None and not preview["is_owner"]
    assert ctx.groups.accept(employee, token)["result"] == "unido"
    assert ctx.groups.accept(other, token)["result"] == "unido"
    again = ctx.groups.accept(employee, token)                          # duplicado: no cambia nada
    assert again["result"] == "ya_integrante"

    detail = ctx.groups.get(admin, gid)
    active = [m for m in detail["members"] if m["status"] == "activo"]
    assert sorted(m["username"] for m in active) == ["bodega", "empleado"]
    assert detail["group"]["member_count"] == 2
    assert next(i for i in detail["invitations"])["uses"] == 2         # el duplicado no consumió cupo
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_group_members").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'grupo.integrante_unido'").fetchone()[0] == 2

    mine = ctx.groups.get(employee, gid)
    assert mine["view"] == "member" and mine["me"]["status"] == "activo"
    assert [m["full_name"] for m in mine["members"]] == ["Bodeguero Dos", "Empleado Uno"]
    assert "invitations" not in mine and "events" not in mine               # nada administrativo
    listing = ctx.groups.list(employee)
    assert not listing["can_manage"] and listing["member_of"][0]["owner_name"] == "Administradora"


def test_approval_policy_requires_admin_decision(ctx, admin, employee):
    g = ctx.groups.create(admin, {"name": "Con aprobación", "join_policy": "aprobacion"})
    gid = g["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, gid, {})["url"])
    assert ctx.groups.accept(employee, token)["result"] == "pendiente"
    assert ctx.groups.get(employee, gid)["members"] == []                   # pendiente: aún no ve a los integrantes
    ctx.groups.member_action(admin, gid, employee.id, "aprobar")
    assert ctx.groups.get(employee, gid)["me"]["status"] == "activo"
    with pytest.raises(ConflictError):
        ctx.groups.member_action(admin, gid, employee.id, "aprobar")


# ------------------------------------------------------------------ escenario E: seguridad
def test_invalid_expired_revoked_full_and_closed_links(ctx, admin, employee, group):
    gid = group["group"]["public_id"]
    with pytest.raises(NotFoundError):
        ctx.groups.preview(employee, "x" * 43)
    full = _token(ctx.groups.create_invitation(admin, gid, {"max_uses": 1})["url"])
    ctx.groups.accept(_employee(ctx, admin, "primero", "Primero"), full)
    with pytest.raises(InvitationGone, match="máximo"):
        ctx.groups.accept(employee, full)

    expired = _token(ctx.groups.create_invitation(admin, gid, {})["url"])
    with ctx.db.tx() as conn:
        conn.execute("UPDATE work_group_invitations SET expires_at = ? WHERE token_hash = ?",
                     (iso(now_utc() - timedelta(minutes=1)), token_hash(expired)))
    with pytest.raises(InvitationGone, match="venció"):
        ctx.groups.preview(employee, expired)

    revoked = ctx.groups.create_invitation(admin, gid, {})
    ctx.groups.revoke_invitation(admin, gid, revoked["invitation"]["id"])
    with pytest.raises(InvitationGone, match="revocó"):
        ctx.groups.accept(employee, _token(revoked["url"]))

    live = _token(ctx.groups.create_invitation(admin, gid, {})["url"])
    ctx.groups.set_open(admin, gid, False)                                  # cerrar revoca los enlaces
    with pytest.raises(InvitationGone):
        ctx.groups.accept(employee, live)
    statuses = {i["status"] for i in ctx.groups.get(admin, gid)["invitations"]}
    assert statuses <= {"revocada", "completa"}


def test_employee_cannot_administer_or_see_foreign_groups(ctx, admin, employee, group):
    gid = group["group"]["public_id"]
    with pytest.raises(PermissionDenied):
        ctx.groups.create(employee, {"name": "Mío"})
    for call in (lambda: ctx.groups.create_invitation(employee, gid, {}),
                 lambda: ctx.groups.update(employee, gid, {"name": "X"}),
                 lambda: ctx.groups.set_open(employee, gid, False),
                 lambda: ctx.groups.member_action(employee, gid, admin.id, "retirar"),
                 lambda: ctx.groups.revoke_invitation(employee, gid, 1)):
        with pytest.raises(PermissionDenied):
            call()
    with pytest.raises(NotFoundError):                                     # no es integrante: el grupo no existe
        ctx.groups.get(employee, gid)
    # Otro administrador tampoco gestiona un grupo ajeno.
    ctx.users.create(admin, {"username": "admin2", "full_name": "Otra admin", "role": "admin", "password": PASSWORD_2})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE username = 'admin2'")
    admin2 = ctx.auth.login("admin2", PASSWORD_2).actor
    with pytest.raises(NotFoundError):
        ctx.groups.create_invitation(admin2, gid, {})


def test_removed_member_needs_a_new_link_and_owner_cannot_join(ctx, admin, employee, group):
    gid = group["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, gid, {})["url"])
    with pytest.raises(ConflictError):
        ctx.groups.accept(admin, token)
    ctx.groups.accept(employee, token)
    ctx.groups.member_action(admin, gid, employee.id, "retirar")
    with pytest.raises(NotFoundError):
        ctx.groups.get(employee, gid)
    with pytest.raises(PermissionDenied, match="enlace nuevo"):
        ctx.groups.accept(employee, token)
    with ctx.db.tx() as conn:   # el enlace nuevo debe ser posterior al retiro (resolución de segundos)
        conn.execute("UPDATE work_group_members SET updated_at = ?", (iso(now_utc() - timedelta(seconds=5)),))
    fresh = _token(ctx.groups.create_invitation(admin, gid, {})["url"])
    assert ctx.groups.accept(employee, fresh)["result"] == "unido"
    ctx.groups.leave(employee, gid)                                        # salir voluntariamente
    assert ctx.groups.list(employee)["member_of"] == []


def test_brute_force_on_links_is_limited(ctx, employee):
    for _ in range(10):
        with pytest.raises(NotFoundError):
            ctx.groups.preview(employee, "y" * 43, "203.0.113.9")
    with pytest.raises(TooManyRequests):
        ctx.groups.preview(employee, "z" * 43, "203.0.113.9")


# ------------------------------------------------------------------ escenario F: presencia y reconexión
def test_disconnection_keeps_membership_and_presence_states(ctx, admin, employee, group, monkeypatch):
    gid = group["group"]["public_id"]
    ctx.groups.accept(employee, _token(ctx.groups.create_invitation(admin, gid, {})["url"]))
    member = lambda: next(m for m in ctx.groups.get(admin, gid)["members"] if m["user_id"] == employee.id)  # noqa: E731
    assert member()["connection"] == "desconocido"

    loop = asyncio.new_event_loop()
    try:
        sub, first = ctx.realtime.subscribe(employee.id, loop)
        assert first
        ctx.groups.presence_changed(employee.id, True)
        assert member()["connection"] == "conectado"
        assert ctx.realtime.unsubscribe(sub)
        ctx.groups.presence_changed(employee.id, False)
        assert member()["connection"] == "reconectando"
        import pospy.services.realtime as rt
        monkeypatch.setattr(rt, "RECONNECT_GRACE_S", 0.0)
        assert member()["connection"] == "desconectado"
        assert member()["status"] == "activo"                              # la desconexión no lo saca del grupo
        sub2, _ = ctx.realtime.subscribe(employee.id, loop)                 # reconecta
        assert member()["connection"] == "conectado"
        ctx.realtime.unsubscribe(sub2)
    finally:
        loop.close()
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_group_members WHERE user_id = ?", (employee.id,)).fetchone()[0] == 1


def test_events_reach_only_the_group_audience(ctx, admin, employee, group):
    gid = group["group"]["public_id"]
    outsider = _employee(ctx, admin, "ajeno", "Persona Ajena", PASSWORD_2)
    loop = asyncio.new_event_loop()
    try:
        subs = {name: ctx.realtime.subscribe(a.id, loop)[0] for name, a in
                (("admin", admin), ("employee", employee), ("outsider", outsider))}
        ctx.groups.accept(employee, _token(ctx.groups.create_invitation(admin, gid, {})["url"]))
        loop.run_until_complete(asyncio.sleep(0))   # entrega las llamadas programadas en el bucle
        assert subs["admin"].queue.get_nowait() == {"type": "grupo", "group": gid, "change": "integrante_unido"}
        assert subs["outsider"].queue.empty()
    finally:
        loop.close()


# ------------------------------------------------------------------ contrato HTTP
def test_http_flow_with_independent_sessions(ctx, admin, employee):
    app = create_app(ctx)
    admin_c, emp_c, anon = (TestClient(app) for _ in range(3))
    for c in (admin_c, emp_c, anon):
        c.headers.update({"X-Requested-With": "pos-py"})
    login(admin_c)
    login(emp_c, "empleado", EMPLOYEE_PASSWORD)

    created = admin_c.post("/api/groups", json={"name": "Ventas centro", "description": "Sede principal"})
    assert created.status_code == 200, created.text
    gid = created.json()["group"]["public_id"]
    inv = admin_c.post(f"/api/groups/{gid}/invitations", json={"expires_in_hours": 48, "max_uses": 2}).json()
    token = _token(inv["url"])
    assert inv["url"].startswith("http://testserver/unirse/") and inv["invite_base"]["reachable_from_internet"] is False

    assert anon.get(f"/api/invitations/{token}").status_code == 401        # sin sesión no hay datos del grupo
    assert anon.get(f"/api/groups/{gid}").status_code == 401
    assert emp_c.post("/api/groups", json={"name": "X"}).status_code == 403
    assert emp_c.get(f"/api/groups/{gid}").status_code == 404
    assert emp_c.post(f"/api/groups/{gid}/invitations", json={}).status_code == 403
    assert emp_c.post(f"/api/groups/{gid}/members/{admin.id}/retirar").status_code == 403
    # El frontend no puede imponer rol, grupo ni permisos.
    assert admin_c.post("/api/groups", json={"name": "Y", "owner_id": employee.id}).status_code == 422
    assert emp_c.post(f"/api/invitations/{token}/accept", json={"role": "admin"}).status_code == 200
    assert emp_c.post(f"/api/invitations/{token}/accept").json()["result"] == "ya_integrante"
    me = emp_c.get(f"/api/groups/{gid}").json()
    assert me["view"] == "member" and me["me"]["status"] == "activo" and me["group"]["owner_name"] == "Administradora"
    assert "gestion.usuarios" not in emp_c.get("/api/me").json()["user"]["permissions"]

    detail = admin_c.get(f"/api/groups/{gid}").json()
    assert [m["username"] for m in detail["members"]] == ["empleado"]
    gone = emp_c.get("/api/invitations/" + "q" * 43)
    assert gone.status_code == 404 and "no es válido" in gone.json()["detail"]
    revoke = admin_c.post(f"/api/groups/{gid}/invitations/{inv['invitation']['id']}/revoke")
    assert revoke.status_code == 200
    gone = emp_c.get(f"/api/invitations/{token}")
    assert gone.status_code == 410 and gone.json()["fields"]["invitacion"] == "revocada"
    assert emp_c.post(f"/api/groups/{gid}/leave").status_code == 200


def test_requests_through_a_proxy_are_never_local(ctx, client):
    """Detrás de un túnel o proxy local las conexiones vienen de 127.0.0.1: no deben valer como locales."""
    direct = client.get("/api/setup/status").json()
    assert direct["local"] is True
    proxied = client.get("/api/setup/status", headers={"X-Forwarded-For": "198.51.100.7"}).json()
    assert proxied["local"] is False and proxied["direct_access"] is False
    cf = client.get("/api/auth/profiles", headers={"CF-Connecting-IP": "198.51.100.7"})
    assert cf.status_code == 403
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD},
                    headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.7"})
    assert "secure" in r.headers["set-cookie"].lower()                        # cookie Secure por HTTPS del túnel


def test_tunnel_without_forward_headers_is_not_local(ctx, admin):
    """ssh -R / localhost.run: la conexión viene de 127.0.0.1 sin cabeceras de proxy, pero con el Host público."""
    from starlette.requests import Request as StarletteRequest

    from pospy.api.deps import is_https, is_local

    app = create_app(ctx)

    def req(host: str, client_host: str = "127.0.0.1") -> StarletteRequest:
        return StarletteRequest({"type": "http", "method": "GET", "path": "/", "scheme": "http", "app": app,
                                 "headers": [(b"host", host.encode())], "client": (client_host, 50000), "query_string": b""})

    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"):
        assert is_local(req(host)) is True, host
    for host in ("abc123.lhr.life", "pos.miempresa.com", "127.0.0.1.nip.io", ""):
        assert is_local(req(host)) is False, host
    assert is_local(req("localhost", client_host="192.168.1.30")) is False

    assert is_https(req("pos.miempresa.com")) is False
    ctx.settings.update("grupos", {"public_url": "https://pos.miempresa.com"}, admin)
    assert is_https(req("pos.miempresa.com")) is True                         # túnel HTTPS que no avisa el esquema
    assert is_https(req("otro.ejemplo.com")) is False
    assert is_https(req("pos.miempresa.com", client_host="203.0.113.9")) is False


def test_half_open_channel_is_dropped_only_for_clients_that_ping():
    from pospy.services.realtime import RealtimeHub

    hub = RealtimeHub()
    loop = asyncio.new_event_loop()
    try:
        sub, _ = hub.subscribe(5, loop)
        sub.opened_at -= 120
        assert hub.is_stale(sub, 30) is False          # cliente sin ping (versión anterior): no se corta
        hub.ping(5)
        assert hub.is_stale(sub, 30) is False
        hub._pinged_at[5] -= 31
        assert hub.is_stale(sub, 30) is True           # dejó de enviar pings: el proxy mantiene un canal huérfano
        fresh, _ = hub.subscribe(5, loop)
        assert hub.is_stale(fresh, 30) is False        # una conexión recién abierta tiene margen
    finally:
        loop.close()


def test_public_url_setting_builds_links(ctx, admin, group):
    from pospy.core.errors import ValidationError
    with pytest.raises(ValidationError):
        ctx.settings.update("grupos", {"public_url": "http://192.168.1.20:8000"}, admin)
    ctx.settings.update("grupos", {"public_url": "https://pos.miempresa.com/"}, admin)
    inv = ctx.groups.create_invitation(admin, group["group"]["public_id"], {}, "http://127.0.0.1:8000")
    assert inv["url"].startswith("https://pos.miempresa.com/unirse/")
    assert inv["invite_base"]["source"] == "configuracion"
    ctx.settings.update("grupos", {"public_url": ""}, admin)
    local = ctx.groups.invite_base_info("http://127.0.0.1:8000")
    assert local["reachable_from_internet"] is False and local["source"] == "navegador"
