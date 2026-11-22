"""Auditoría de seguridad (prompt de auditoría integral): pruebas de regresión de autenticación, autorización,
manipulación de datos, sesiones, límites, cabeceras, auditoría y equipos autorizados.

Recorren TODA la API publicada (OpenAPI): una ruta nueva sin protección o que un empleado pueda usar sin estar en
la lista revisada hace fallar estas pruebas (denegación por defecto)."""
from __future__ import annotations

import base64
import re

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.core.errors import ValidationError

from .conftest import ADMIN_PASSWORD, EMPLOYEE_PASSWORD, key, login

# Rutas públicas (sin sesión) a propósito; todo lo demás exige identidad.
PUBLIC = {
    "GET /api/health", "GET /api/setup/status", "POST /api/setup", "POST /api/setup/start", "POST /api/auth/open",
    "POST /api/auth/login", "POST /api/auth/logout", "GET /api/appearance", "GET /api/devices/policy",
    "POST /api/devices/challenge", "POST /api/devices/request",
}
# Lo que un empleado con los permisos por defecto puede completar (revisado en la auditoría: todo es de su trabajo
# o de solo lectura de su propio alcance). Cualquier otra ruta debe rechazarse.
EMPLOYEE_OK = {
    "GET /api/activity",            # solo SUS operaciones (sin permiso de auditoría)
    "GET /api/appearance", "GET /api/categories", "GET /api/devices/current", "GET /api/devices/policy",
    "GET /api/document-types", "GET /api/document-types/{type_id}", "GET /api/documents", "GET /api/groups",
    "GET /api/health", "GET /api/inventories", "GET /api/inventories/permissions", "GET /api/inventory/columns",
    "GET /api/inventory/dashboard", "GET /api/inventory/returns", "GET /api/me", "GET /api/movements", "GET /api/notes",
    "GET /api/observations", "GET /api/observations/flags", "GET /api/observations/meta", "GET /api/observations/products",
    "GET /api/observations/products/{product_id}", "GET /api/payment-methods", "GET /api/permissions/catalog",
    "GET /api/prefs", "GET /api/print-templates", "GET /api/print-templates/catalog", "GET /api/printing/jobs",
    "GET /api/printing/printers", "GET /api/products", "GET /api/products/meta", "GET /api/products/{product_id}",
    "GET /api/sales", "GET /api/sales/summary", "GET /api/settings/public", "GET /api/setup/status", "GET /api/tasks",
    "POST /api/devices/challenge", "POST /api/realtime/ping", "PUT /api/prefs",
}


def _client(ctx, user=None, password=None, headers=None) -> TestClient:
    c = TestClient(create_app(ctx))
    c.headers.update({"X-Requested-With": "pos-py", "Idempotency-Key": "auditoria-0001", **(headers or {})})
    if user:
        login(c, user, password)
    return c


def _operations(c: TestClient):
    for path, ops in c.get("/api/openapi.json").json()["paths"].items():
        for method in ops:
            if "stream" in path:          # canal de eventos (flujo infinito): se prueba aparte
                continue
            yield method.upper(), path, re.sub(r"\{[^}]+\}", "1", path)


# ------------------------------------------------------------------ autenticación y denegación por defecto
def test_every_route_requires_a_session_except_the_public_ones(client):
    client.headers.update({"Idempotency-Key": "auditoria-0001"})
    exposed = set()
    for method, path, url in _operations(client):
        r = client.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
        if r.status_code != 401:
            exposed.add(f"{method} {path}")
    assert exposed <= PUBLIC, sorted(exposed - PUBLIC)
    assert client.get("/api/realtime/stream").status_code == 401


def test_employee_reaches_only_reviewed_operations(ctx, admin, employee, product):
    c = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    reached = set()
    for method, path, url in _operations(c):
        if path == "/api/auth/logout":
            continue
        r = c.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
        if r.status_code < 300:
            reached.add(f"{method} {path}")
    assert reached <= EMPLOYEE_OK, sorted(reached - EMPLOYEE_OK)


