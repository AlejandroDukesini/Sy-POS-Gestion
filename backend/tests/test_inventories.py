"""Inventarios del administrador asociados a grupos: independencia, selección, permisos por inventario,
sincronización entre sesiones independientes, estados, eliminación segura, columnas y migración (prompt 6)."""
from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

from pospy import db as dbmod
from pospy.api.app import create_app
from pospy.core.errors import ConflictError, NotFoundError, ValidationError
from pospy.db import Database
from pospy.services.inventories import MEMBER_ASSIGNABLE

from .conftest import EMPLOYEE_PASSWORD, key, login, main_inventory
from .test_groups import _employee, _token

PW2, PW3, PW4 = "Almacen firme 77y", "Vitrina clara 55z", "Bodega norte 33q"


def _group(ctx, admin, name, *members):
    g = ctx.groups.create(admin, {"name": name})["group"]["public_id"]
    token = _token(ctx.groups.create_invitation(admin, g, {"max_uses": 10})["url"])
    for m in members:
        ctx.groups.accept(m, token)
    return g


@pytest.fixture()
def org(ctx, admin, employee, cash_id):
    """Alejandro (admin) con 3 inventarios: Armenia (Ana, Beto), Bodega (Dani) y Pereira (vacío)."""
    beto = _employee(ctx, admin, "beto", "Beto Bodega", PW2)
    dani = _employee(ctx, admin, "dani", "Dani Norte", PW3)
    caro = _employee(ctx, admin, "caro", "Caro Sin Grupo", PW4)
    ga = _group(ctx, admin, "Sucursal Armenia", employee, beto)
    gb = _group(ctx, admin, "Bodega Central", dani)
    gp = _group(ctx, admin, "Sucursal Pereira")
    inv = {
        "armenia": ctx.inventories.create(admin, {"name": "Inventario Armenia", "group": ga})["key"],
        "bodega": ctx.inventories.create(admin, {"name": "Inventario Bodega", "group": gb, "description": "Central"})["key"],
        "pereira": ctx.inventories.create(admin, {"name": "Inventario Pereira", "group": gp})["key"],
    }
    p_arm = ctx.inventory.create(admin, {"code": "TAL-01", "description": "Taladro", "price": "10000", "initial_stock": "5"},
                                 inv["armenia"])
    ctx.inventory.create(admin, {"code": "MAR-02", "description": "Martillo", "price": "8000", "initial_stock": "3"}, inv["armenia"])
    p_bod = ctx.inventory.create(admin, {"code": "TAL-01", "description": "Taladro bodega", "price": "9000", "initial_stock": "50"},
                                 inv["bodega"])
    return {"inv": inv, "groups": {"armenia": ga, "bodega": gb, "pereira": gp}, "ana": employee, "beto": beto, "dani": dani,
            "caro": caro, "p_arm": p_arm, "p_bod": p_bod, "cash": cash_id}


def _client(ctx, username=None, password=None):
    c = TestClient(create_app(ctx))
    c.headers.update({"X-Requested-With": "pos-py"})
    login(c, *(() if username is None else (username, password)))
    return c


