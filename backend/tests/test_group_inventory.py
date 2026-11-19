"""Inventario por grupo: acceso entre grupos, ventas concurrentes, anulación, devoluciones con estado del
producto, panel de movimientos y aviso en vivo (prompt 4)."""
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.core.errors import NotFoundError, PermissionDenied, ValidationError

from .conftest import EMPLOYEE_PASSWORD, key, login
from .test_groups import _employee, _token

PASSWORD_2 = "Almacen firme 77y"
PASSWORD_3 = "Vitrina clara 55z"


@pytest.fixture()
def shop(ctx, admin, employee, cash_id):
    """Grupo «Sucursal Armenia» con Ana (employee) y Beto; Caro trabaja en el inventario general.
    El grupo tiene su propio producto TAL-01 con 5 unidades."""
    beto = _employee(ctx, admin, "beto", "Beto Bodega", PASSWORD_2)
    caro = _employee(ctx, admin, "caro", "Caro Caja", PASSWORD_3)
    g = ctx.groups.create(admin, {"name": "Sucursal Armenia"})
    gid = g["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, gid, {"max_uses": 5})["url"])
    ctx.groups.accept(employee, token)
    ctx.groups.accept(beto, token)
    product = ctx.inventory.create(admin, {"code": "TAL-01", "description": "Taladro", "price": "10000", "cost": "6000",
                                           "tax_rate": "0", "initial_stock": "5", "min_stock": "1"}, gid)
    return {"gid": gid, "ana": employee, "beto": beto, "caro": caro, "product": product, "cash": cash_id}


def _grant(ctx, admin, actor, username, password, *extra):
    """Da permisos adicionales a un empleado y devuelve su sesión renovada."""
    ctx.users.update(admin, actor.id, {"permissions": sorted(actor.permissions | set(extra))})
    return ctx.auth.login(username, password).actor


def _sell(ctx, actor, product, qty, cash_id, price=10000):
    return ctx.sales.checkout(actor, {"lines": [{"product_id": product["id"], "qty": str(qty)}],
                                      "payments": [{"method_id": cash_id, "amount": str(price * qty)}]}, key())


def _stock(ctx, admin, product_id) -> int:
    return ctx.inventory.get(admin, product_id)["stock_milli"]


def test_group_members_share_one_inventory_and_others_cannot_see_it(ctx, admin, shop):
    ana, beto, caro, p, gid = shop["ana"], shop["beto"], shop["caro"], shop["product"], shop["gid"]
    # Los integrantes trabajan por defecto en el inventario del grupo; ven el mismo producto
    with ctx.db.read() as conn:
        assert [x["key"] for x in ctx.inventory.scopes.accessible(conn, ana)] == [gid]
    assert [r["code"] for r in ctx.inventory.list(ana)["items"]] == ["TAL-01"]
    assert [r["code"] for r in ctx.inventory.list(beto)["items"]] == ["TAL-01"]
    assert [r["code"] for r in ctx.inventory.list(admin, inventory=gid)["items"]] == ["TAL-01"]
    # El inventario general no muestra el producto del grupo
    assert ctx.inventory.list(admin)["items"] == [] and ctx.inventory.list(caro)["items"] == []
    # Caro (sin grupo) no entra al inventario del grupo ni a su producto, ni pidiéndolo por id
    with pytest.raises(NotFoundError):
        ctx.inventory.list(caro, inventory=gid)
    with pytest.raises(NotFoundError):
        ctx.inventory.get(caro, p["id"])
    with pytest.raises(NotFoundError):
        _sell(ctx, caro, p, 1, shop["cash"])
    # Un integrante del grupo no entra al inventario general
    with pytest.raises(NotFoundError):
        ctx.inventory.list(ana, inventory="general")
    # Otro administrador tampoco ve el grupo ajeno
    socio = ctx.users.create(admin, {"username": "socio", "full_name": "Socio", "role": "admin", "password": PASSWORD_3 + "x"})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE id = ?", (socio["id"],))
    socio = ctx.auth.login("socio", PASSWORD_3 + "x").actor
    with pytest.raises(NotFoundError):
        ctx.inventory.get(socio, p["id"])
    # El mismo código puede existir en otro inventario, pero no repetirse en el mismo
    ctx.inventory.create(admin, {"code": "TAL-01", "description": "Taladro general", "price": "1", "initial_stock": "1"})
    with pytest.raises(ValidationError) as dup:
        ctx.inventory.create(admin, {"code": "TAL-01", "description": "Otro", "price": "1"}, gid)
    assert "este inventario" in str(dup.value.fields)


def test_sale_by_employee_updates_shared_stock_and_movement_history(ctx, admin, shop):
    ana, beto, p = shop["ana"], shop["beto"], shop["product"]
    sale = _sell(ctx, ana, p, 3, shop["cash"])
    assert _stock(ctx, beto, p["id"]) == 2000 and _stock(ctx, admin, p["id"]) == 2000
    listed = ctx.sales.list(admin, inventory=shop["gid"])["items"]
    assert [s["id"] for s in listed] == [sale["id"]] and listed[0]["seller_name"] == "Empleado Uno"
    assert ctx.sales.list(admin)["items"] == []                        # no aparece en el inventario general
    hist = ctx.inventory.history(admin, inventory=shop["gid"], category="salidas")["items"]
    assert len(hist) == 1 and hist[0]["kind"] == "venta" and hist[0]["qty_milli"] == -3000
    assert hist[0]["stock_before_milli"] == 5000 and hist[0]["stock_after_milli"] == 2000
    assert hist[0]["full_name"] == "Empleado Uno" and hist[0]["reference_number"] == sale["number"]
    entries = ctx.inventory.history(admin, inventory=shop["gid"], category="entradas")["items"]
    assert [m["kind"] for m in entries] == ["inicial"]


def test_concurrent_sales_of_last_units_never_go_negative(ctx, admin, shop):
    ana, beto, p = shop["ana"], shop["beto"], shop["product"]
    results: list = []
    barrier = threading.Barrier(2)

    def attempt(actor):
        barrier.wait()
        try:
            results.append(_sell(ctx, actor, p, 4, shop["cash"]))
        except ValidationError as exc:
            results.append(exc)

    threads = [threading.Thread(target=attempt, args=(a,)) for a in (ana, beto)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    ok = [r for r in results if isinstance(r, dict)]
    failed = [r for r in results if isinstance(r, ValidationError)]
    assert len(ok) == 1 and len(failed) == 1 and "insuficientes" in str(failed[0])
    assert _stock(ctx, admin, p["id"]) == 1000
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 1


def test_cancel_sale_restores_stock_once_and_keeps_history(ctx, admin, shop):
    ana, p = shop["ana"], shop["product"]
    caro = _grant(ctx, admin, shop["caro"], "caro", PASSWORD_3, "ventas.anular")
    sale = _sell(ctx, ana, p, 4, shop["cash"])
    assert _stock(ctx, admin, p["id"]) == 1000
    with pytest.raises(PermissionDenied):                              # sin permiso ventas.anular
        ctx.sales.void(ana, sale["id"], "Cliente desistió")
    with pytest.raises(NotFoundError):                                 # de otro inventario
        ctx.sales.void(caro, sale["id"], "Cliente desistió")
    voided = ctx.sales.void(admin, sale["id"], "Cliente desistió")
    assert voided["status"] == "anulada" and voided["void_reason"] == "Cliente desistió"
    assert voided["voided_by_name"] == "Administradora" and voided["user_id"] == ana.id
    assert _stock(ctx, admin, p["id"]) == 5000
    with pytest.raises(ValidationError, match="ya estaba anulada"):
        ctx.sales.void(admin, sale["id"], "otra vez")
    assert _stock(ctx, admin, p["id"]) == 5000
    kinds = [m["kind"] for m in ctx.inventory.history(admin, p["id"])["items"]]
    assert kinds == ["anulacion_venta", "venta", "inicial"]           # la salida original se conserva


def test_returns_by_condition_and_review(ctx, admin, shop):
    p, gid = shop["product"], shop["gid"]
    sale = _sell(ctx, shop["ana"], p, 5, shop["cash"])
    line = sale["lines"][0]["id"]
    assert _stock(ctx, admin, p["id"]) == 0

    def ret(qty, condition):
        return ctx.sales.register_return(admin, sale["id"], {
            "reason": "Cliente", "refund_method_id": shop["cash"],
            "lines": [{"sale_line_id": line, "qty": str(qty), "condition": condition}]}, key())

    ret(1, "apto")
    assert _stock(ctx, admin, p["id"]) == 1000                         # lo apto vuelve
    ret(1, "no_apto")
    assert _stock(ctx, admin, p["id"]) == 1000                         # lo dañado no vuelve
    after = ret(2, "revision")
    assert _stock(ctx, admin, p["id"]) == 1000                         # pendiente: todavía no vuelve
    with pytest.raises(ValidationError, match="Estado"):
        ret(1, "roto")

    rows = ctx.inventory.returns(admin, gid)["items"]
    assert {r["condition"]: r["restocked_milli"] for r in rows} == {"apto": 1000, "no_apto": 0, "revision": 0}
    assert all(r["sale_number"] == sale["number"] for r in rows)
    pending = next(r for r in rows if r["condition"] == "revision")
    assert pending["id"] == after["returns"][-1]["lines"][0]["id"]

    with pytest.raises(PermissionDenied):
        ctx.sales.resolve_return_line(shop["ana"], pending["id"], "apto")
    with pytest.raises(NotFoundError):
        ctx.sales.resolve_return_line(_grant(ctx, admin, shop["caro"], "caro", PASSWORD_3, "ventas.anular"), pending["id"], "apto")
    ctx.sales.resolve_return_line(admin, pending["id"], "apto", "Revisado, funciona")
    assert _stock(ctx, admin, p["id"]) == 3000
    with pytest.raises(ValidationError, match="ya fue revisado"):
        ctx.sales.resolve_return_line(admin, pending["id"], "no_apto")
    assert _stock(ctx, admin, p["id"]) == 3000
    dash = ctx.inventory.dashboard(admin, gid)
    assert dash["counts"]["devoluciones"]["qty_milli"] == 4000
    assert dash["counts"]["devoluciones"]["restocked_milli"] == 3000
    assert dash["counts"]["devoluciones"]["pending_review"] == 0


def test_dashboard_counts_filters_and_people(ctx, admin, shop):
    ana, beto, p, gid = shop["ana"], shop["beto"], shop["product"], shop["gid"]
    _sell(ctx, ana, p, 1, shop["cash"])
    _sell(ctx, beto, p, 2, shop["cash"])
    dash = ctx.inventory.dashboard(admin, gid)
    assert dash["inventory"]["key"] == gid
    assert dash["counts"]["entradas"] == {"count": 1, "qty_milli": 5000}
    assert dash["counts"]["salidas"] == {"count": 2, "qty_milli": 3000}
    assert dash["sales"] == {"completed": 2, "voided": 0, "total_cents": 3000000}
    assert dash["low_stock"] == 0
    assert {x["full_name"]: x["movements"] for x in dash["people"]} == {
        "Administradora": 1, "Empleado Uno": 1, "Beto Bodega": 1}
    only_beto = ctx.inventory.dashboard(admin, gid, user_id=beto.id)
    assert only_beto["counts"]["salidas"] == {"count": 1, "qty_milli": 2000} and only_beto["sales"]["completed"] == 1
    _sell(ctx, ana, p, 1, shop["cash"])
    assert ctx.inventory.dashboard(admin, gid)["low_stock"] == 1       # quedó en el mínimo
    with pytest.raises(NotFoundError):
        ctx.inventory.dashboard(shop["caro"], gid)
    # El general no mezcla movimientos del grupo
    assert ctx.inventory.dashboard(admin)["counts"]["salidas"]["count"] == 0


def test_live_event_reaches_only_people_of_that_inventory(ctx, admin, shop):
    ana, beto, caro, p = shop["ana"], shop["beto"], shop["caro"], shop["product"]
    loop = asyncio.new_event_loop()
    try:
        subs = {name: ctx.realtime.subscribe(actor.id, loop)[0] for name, actor in
                (("admin", admin), ("ana", ana), ("beto", beto), ("caro", caro))}
        sale = _sell(ctx, ana, p, 1, shop["cash"])
        loop.run_until_complete(asyncio.sleep(0))
        for name in ("admin", "ana", "beto"):
            events = []
            while not subs[name].queue.empty():
                events.append(subs[name].queue.get_nowait())
            assert {"type": "inventario", "inventory": shop["gid"], "change": "venta", "sale": sale["id"],
                    "products": [p["id"]]} in events, name
        assert subs["caro"].queue.empty()
    finally:
        loop.close()


def test_http_inventory_header_and_isolation(ctx, admin, shop):
    app = create_app(ctx)
    adm, a, c = (TestClient(app) for _ in range(3))
    for cl in (adm, a, c):
        cl.headers.update({"X-Requested-With": "pos-py"})
    login(adm)
    login(a, "empleado", EMPLOYEE_PASSWORD)
    login(c, "caro", PASSWORD_3)
    gid, p = shop["gid"], shop["product"]
    keys = [x["key"] for x in adm.get("/api/inventories").json()]
    assert keys == ["general", gid]
    assert [x["key"] for x in a.get("/api/inventories").json()] == [gid]
    assert [x["code"] for x in adm.get("/api/products", headers={"X-Inventory": gid}).json()["items"]] == ["TAL-01"]
    assert adm.get("/api/products").json()["items"] == []
    assert a.get("/api/products").json()["items"][0]["code"] == "TAL-01"
    assert c.get("/api/products", headers={"X-Inventory": gid}).status_code == 404
    assert c.get(f"/api/products/{p['id']}").status_code == 404
    assert adm.get("/api/inventory/dashboard", headers={"X-Inventory": gid}).status_code == 200
    assert adm.get("/api/inventory/returns", headers={"X-Inventory": gid}).json()["items"] == []
    created = adm.post("/api/products", headers={"X-Inventory": gid},
                       json={"code": "BRO-02", "description": "Broca", "price": "500", "initial_stock": "7"})
    assert created.status_code == 200, created.text
    movs = a.get("/api/movements?category=entradas").json()["items"]
    assert {m["code"] for m in movs} == {"TAL-01", "BRO-02"}