ADMIN_ONLY_CALLS = [
    ("GET", "/api/users", None), ("POST", "/api/users", {"username": "nuevo", "full_name": "N", "role": "admin", "password": "Clave segura 2026"}),
    ("PUT", "/api/settings/empresa", {"name": "Hackeada"}), ("PUT", "/api/settings/seguridad", {"session_idle_minutes": 480}),
    ("GET", "/api/backups", None), ("POST", "/api/backups", {}), ("GET", "/api/integrations", None),
    ("PUT", "/api/appearance/theme", {"enabled": False}), ("GET", "/api/devices", None), ("PUT", "/api/devices/policy", {"enforced": False}),
    ("PUT", "/api/devices/1/status", {"status": "autorizado"}), ("POST", "/api/groups", {"name": "G"}),
    ("POST", "/api/print-templates", {"name": "X", "kind": "venta"}), ("POST", "/api/document-types", {"name": "X"}),
    ("GET", "/api/reports/sales", None), ("GET", "/api/reports/movements", None),
]


@pytest.mark.parametrize(("method", "url", "body"), ADMIN_ONLY_CALLS)
def test_employee_cannot_use_administrative_endpoints(ctx, admin, employee, method, url, body):
    c = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    r = c.request(method, url, json=body)
    assert r.status_code in (403, 404), (url, r.status_code, r.text[:200])
    if r.status_code == 403:
        assert "solicítela a un administrador" in r.json()["detail"]      # mensaje claro, sin autoelevación


def test_employee_cannot_escalate_privileges(ctx, admin, employee):
    c = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    me = c.get("/api/me").json()["user"]
    assert c.put(f"/api/users/{me['id']}", json={"role": "admin"}).status_code in (403, 404, 422)
    assert c.put(f"/api/users/{me['id']}/permissions", json={"permissions": ["gestion.usuarios"]}).status_code in (403, 404, 405, 422)
    assert c.put("/api/prefs", json={"role": "admin", "permissions": ["gestion.usuarios"]}).status_code in (200, 422)
    again = c.get("/api/me").json()["user"]
    assert again["role"] == "employee" and "gestion.usuarios" not in again["permissions"]
    # Ni el administrador puede dar a un empleado permisos exclusivos de administración.
    with pytest.raises(ValidationError, match="exclusivos de administradores"):
        ctx.users.update(admin, employee.id, {"permissions": ["ventas.vender", "gestion.usuarios", "gestion.configuracion"]})
    limited = ctx.auth.login("empleado", EMPLOYEE_PASSWORD).actor
    assert not (limited.can("gestion.usuarios") or limited.can("gestion.configuracion"))


# ------------------------------------------------------------------ manipulación de datos sensibles
def test_prices_totals_discounts_and_stock_are_decided_by_the_server(ctx, admin, employee, product, cash_id):
    c = _client(ctx, "admin", ADMIN_PASSWORD)
    pay = [{"method_id": cash_id, "amount": "18000"}]
    for line in ({"product_id": product["id"], "qty": "1", "unit_price": "1"}, {"product_id": product["id"], "qty": "1", "total": "1"},
                 {"product_id": product["id"], "qty": "-1"}, {"product_id": product["id"], "qty": "1", "discount_pct": "21"}):
        r = c.post("/api/sales", json={"lines": [line], "payments": pay}, headers={"Idempotency-Key": key()})
        assert r.status_code == 422, (line, r.text[:200])
    r = c.post("/api/sales", json={"lines": [{"product_id": product["id"], "qty": "1"}], "payments": pay, "total": "1"},
               headers={"Idempotency-Key": key()})
    assert r.status_code == 422                                           # campos desconocidos: rechazados
    ok = c.post("/api/sales", json={"lines": [{"product_id": product["id"], "qty": "1"}], "payments": pay},
                headers={"Idempotency-Key": key()})
    assert ok.status_code == 200 and ok.json()["total"] == "18000.00"   # precio del catálogo, no del cliente
    assert c.put(f"/api/products/{product['id']}", json={"stock": "999"}).status_code == 422
    e = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    r = e.post("/api/sales", json={"lines": [{"product_id": product["id"], "qty": "1", "discount_pct": "5"}], "payments": pay},
               headers={"Idempotency-Key": key()})
    assert r.status_code in (403, 422) and "permiso" in r.text           # sin «ventas.descuento»
    assert e.put(f"/api/products/{product['id']}", json={"price": "1"}).status_code in (403, 404)


def test_repeated_operation_is_not_registered_twice(ctx, admin, product, cash_id):
    c = _client(ctx, "admin", ADMIN_PASSWORD)
    body = {"lines": [{"product_id": product["id"], "qty": "1"}], "payments": [{"method_id": cash_id, "amount": "18000"}]}
    k = key()
    a = c.post("/api/sales", json=body, headers={"Idempotency-Key": k}).json()
    b = c.post("/api/sales", json=body, headers={"Idempotency-Key": k}).json()
    assert a["id"] == b["id"]
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 1