# ------------------------------------------------------------------ inventarios independientes y selección
def test_admin_owns_several_independent_inventories(ctx, admin, org):
    inv = org["inv"]
    cards = {c["name"]: c for c in ctx.inventories.list(admin)}
    assert set(cards) == {"Inventario principal", "Inventario Armenia", "Inventario Bodega", "Inventario Pereira"}
    arm = cards["Inventario Armenia"]
    assert arm["group"]["name"] == "Sucursal Armenia" and arm["products"] == 2 and arm["stock_milli"] == 8000
    assert [p["code"] for p in arm["first_products"]] == ["TAL-01", "MAR-02"]           # productos reales, en orden de alta
    assert cards["Inventario Pereira"]["first_products"] == [] and cards["Inventario Pereira"]["products"] == 0
    # No se mezclan: mismo código en dos inventarios, existencias separadas
    assert [p["code"] for p in ctx.inventory.list(admin, inventory=inv["armenia"])["items"]] == ["MAR-02", "TAL-01"]
    assert [p["stock_milli"] for p in ctx.inventory.list(admin, inventory=inv["bodega"])["items"]] == [50000]
    assert ctx.inventory.list(admin, inventory=inv["pereira"])["items"] == []
    # Un grupo tiene un solo inventario; el grupo debe ser del administrador
    with pytest.raises(ConflictError):
        ctx.inventories.create(admin, {"name": "Otro", "group": org["groups"]["armenia"]})
    other = ctx.users.create(admin, {"username": "socio", "full_name": "Socio", "role": "admin", "password": PW4 + "x"})
    with ctx.db.tx() as conn:
        conn.execute("UPDATE users SET must_change_password = 0 WHERE id = ?", (other["id"],))
    socio = ctx.auth.login("socio", PW4 + "x").actor
    assert ctx.inventories.list(socio) == []                                   # no ve inventarios de otro administrador
    with pytest.raises(NotFoundError):
        ctx.inventories.get(socio, inv["armenia"])
    with pytest.raises(NotFoundError):
        ctx.inventories.update(socio, inv["armenia"], {"name": "Mío"})
    sg = ctx.groups.create(socio, {"name": "Grupo del socio"})["group"]["public_id"]
    with pytest.raises(ValidationError):                                       # no puede usar un grupo ajeno
        ctx.inventories.create(admin, {"name": "Robado", "group": sg})
    with pytest.raises(NotFoundError):
        ctx.inventory.get(socio, org["p_arm"]["id"])


def test_employees_work_only_in_their_group_inventory(ctx, admin, org):
    inv = org["inv"]
    ana_list = ctx.inventories.list(org["ana"])
    assert [c["key"] for c in ana_list] == [inv["armenia"]] and "inventario.editar" not in ana_list[0]["permissions"]
    assert [c["key"] for c in ctx.inventories.list(org["dani"])] == [inv["bodega"]]
    assert [c["key"] for c in ctx.inventories.list(org["caro"])] == [main_inventory(ctx, admin)]   # sin grupo: el principal
    with pytest.raises(NotFoundError):
        ctx.inventory.list(org["ana"], inventory=inv["bodega"])
    with pytest.raises(NotFoundError):
        ctx.inventory.get(org["dani"], org["p_arm"]["id"])


# ------------------------------------------------------------------ sincronización entre sesiones independientes
def test_shared_inventory_sync_between_independent_sessions(ctx, admin, org):
    inv = org["inv"]
    adm = _client(ctx)
    ana = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    beto = _client(ctx, "beto", PW2)
    dani = _client(ctx, "dani", PW3)
    loop = asyncio.new_event_loop()
    try:
        subs = {n: ctx.realtime.subscribe(a.id, loop)[0] for n, a in
                (("admin", admin), ("ana", org["ana"]), ("beto", org["beto"]), ("dani", org["dani"]))}
        # El administrador ingresa un producto: Ana y Beto lo ven; Dani no
        r = adm.post("/api/products", headers={"X-Inventory": inv["armenia"]},
                     json={"code": "BRO-03", "description": "Broca", "price": "500", "initial_stock": "4"})
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        assert "BRO-03" in [p["code"] for p in ana.get("/api/products").json()["items"]]
        assert "BRO-03" in [p["code"] for p in beto.get("/api/products").json()["items"]]
        assert "BRO-03" not in [p["code"] for p in dani.get("/api/products").json()["items"]]
        # Ana vende: el administrador y Beto ven la existencia nueva
        sale = ana.post("/api/sales", headers={"Idempotency-Key": key()},
                        json={"lines": [{"product_id": pid, "qty": "3"}], "payments": [{"method_id": org["cash"], "amount": "1500"}]})
        assert sale.status_code == 200, sale.text
        assert adm.get(f"/api/products/{pid}", headers={"X-Inventory": inv["armenia"]}).json()["stock"] == "1"
        assert beto.get(f"/api/products/{pid}").json()["stock"] == "1"
        assert sale.json()["id"] in [s["id"] for s in adm.get("/api/sales", headers={"X-Inventory": inv["armenia"]}).json()["items"]]
        loop.run_until_complete(asyncio.sleep(0))
        got = {n: [] for n in subs}
        for n, s in subs.items():
            while not s.queue.empty():
                got[n].append(s.queue.get_nowait())
        for n in ("admin", "ana", "beto"):
            assert any(e.get("type") == "inventario" and e.get("inventory") == inv["armenia"] and e.get("change") == "venta"
                       for e in got[n]), n
        assert not any(e.get("type") == "inventario" for e in got["dani"])   # otro inventario: no recibe nada
        # Reenviar la misma venta (reconexión) no la duplica
        k = key()
        body = {"lines": [{"product_id": pid, "qty": "1"}], "payments": [{"method_id": org["cash"], "amount": "500"}]}
        first = beto.post("/api/sales", headers={"Idempotency-Key": k}, json=body).json()
        again = beto.post("/api/sales", headers={"Idempotency-Key": k}, json=body).json()
        assert again["duplicate"] and again["id"] == first["id"]
        assert adm.get(f"/api/products/{pid}", headers={"X-Inventory": inv["armenia"]}).json()["stock"] == "0"
    finally:
        loop.close()


