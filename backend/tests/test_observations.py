"""Observaciones de inventario: CRUD, seguimiento, filtros, indicadores, permisos, integridad y persistencia."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext

from .conftest import EMPLOYEE_PASSWORD, key, login

TODAY = date.today()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def inventory_snapshot(app) -> dict:
    """Lo que una observación NUNCA debe tocar: existencias, costos, movimientos, compras, ventas y asientos."""
    with app.db.read() as conn:
        return {
            "products": [tuple(r) for r in conn.execute(
                "SELECT id, stock_milli, cost_cents, price_cents, active, version FROM products ORDER BY id")],
            **{t: conn.execute(f"SELECT COUNT(*), COALESCE(SUM(id), 0) FROM {t}").fetchone()[:]
               for t in ("inventory_movements", "sales", "payables", "journal_entries")},
        }


@pytest.fixture()
def c(client):
    login(client)
    return client


@pytest.fixture()
def meta(c):
    return c.get("/api/observations/meta").json()


def cat(meta, code: str) -> int:
    return next(x["id"] for x in meta["categories"] if x["code"] == code)


@pytest.fixture()
def obs(c, product, meta):
    r = c.post("/api/observations", json={"product_id": product["id"], "category_id": cat(meta, "diferencia_inventario"),
                                          "priority": "media", "description": "Se detectaron 5 unidades faltantes en el conteo.",
                                          "qty": "5", "reference_doc": "REC-0045"})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 1. crear asociada a un producto
def test_create_links_existing_product_and_records_history(c, product, meta, obs, ctx):
    assert obs["product_id"] == product["id"] and obs["status"] == "pendiente" and obs["qty"] == "5"
    assert obs["code"] == f"OBS-{obs['id']:05d}" and obs["responsible_name"] == "Administradora"
    assert obs["product"]["code"] == "MART-01" and obs["product"]["stock"] == "10"
    assert obs["product"]["cost"] == "10000.00"            # el administrador ve el costo
    assert obs["detected_on"] == TODAY.isoformat()
    assert [e["kind"] for e in obs["events"]] == ["creada"]
    with ctx.db.read() as conn:   # no copia datos del producto: solo su id
        cols = {r[1] for r in conn.execute("PRAGMA table_info(inventory_observations)")}
    assert not {"code", "product_code", "product_description", "stock_milli"} & cols
    assert len(meta["categories"]) == 10 and [p["value"] for p in meta["priorities"]] == ["baja", "media", "alta", "critica"]


def test_required_fields_and_validation(c, product, meta):
    base = {"product_id": product["id"], "category_id": cat(meta, "otro"), "priority": "baja", "description": "Detalle válido"}
    for missing, field in (("product_id", "product_id"), ("category_id", "category_id"), ("priority", "priority"),
                           ("description", "description")):
        r = c.post("/api/observations", json={k: v for k, v in base.items() if k != missing})
        assert r.status_code == 422 and field in r.json()["fields"], (missing, r.text)
    bad = [({"product_id": 99999}, "product_id", 404), ({"category_id": 99999}, "category_id", 422),
           ({"priority": "urgente"}, None, 422), ({"description": "x" * 2001}, None, 422),
           ({"description": "abc"}, "description", 422), ({"qty": "-2"}, "qty", 422),
           ({"detected_on": (TODAY + timedelta(days=5)).isoformat()}, "detected_on", 422),
           ({"follow_up_date": (TODAY - timedelta(days=5)).isoformat()}, "follow_up_date", 422),
           ({"supplier_id": 9999}, "supplier_id", 422), ({"assigned_to": 9999}, "assigned_to", 422),
           ({"detected_on": "15/11/2026"}, "detected_on", 422), ({"extra": 1}, None, 422)]
    for patch, field, status in bad:
        r = c.post("/api/observations", json={**base, **patch})
        assert r.status_code == status, (patch, r.text)
        if field:
            assert field in r.json().get("fields", {}), (patch, r.text)
    # Caracteres de control eliminados (sanitización), saltos de línea conservados.
    r = c.post("/api/observations", json={**base, "description": "Línea 1\x00\x07\nLínea 2"})
    assert r.json()["description"] == "Línea 1\nLínea 2"


# ------------------------------------------------------------------ 2-3. búsquedas
def test_search_by_name_code_and_id(c, ctx, admin, product, meta, obs):
    other = ctx.inventory.create(admin, {"code": "7701234567890", "description": "Aceite 20W50", "price": "30000", "cost": "20000"})
    c.post("/api/observations", json={"product_id": other["id"], "category_id": cat(meta, "reposicion_pendiente"),
                                      "priority": "alta", "description": "Pedir reposición al proveedor."})
    ids = lambda q: [o["product_code"] for o in c.get("/api/observations", params={"q": q}).json()["items"]]  # noqa: E731
    assert ids("martillo") == ["MART-01"]
    assert ids("aceite") == ["7701234567890"]
    assert ids("MART-01") == ["MART-01"]
    assert ids("77012345") == ["7701234567890"]          # código de barras parcial
    assert ids(obs["code"]) == ["MART-01"] and ids(f"#{obs['id']}") == ["MART-01"]
    assert "MART-01" in ids(str(obs["id"]))              # un número busca id y también códigos
    assert ids("REC-0045") == ["MART-01"]                 # documento de referencia
    assert ids("100%_") == []                             # comodines escapados


# ------------------------------------------------------------------ 4, 5, 6, 7, 8. editar, prioridad, estado, comentarios, historial
def test_follow_up_lifecycle(c, obs):
    oid = obs["id"]
    r = c.put(f"/api/observations/{oid}", json={"priority": "critica", "comment": "Afecta las ventas", "version": obs["version"]})
    assert r.status_code == 200 and r.json()["priority"] == "critica"
    v = r.json()["version"]
    assert c.put(f"/api/observations/{oid}", json={"priority": "alta", "version": obs["version"]}).status_code == 409
    r = c.post(f"/api/observations/{oid}/status", json={"status": "en_proceso", "comment": "Se inició revisión de entradas.",
                                                        "version": v})
    assert r.status_code == 200 and r.json()["status"] == "en_proceso"
    assert c.post(f"/api/observations/{oid}/status", json={"status": "en_proceso"}).status_code == 422
    r = c.post(f"/api/observations/{oid}/comments", json={"comment": "Error en el registro de recepción."})
    assert r.status_code == 200 and r.json()["kind"] == "comentario" and r.json()["user_name"] == "Administradora"
    assert c.post(f"/api/observations/{oid}/comments", json={"comment": "   "}).status_code == 422
    r = c.put(f"/api/observations/{oid}", json={"description": "Faltaban 5 unidades por error de recepción."})
    assert r.json()["description"].startswith("Faltaban")
    r = c.post(f"/api/observations/{oid}/status", json={"status": "resuelta", "comment": "Corregido."})
    assert r.json()["status"] == "resuelta" and r.json()["resolved_at"]
    # Cerrar y reabrir exigen motivo.
    assert c.post(f"/api/observations/{oid}/status", json={"status": "cerrada"}).status_code == 422
    assert c.post(f"/api/observations/{oid}/status", json={"status": "cerrada", "comment": "Verificado"}).json()["closed_at"]
    assert c.post(f"/api/observations/{oid}/status", json={"status": "pendiente"}).status_code == 422
    r = c.post(f"/api/observations/{oid}/status", json={"status": "pendiente", "comment": "Reapareció la diferencia"})
    assert r.json()["status"] == "pendiente" and r.json()["resolved_at"] is None and r.json()["closed_at"] is None

    events = c.get(f"/api/observations/{oid}").json()["events"]
    assert [e["kind"] for e in events] == ["creada", "prioridad", "estado", "comentario", "edicion", "estado", "estado", "estado"]
    assert (events[1]["from_value"], events[1]["to_value"], events[1]["comment"]) == ("media", "critica", "Afecta las ventas")
    assert (events[2]["from_value"], events[2]["to_value"]) == ("pendiente", "en_proceso")
    assert events[4]["details"]["description"]["antes"].startswith("Se detectaron")
    assert all(e["user_name"] == "Administradora" and e["created_at"] for e in events)
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)       # cronológico


def test_history_is_immutable_and_product_cannot_change(c, ctx, obs, admin):
    with ctx.db.tx() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE inventory_observation_events SET comment = 'x'")
    with ctx.db.tx() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM inventory_observation_events")
    with ctx.db.tx() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM inventory_observations")
    other = ctx.inventory.create(admin, {"code": "OTRO", "description": "Otro", "price": "1"})
    r = c.put(f"/api/observations/{obs['id']}", json={"product_id": other["id"]})
    assert r.status_code == 422 and "product_id" in r.json()["fields"]


# ------------------------------------------------------------------ 9. adjuntos
def test_attachments(c, ctx, obs):
    oid = obs["id"]
    r = c.post(f"/api/observations/{oid}/files", files={"file": ("../../foto caja.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["original_name"] == "foto caja.png"
    stored = list((ctx.config.data_dir / "observaciones" / str(oid)).iterdir())
    assert len(stored) == 1 and stored[0].name != "foto caja.png"
    assert c.get(f"/api/observations/{oid}/files/{fid}/download").content == PNG
    detail = c.get(f"/api/observations/{oid}").json()
    assert detail["files"][0]["available"] and "stored_name" not in detail["files"][0]
    for name, content in (("virus.exe", b"MZ..."), ("falso.pdf", b"no soy pdf"), ("vacio.png", b"")):
        assert c.post(f"/api/observations/{oid}/files", files={"file": (name, content, "x")}).status_code == 422, name
    assert c.post(f"/api/observations/{oid}/files",
                  files={"file": ("grande.pdf", b"%PDF-" + b"0" * (11 * 1024 * 1024), "x")}).status_code == 422
    assert c.delete(f"/api/observations/{oid}/files/{fid}").status_code == 200
    assert c.get(f"/api/observations/{oid}/files/{fid}/download").status_code == 404
    kinds = [e["kind"] for e in c.get(f"/api/observations/{oid}").json()["events"]]
    assert kinds[-2:] == ["adjunto", "adjunto_eliminado"]
    # Un archivo de otra observación no se alcanza por id.
    fid2 = c.post(f"/api/observations/{oid}/files", files={"file": ("a.png", PNG, "x")}).json()["id"]
    other = c.post("/api/observations", json={"product_id": obs["product_id"], "category_id": obs["category_id"],
                                              "priority": "baja", "description": "Otra observación"}).json()
    assert c.get(f"/api/observations/{other['id']}/files/{fid2}/download").status_code == 404


# ------------------------------------------------------------------ 10. integración con la ficha del producto
def test_product_integration(c, ctx, admin, product, meta, obs):
    crit = cat(meta, "producto_defectuoso")
    c.post("/api/observations", json={"product_id": product["id"], "category_id": crit, "priority": "critica",
                                      "description": "Lote defectuoso"})
    plain = ctx.inventory.create(admin, {"code": "SIN-OBS", "description": "Sin novedades", "price": "1"})
    r = c.get("/api/observations", params={"product_id": product["id"]}).json()
    assert r["total"] == 2 and {o["product_id"] for o in r["items"]} == {product["id"]}
    context = c.get(f"/api/observations/products/{product['id']}").json()
    assert (context["open_observations"], context["critical_observations"], context["total_observations"]) == (2, 1, 2)
    flags = c.get("/api/observations/flags", params={"ids": f"{product['id']},{plain['id']}"}).json()
    assert flags == {str(product["id"]): {"open": 2, "critical": 1}}
    assert c.get("/api/observations/flags", params={"ids": "a,b"}).status_code == 422
    # La búsqueda de productos para asociar encuentra por nombre, código y referencia, incluso inactivos.
    ctx.inventory.update(admin, plain["id"], {"active": False, "version": plain["version"]})
    found = c.get("/api/observations/products", params={"q": "sin-obs"}).json()
    assert found[0]["code"] == "SIN-OBS" and found[0]["active"] == 0
    assert c.get("/api/observations/products", params={"q": ""}).json() == []


def test_last_supplier_comes_from_real_purchases(c, ctx, admin, product):
    sid = c.post("/api/parties/proveedores", json={"name": "Distribuidora Andina"}).json()["id"]
    assert c.get(f"/api/observations/products/{product['id']}").json()["last_supplier"] is None
    ctx.inventory.register_movement(admin, product["id"], {"kind": "entrada", "qty": "2", "unit_cost": "9000", "reason": "Compra",
                                                           "counterpart": "compra_credito", "supplier_id": sid,
                                                           "invoice_number": "FV-1"}, key())
    assert c.get(f"/api/observations/products/{product['id']}").json()["last_supplier"] == {"id": sid, "name": "Distribuidora Andina"}


# ------------------------------------------------------------------ 11-12. indicadores y filtros combinados
def test_dashboard_metrics_and_combined_filters(c, ctx, admin, product, meta):
    sid = c.post("/api/parties/proveedores", json={"name": "Proveedor Uno"}).json()["id"]
    ctx.users.create(admin, {"username": "bodega", "full_name": "Bodeguero", "role": "employee", "password": EMPLOYEE_PASSWORD})
    uid = next(u["id"] for u in c.get("/api/observations/meta").json()["users"] if u["full_name"] == "Bodeguero")
    def mk(priority, category, **extra):
        r = c.post("/api/observations", json={"product_id": product["id"], "category_id": cat(meta, category),
                                              "priority": priority, "description": f"Observación {priority} {category}", **extra})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    a = mk("critica", "problema_proveedor", supplier_id=sid, assigned_to=uid, detected_on=(TODAY - timedelta(days=10)).isoformat())
    b = mk("critica", "faltante")
    d = mk("baja", "faltante", follow_up_date=TODAY.isoformat())
    e = mk("alta", "otro")
    c.post(f"/api/observations/{b}/status", json={"status": "en_proceso"})
    c.post(f"/api/observations/{d}/status", json={"status": "resuelta"})
    c.post(f"/api/observations/{e}/delete", json={"reason": "Duplicada"})

    data = c.get("/api/observations").json()
    assert data["metrics"] == {"total": 3, "pendiente": 1, "en_proceso": 1, "resuelta": 1, "cerrada": 0, "criticas": 2,
                               "recientes": 3, "seguimiento_vencido": 0}
    ids = lambda **p: [o["id"] for o in c.get("/api/observations", params=p).json()["items"]]  # noqa: E731
    assert ids() == [d, b, a]                                   # más recientes primero
    assert ids(sort="antiguas") == [a, b, d]
    assert ids(sort="prioridad")[-1] == d
    assert ids(sort="estado") == [a, b, d]
    assert ids(quick="pendientes") == [a] and ids(quick="criticas") == [b, a]
    assert ids(quick="en_proceso") == [b] and ids(quick="resueltas") == [d] and ids(quick="recientes") == [d, b, a]
    assert ids(priority="critica", status="en_proceso") == [b]
    assert ids(category_id=cat(meta, "faltante"), priority="baja") == [d]
    assert ids(supplier_id=sid) == [a] and ids(responsible_id=uid) == [a]
    assert ids(responsible_id=admin.id, quick="criticas") == [b]
    assert ids(date_from=TODAY.isoformat()) == [d, b]
    assert ids(date_to=(TODAY - timedelta(days=1)).isoformat()) == [a]
    assert ids(q="martillo", priority="critica", date_from=(TODAY - timedelta(days=30)).isoformat()) == [b, a]
    assert c.get("/api/observations", params={"date_from": "2026-11-10", "date_to": "2026-11-01"}).status_code == 422
    assert c.get("/api/observations", params={"quick": "raro"}).status_code == 422
    assert c.get("/api/observations", params={"status": "raro"}).status_code == 422


# ------------------------------------------------------------------ 13. permisos
def test_permissions(client, ctx, admin, employee, obs):
    client.cookies.clear()
    login(client, "empleado", EMPLOYEE_PASSWORD)
    oid = obs["id"]
    # El empleado nuevo tiene por defecto: ver, crear y comentar (no editar, estado ni eliminar).
    ctx.users.update(admin, employee.id, {"permissions": ["inventario.ver"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    for method, path, body in (("get", "/api/observations", None), ("get", f"/api/observations/{oid}", None),
                               ("get", "/api/observations/meta", None),
                               ("post", "/api/observations", {"product_id": obs["product_id"]}),
                               ("put", f"/api/observations/{oid}", {"priority": "baja"}),
                               ("post", f"/api/observations/{oid}/status", {"status": "resuelta"}),
                               ("post", f"/api/observations/{oid}/comments", {"comment": "x"}),
                               ("post", f"/api/observations/{oid}/delete", {"reason": "x"})):
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.text)
    assert client.get("/api/observations/flags", params={"ids": str(obs["product_id"])}).json() == {}

    ctx.users.update(admin, employee.id, {"permissions": ["inventario.ver", "observaciones.ver", "observaciones.comentar"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    detail = client.get(f"/api/observations/{oid}").json()
    assert "cost" not in detail["product"]                      # sin permiso de costos no ve el costo
    assert client.post(f"/api/observations/{oid}/comments", json={"comment": "Visto"}).status_code == 200
    assert client.put(f"/api/observations/{oid}", json={"priority": "baja"}).status_code == 403
    assert client.post(f"/api/observations/{oid}/status", json={"status": "resuelta"}).status_code == 403
    assert client.post(f"/api/observations/{oid}/delete", json={"reason": "x"}).status_code == 403
    assert client.post(f"/api/observations/{oid}/files", files={"file": ("a.png", PNG, "x")}).status_code == 403

    ctx.users.update(admin, employee.id, {"permissions": ["observaciones.ver", "observaciones.estado"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    assert client.post(f"/api/observations/{oid}/status", json={"status": "en_proceso"}).status_code == 200
    events = client.get(f"/api/observations/{oid}").json()["events"]
    assert events[-1]["user_name"] == "Empleado Uno"


def test_default_employee_permissions(ctx, admin):
    user = ctx.users.create(admin, {"username": "nuevo", "full_name": "Nuevo", "role": "employee", "password": EMPLOYEE_PASSWORD})
    assert {"observaciones.ver", "observaciones.crear", "observaciones.comentar"} <= set(user["permissions"])
    assert not {"observaciones.editar", "observaciones.estado", "observaciones.eliminar"} & set(user["permissions"])


# ------------------------------------------------------------------ 14. eliminación lógica
def test_logical_delete_keeps_traceability(c, ctx, obs):
    oid = obs["id"]
    assert c.post(f"/api/observations/{oid}/delete", json={"reason": " "}).status_code == 422
    assert c.post(f"/api/observations/{oid}/delete", json={"reason": "Registrada por error"}).status_code == 200
    assert c.get(f"/api/observations/{oid}").status_code == 404
    assert c.get("/api/observations").json()["total"] == 0
    assert c.post(f"/api/observations/{oid}/comments", json={"comment": "x"}).status_code == 404
    with ctx.db.read() as conn:
        row = conn.execute("SELECT deleted_at, delete_reason FROM inventory_observations WHERE id = ?", (oid,)).fetchone()
        kinds = [r[0] for r in conn.execute("SELECT kind FROM inventory_observation_events WHERE observation_id = ?", (oid,))]
        audit = conn.execute("SELECT details FROM audit_log WHERE action = 'observacion.eliminar'").fetchone()[0]
    assert row[0] and row[1] == "Registrada por error" and kinds[-1] == "eliminada"
    assert "Registrada por error" in audit and "faltantes" in audit


# ------------------------------------------------------------------ 15. existencias y movimientos intactos
def test_observations_never_touch_inventory(c, ctx, product, meta):
    before = inventory_snapshot(ctx)
    r = c.post("/api/observations", json={"product_id": product["id"], "category_id": cat(meta, "faltante"), "priority": "critica",
                                          "description": "Faltan 7 unidades", "qty": "7"}).json()
    oid = r["id"]
    c.put(f"/api/observations/{oid}", json={"qty": "8", "priority": "alta"})
    c.post(f"/api/observations/{oid}/comments", json={"comment": "Se revisa"})
    c.post(f"/api/observations/{oid}/files", files={"file": ("f.png", PNG, "x")})
    c.post(f"/api/observations/{oid}/status", json={"status": "resuelta", "comment": "Listo"})
    c.post(f"/api/observations/{oid}/status", json={"status": "cerrada", "comment": "Listo"})
    c.post(f"/api/observations/{oid}/delete", json={"reason": "Prueba"})
    assert inventory_snapshot(ctx) == before
    assert c.get(f"/api/products/{product['id']}").json()["stock"] == "10"


# ------------------------------------------------------------------ 16. persistencia tras reiniciar
def test_persistence_after_restart(c, ctx, obs, tmp_path):
    oid = obs["id"]
    c.post(f"/api/observations/{oid}/comments", json={"comment": "Persistente"})
    fid = c.post(f"/api/observations/{oid}/files", files={"file": ("p.png", PNG, "x")}).json()["id"]
    again = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    assert again.db.migrate() == []                                  # la migración no se reaplica
    c2 = TestClient(create_app(again))
    c2.headers.update({"X-Requested-With": "pos-py"})
    login(c2)
    detail = c2.get(f"/api/observations/{oid}").json()
    assert detail["description"] == obs["description"] and detail["events"][-2]["comment"] == "Persistente"
    assert c2.get(f"/api/observations/{oid}/files/{fid}/download").content == PNG