# ------------------------------------------------------------------ sesiones
def test_sessions_logout_tampering_revocation_and_deactivation(ctx, admin, employee):
    c = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    cookie = c.cookies.get("pospy_session")
    assert c.get("/api/me").status_code == 200
    stolen = _client(ctx)
    stolen.cookies.set("pospy_session", cookie[:-2] + ("AA" if not cookie.endswith("AA") else "BB"))
    assert stolen.get("/api/me").status_code == 401                       # token alterado
    c.post("/api/auth/logout")
    replay = _client(ctx)
    replay.cookies.set("pospy_session", cookie)
    assert replay.get("/api/me").status_code == 401                       # reutilizar la sesión cerrada
    d = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    ctx.users.update(admin, employee.id, {"active": False})
    assert d.get("/api/me").status_code == 401                            # cuenta desactivada: sesión revocada


def test_login_rate_limit_by_origin_and_account_lockout(ctx, admin):
    c = _client(ctx)
    for i in range(20):
        assert c.post("/api/auth/login", json={"username": f"nadie{i}", "password": "x"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 429                                            # incluso con la contraseña correcta
    other = _client(ctx, headers={"X-Forwarded-For": "203.0.113.9"})
    assert other.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'sesion.fallida'").fetchone()[0] == 20


def test_security_headers_and_api_docs_only_on_the_server(client):
    r = client.get("/api/health")
    for h, v in (("x-content-type-options", "nosniff"), ("x-frame-options", "DENY"), ("referrer-policy", "no-referrer"),
                 ("cross-origin-opener-policy", "same-origin")):
        assert r.headers[h] == v
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and "camera=()" in r.headers["permissions-policy"]
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/openapi.json", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 404
    assert client.get("/api/docs", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 404
    assert client.post("/api/auth/login", json={}, headers={"X-Requested-With": ""}).status_code == 403   # CSRF


def test_denied_access_is_audited(ctx, admin, employee):
    c = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    assert c.get("/api/users").status_code == 403
    with ctx.db.read() as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE action = 'seguridad.acceso_denegado' ORDER BY id DESC").fetchone()
    assert row["username"] == "empleado" and row["entity_id"] == "GET /api/users" and "gestion.usuarios" in row["details"]
    with ctx.db.tx() as conn, pytest.raises(Exception, match="no se modifica|no se borra|auditor"):
        conn.execute("DELETE FROM audit_log")                             # registro protegido contra manipulación


def test_reports_only_for_audit_permission_and_current_inventory(ctx, admin, product, cash_id):
    ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1"}],
                               "payments": [{"method_id": cash_id, "amount": "18000"}]}, key())
    ctx.groups.create(admin, {"name": "Sucursal norte"})
    with ctx.db.read() as conn:
        group_key = conn.execute("SELECT public_id FROM work_groups WHERE name = 'Sucursal norte'").fetchone()[0]
    other = ctx.inventories.create(admin, {"name": "Otro negocio", "group": group_key})
    c = _client(ctx, "admin", ADMIN_PASSWORD)
    assert c.get("/api/reports/sales").json()["sales"] == 1
    r = c.get("/api/reports/sales", headers={"X-Inventory": other["key"]})
    assert r.status_code == 200 and r.json()["sales"] == 0               # no mezcla inventarios


# ------------------------------------------------------------------ equipos autorizados
class Device:
    """Equipo simulado: par de claves ECDSA P-256 y firma en formato WebCrypto (r||s de 64 bytes)."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.spki = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()

    def proof(self, c: TestClient, nonce: str | None = None) -> dict:
        nonce = nonce or c.post("/api/devices/challenge").json()["nonce"]
        r, s = decode_dss_signature(self.key.sign(nonce.encode(), ec.ECDSA(hashes.SHA256())))
        return {"public_key": self.spki, "nonce": nonce, "signature": base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()}


REMOTE = {"X-Forwarded-For": "198.51.100.7"}      # simula otro computador de la red (no el equipo servidor)


def _remote_login(ctx, user, password, device: Device | None = None):
    c = _client(ctx, headers=REMOTE)
    body = {"username": user, "password": password}
    if device:
        body["device"] = device.proof(c)
    return c, c.post("/api/auth/login", json=body)


def test_device_restriction_full_flow(ctx, admin, employee):
    admin_pc, emp_pc, intruder = Device(), Device(), Device()
    # Sin restricción, todo sigue igual que antes (instalaciones existentes).
    assert _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD)[1].status_code == 200
    # El administrador no puede activarla desde un equipo no autorizado (evita quedar fuera).
    a, r = _remote_login(ctx, "admin", ADMIN_PASSWORD)
    assert a.put("/api/devices/policy", json={"enforced": True}).status_code == 422
    # Autoriza SU equipo (prueba de posesión de la clave) y activa la restricción.
    reg = a.post("/api/devices/register", json={"name": "Caja principal", "device": admin_pc.proof(a)})
    assert reg.status_code == 200 and reg.json()["device"]["status"] == "autorizado"
    assert a.put("/api/devices/policy", json={"enforced": True}).json()["enforced"] is True
    assert a.get("/api/me").status_code == 200                            # su sesión quedó vinculada al equipo
    # Empleado desde un equipo sin identificar: rechazado aunque la contraseña sea correcta.
    _, r = _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD)
    assert r.status_code == 403 and r.json()["fields"]["device"] == "sin_prueba"
    _, r = _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD, emp_pc)
    assert r.status_code == 403 and r.json()["fields"]["device"] == "no_registrado"
    # Solicita autorización: queda pendiente (no se autoriza solo).
    s = _client(ctx, headers=REMOTE)
    req = s.post("/api/devices/request", json={"username": "empleado", "password": EMPLOYEE_PASSWORD, "name": "Caja 2",
                                               "device": emp_pc.proof(s)})
    assert req.json()["device"]["status"] == "pendiente"
    assert s.post("/api/devices/request", json={"username": "empleado", "password": "mala", "name": "X",
                                                "device": intruder.proof(s)}).status_code == 401
    _, r = _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD, emp_pc)
    assert r.json()["fields"]["device"] == "pendiente"
    # El administrador lo autoriza: ahora entra.
    devices = a.get("/api/devices").json()["devices"]
    emp_dev = next(d for d in devices if d["name"] == "Caja 2")
    assert a.put(f"/api/devices/{emp_dev['id']}/status", json={"status": "autorizado"}).status_code == 200
    e, r = _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD, emp_pc)
    assert r.status_code == 200 and e.get("/api/products").status_code == 200   # conserva sus funciones
    # El empleado no puede autorizar equipos.
    assert e.put(f"/api/devices/{emp_dev['id']}/status", json={"status": "autorizado"}).status_code == 403
    # Copiar la cookie a otro computador no sirve si el equipo se revoca; revocar cierra la sesión YA.
    a.put(f"/api/devices/{emp_dev['id']}/status", json={"status": "revocado"})
    assert e.get("/api/products").status_code in (401, 403)
    _, r = _remote_login(ctx, "empleado", EMPLOYEE_PASSWORD, emp_pc)
    assert r.json()["fields"]["device"] == "revocado"
    # Desafío reutilizado o firma de otra clave: rechazados.
    c = _client(ctx, headers=REMOTE)
    p = admin_pc.proof(c)
    assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD, "device": p}).status_code == 200
    c2 = _client(ctx, headers=REMOTE)
    assert c2.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD, "device": p}).status_code == 403
    forged = {**admin_pc.proof(c2), "public_key": admin_pc.spki}
    forged["signature"] = intruder.proof(c2, forged["nonce"])["signature"] if False else base64.b64encode(b"\x01" * 64).decode()
    assert c2.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD, "device": forged}).status_code == 403
    # El equipo servidor (petición local) queda exento: el negocio nunca queda bloqueado.
    assert _client(ctx, "empleado", EMPLOYEE_PASSWORD).get("/api/me").status_code == 200
    # Eventos registrados.
    with ctx.db.read() as conn:
        actions = {r[0] for r in conn.execute("SELECT action FROM audit_log")}
    assert {"dispositivo.solicitado", "dispositivo.autorizado", "dispositivo.revocado", "sesion.equipo_rechazado",
            "seguridad.dispositivos_activada"} <= actions


def test_device_registered_by_employee_session_stays_pending(ctx, admin, employee):
    pc = Device()
    e = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    r = e.post("/api/devices/register", json={"name": "Portátil", "device": pc.proof(e)})
    assert r.status_code == 200 and r.json()["device"]["status"] == "pendiente"
    assert e.get("/api/devices").status_code == 403