# ------------------------------------------------------------------ permisos por inventario y manipulación
def test_permissions_per_inventory_and_identifier_manipulation(ctx, admin, org):
    inv = org["inv"]
    ana = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    pid = org["p_arm"]["id"]
    # Sin restricción del inventario valen sus permisos de usuario: vende, pero como usuario no edita productos
    assert ana.post("/api/sales/quote", json={"lines": [{"product_id": pid, "qty": "1"}]}).status_code == 200
    assert ana.put(f"/api/products/{pid}", json={"description": "X"}).status_code == 403
    ctx.users.update(admin, org["ana"].id, {"permissions": sorted(MEMBER_ASSIGNABLE)})   # como usuario puede todo…
    ana = _client(ctx, "empleado", EMPLOYEE_PASSWORD)
    assert ana.put(f"/api/products/{pid}", json={"description": "Y"}).status_code == 200  # …y el inventario no lo restringe
    ctx.inventories.update(admin, inv["armenia"], {"members": [                          # el administrador lo restringe aquí
        {"user_id": org["ana"].id, "permissions": ["inventario.ver", "ventas.vender"]}]})
    assert ana.put(f"/api/products/{pid}", json={"description": "X"}).status_code == 403
    assert ana.post("/api/sales/quote", json={"lines": [{"product_id": pid, "qty": "1"}]}).status_code == 200
    ctx.inventories.update(admin, inv["armenia"], {"members": [
        {"user_id": org["ana"].id, "permissions": ["inventario.ver", "inventario.editar", "ventas.vender"]}]})
    r = ana.put(f"/api/products/{pid}", json={"description": "Taladro percutor"})
    assert r.status_code == 200, r.text
    # Ana también entra a Bodega, solo para consultar
    ctx.groups.accept(org["ana"], _token(ctx.groups.create_invitation(admin, org["groups"]["bodega"], {"max_uses": 2})["url"]))
    ctx.inventories.update(admin, inv["bodega"], {"members": [{"user_id": org["ana"].id, "permissions": ["inventario.ver"]}]})
    bid = org["p_bod"]["id"]
    # Manipulación: cabecera del inventario donde sí edita + producto del otro inventario → no existe
    assert ana.put(f"/api/products/{bid}", headers={"X-Inventory": inv["armenia"]}, json={"description": "X"}).status_code == 404
    assert ana.put(f"/api/products/{bid}", headers={"X-Inventory": inv["bodega"]}, json={"description": "X"}).status_code == 403
    assert ana.get(f"/api/products/{bid}", headers={"X-Inventory": inv["bodega"]}).status_code == 200
    # Vender en un inventario sin permiso de venta
    sale = ana.post("/api/sales", headers={"X-Inventory": inv["bodega"], "Idempotency-Key": key()},
                    json={"lines": [{"product_id": bid, "qty": "1"}], "payments": [{"method_id": org["cash"], "amount": "9000"}]})
    assert sale.status_code == 403
    # Solo integrantes activos del grupo pueden ser autorizados
    with pytest.raises(ValidationError):
        ctx.inventories.update(admin, inv["bodega"], {"members": [{"user_id": org["caro"].id, "permissions": ["inventario.ver"]}]})
    # Retirar a Ana del grupo le quita el acceso aunque tenga permisos guardados
    ctx.groups.member_action(admin, org["groups"]["bodega"], org["ana"].id, "retirar")
    assert [c["key"] for c in ctx.inventories.list(org["ana"])] == [inv["armenia"]]


def test_auto_authorize_setting_and_member_detail(ctx, admin, org):
    inv = org["inv"]
    ctx.inventories.update(admin, inv["pereira"], {"settings": {"auto_authorize": False}})
    eva = _employee(ctx, admin, "eva", "Eva Nueva", "Mostrador azul 88k")
    ctx.groups.accept(eva, _token(ctx.groups.create_invitation(admin, org["groups"]["pereira"], {"max_uses": 2})["url"]))
    assert ctx.inventories.list(eva) == []                                       # sin autorización todavía
    detail = ctx.inventories.get(admin, inv["pereira"])
    assert [m["full_name"] for m in detail["members"]] == ["Eva Nueva"] and detail["members"][0]["effective"] == []
    ctx.inventories.update(admin, inv["pereira"], {"members": [{"user_id": eva.id, "permissions": ["inventario.ver", "ventas.vender"]}]})
    assert [c["key"] for c in ctx.inventories.list(eva)] == [inv["pereira"]]


# ------------------------------------------------------------------ estados, configuración y eliminación
def test_status_negative_stock_override_and_safe_delete(ctx, admin, org):
    inv = org["inv"]
    ctx.inventories.update(admin, inv["armenia"], {"status": "inactivo"})
    assert ctx.inventories.list(org["ana"]) == []                                 # el empleado deja de verlo
    assert any(c["key"] == inv["armenia"] and c["status"] == "inactivo" for c in ctx.inventories.list(admin))
    with pytest.raises(ValidationError, match="inactivo"):
        ctx.sales.checkout(admin, {"lines": [{"product_id": org["p_arm"]["id"], "qty": "1"}],
                                   "payments": [{"method_id": org["cash"], "amount": "10000"}]}, key())
    ctx.inventories.update(admin, inv["armenia"], {"status": "activo", "settings": {"allow_negative_stock": True}})
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": org["p_arm"]["id"], "qty": "7"}],
                                      "payments": [{"method_id": org["cash"], "amount": "70000"}]}, key())
    assert ctx.inventory.get(admin, org["p_arm"]["id"])["stock_milli"] == -2000 and sale["id"]
    with pytest.raises(ValidationError, match="insuficientes"):                  # la otra no lo permite
        ctx.sales.checkout(admin, {"lines": [{"product_id": org["p_bod"]["id"], "qty": "51"}],
                                   "payments": [{"method_id": org["cash"], "amount": "459000"}]}, key())
    with pytest.raises(ValidationError, match="historia"):
        ctx.inventories.delete(admin, inv["armenia"])
    ctx.inventories.delete(admin, inv["pereira"])                                # vacío: se elimina
    with pytest.raises(NotFoundError):
        ctx.inventories.get(admin, inv["pereira"])
    ctx.inventories.update(admin, inv["bodega"], {"status": "archivado"})
    assert ctx.inventory.get(admin, org["p_bod"]["id"])["code"] == "TAL-01"      # archivado: la historia se conserva


def test_custom_columns_are_per_inventory(ctx, admin, org):
    inv = org["inv"]
    adm = _client(ctx)
    r = adm.post("/api/inventory/columns", headers={"X-Inventory": inv["armenia"]}, json={"name": "Marca", "data_type": "texto"})
    assert r.status_code == 200, r.text
    names = lambda k: [c["name"] for c in adm.get("/api/inventory/columns", headers={"X-Inventory": k}).json()["columns"]]  # noqa: E731
    assert names(inv["armenia"]) == ["Observaciones", "Marca"] and names(inv["bodega"]) == ["Observaciones"]
    assert adm.post("/api/inventory/columns", headers={"X-Inventory": inv["bodega"]},
                    json={"name": "Marca", "data_type": "texto"}).status_code == 200      # el mismo nombre en otro inventario
    col = r.json()["id"]
    assert adm.delete(f"/api/inventory/columns/{col}", headers={"X-Inventory": inv["bodega"]}).status_code == 404


def test_associate_migrated_inventory_with_group(ctx, admin, org):
    main = main_inventory(ctx, admin)
    ctx.inventory.create(admin, {"code": "GEN-1", "description": "Del principal", "price": "1", "initial_stock": "1"}, main)
    assert ctx.inventory.list(org["caro"])["items"][0]["code"] == "GEN-1"       # empleado sin grupo trabaja en él
    g = _group(ctx, admin, "Casa Renault", org["caro"])
    ctx.inventories.update(admin, main, {"group": g})
    assert [c["key"] for c in ctx.inventories.list(org["caro"])] == [main]       # ahora entra por su grupo
    assert ctx.inventories.get(admin, main)["group"]["name"] == "Casa Renault"
    with pytest.raises(ValidationError):
        ctx.inventories.update(admin, main, {"group": None})                     # no se puede dejar sin grupo


# ------------------------------------------------------------------ migración de datos existentes (v012 → v013)
def test_migration_from_group_inventories_preserves_everything(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    full = list(dbmod.MIGRATIONS)
    monkeypatch.setattr(dbmod, "MIGRATIONS", [m for m in full if m[0] <= 12])
    old = Database(path)
    old.migrate()
    c = sqlite3.connect(path)
    now = "2026-01-01T00:00:00Z"
    c.executescript(f"""
        INSERT INTO users(id, username, full_name, role, password_hash, created_at, updated_at) VALUES
          (1,'admin','Admin','admin','x','{now}','{now}'), (2,'ana','Ana','employee','x','{now}','{now}'),
          (3,'caro','Caro','employee','x','{now}','{now}');
        INSERT INTO work_groups(id, public_id, name, owner_id, created_at, updated_at) VALUES (1,'G-1','Armenia',1,'{now}','{now}');
        INSERT INTO work_group_members(group_id, user_id, status, requested_at, joined_at, updated_at)
          VALUES (1,2,'activo','{now}','{now}','{now}');
        INSERT INTO products(id, group_id, code, description, price_cents, created_at, updated_at) VALUES
          (1,NULL,'A','General',100,'{now}','{now}'), (2,1,'A','Del grupo',200,'{now}','{now}');
        INSERT INTO inventory_columns(name, data_type, position, created_at, updated_at) VALUES ('Marca','texto',20,'{now}','{now}');
        INSERT INTO inventory_custom_values(product_id, column_id, value, updated_at) VALUES
          (1,(SELECT id FROM inventory_columns WHERE name='Marca'),'Bosch','{now}'),
          (2,(SELECT id FROM inventory_columns WHERE name='Marca'),'Stanley','{now}');
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(dbmod, "MIGRATIONS", full)
    db = Database(path)
    assert db.migrate() == [13, 14] and db.migrate() == []                         # idempotente
    c = sqlite3.connect(path)
    invs = c.execute("SELECT id, group_id, name, owner_id FROM inventories ORDER BY id").fetchall()
    assert [(g, n) for _, g, n, _ in invs] == [(1, "Armenia"), (None, "Inventario general")]
    by_group = {g: i for i, g, _, _ in invs}
    assert c.execute("SELECT inventory_id FROM products ORDER BY id").fetchall() == [(by_group[None],), (by_group[1],)]
    members = c.execute("SELECT inventory_id, user_id FROM inventory_members ORDER BY user_id").fetchall()
    assert members == [(by_group[1], 2), (by_group[None], 3)]                  # Ana por su grupo, Caro (sin grupo) en el general
    values = c.execute("SELECT p.code, c.inventory_id, c.name, v.value FROM inventory_custom_values v JOIN inventory_columns c"
                       " ON c.id = v.column_id JOIN products p ON p.id = v.product_id ORDER BY p.id").fetchall()
    assert values == [("A", by_group[None], "Marca", "Bosch"), ("A", by_group[1], "Marca", "Stanley")]
    assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
