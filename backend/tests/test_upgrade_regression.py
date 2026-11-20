"""Regresión del prompt 7: al actualizar una instalación real (base en v012) el administrador no queda
bloqueado y el empleado conserva sus funciones POS.

Reproduce los datos reales: productos en el «Inventario general» (sin grupo), un administrador y un empleado
con permisos amplios que es integrante de un grupo SIN inventario propio."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from pospy import db as dbmod
from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext
from pospy.core.security import hash_password
from pospy.db import Database

from .conftest import key

ADMIN_PW, EMP_PW, EMP2_PW, OTHER_PW = "Clave segura 2026", "Caja segura 99x", "Mostrador azul 88k", "Socio firme 77y"
EMP_PERMS = ["documentos.anular", "documentos.crear", "documentos.imprimir", "documentos.ver", "finanzas.registrar",
             "inventario.costos", "inventario.editar", "inventario.movimientos", "inventario.ver", "ventas.descuento",
             "ventas.historial", "ventas.vender"]


@pytest.fixture()
def upgraded(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    full = list(dbmod.MIGRATIONS)
    monkeypatch.setattr(dbmod, "MIGRATIONS", [m for m in full if m[0] <= 12])
    Database(data / "pospy.db").migrate()
    now = "2026-11-12T16:00:00Z"
    c = sqlite3.connect(data / "pospy.db")
    users = [(1, "administrador", "Administrador", "admin", ADMIN_PW), (2, "empleado", "Empleado", "employee", EMP_PW),
             (3, "vitrina", "Sin venta", "employee", EMP2_PW), (4, "socio", "Otro admin", "admin", OTHER_PW)]
    for uid, name, full_name, role, pw in users:
        c.execute("INSERT INTO users(id, username, full_name, role, password_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                  (uid, name, full_name, role, hash_password(pw), now, now))
    c.executemany("INSERT INTO user_permissions(user_id, permission) VALUES (2, ?)", [(p,) for p in EMP_PERMS])
    c.executemany("INSERT INTO user_permissions(user_id, permission) VALUES (3, ?)", [("inventario.ver",)])
    c.execute("INSERT INTO settings(key, value, updated_at) VALUES ('acceso', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
              ('{"login_enabled": true, "setup_completed": true, "setup_step": "listo"}', now))
    c.executescript(f"""
        INSERT INTO work_groups(id, public_id, name, owner_id, status, created_at, updated_at) VALUES
          (1,'G-E8748C2B','Casa Renault',1,'cerrado','{now}','{now}'), (2,'G-E8470C68','Casa Renault-PRUEBA',1,'activo','{now}','{now}');
        INSERT INTO work_group_members(group_id, user_id, status, requested_at, joined_at, updated_at) VALUES
          (1,2,'retirado','{now}','{now}','{now}'), (2,2,'activo','{now}','{now}','{now}'), (2,3,'activo','{now}','{now}','{now}');
        INSERT INTO products(id, group_id, code, description, price_cents, created_at, updated_at) VALUES
          (1,NULL,'0257','VARILLA ACEITE STEPWAY',2800000,'{now}','{now}'), (2,NULL,'0910','ANILLO EXOSTO',1000000,'{now}','{now}');
        INSERT INTO inventory_movements(product_id, kind, qty_milli, stock_after_milli, reason, created_at)
          VALUES (1,'inicial',10000,10000,'Existencia inicial','{now}'), (2,'inicial',4000,4000,'Existencia inicial','{now}');
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(dbmod, "MIGRATIONS", full)
    ctx = AppContext(Config.from_env(data_dir=data, web_dist=tmp_path / "no-dist", master_key="prueba"))   # arranca = migra
    return ctx


def _session(ctx, user, pw):
    c = TestClient(create_app(ctx))
    c.headers.update({"X-Requested-With": "pos-py"})
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return c


def test_admin_keeps_full_access_after_upgrade(upgraded):
    ctx = upgraded
    assert ctx.db.schema_version() >= 13
    adm = _session(ctx, "administrador", ADMIN_PW)
    invs = adm.get("/api/inventories").json()
    assert [i["name"] for i in invs] == ["Inventario general"] and invs[0]["owner"]
    assert {"inventario.ver", "inventario.editar", "ventas.vender", "inventario.columnas"} <= set(invs[0]["permissions"])
    assert [p["code"] for p in adm.get("/api/products").json()["items"]] == ["0257", "0910"]
    assert adm.get("/api/movements").json()["total"] == 2
    created = adm.post("/api/inventories", json={"name": "Bodega", "group": "G-E8748C2B"})
    assert created.status_code == 200, created.text
    other = created.json()["key"]
    assert adm.get("/api/products", headers={"X-Inventory": other}).json()["items"] == []        # cambiar de inventario
    assert adm.get("/api/products", headers={"X-Inventory": invs[0]["key"]}).json()["total"] == 2
    socio = _session(ctx, "socio", OTHER_PW)
    assert socio.get("/api/inventories").json() == []                                        # otro administrador
    assert socio.get("/api/products/1").status_code in (403, 404)
    assert socio.get("/api/products", headers={"X-Inventory": invs[0]["key"]}).status_code == 403


def test_employee_keeps_pos_functions_and_sells_after_upgrade(upgraded):
    ctx = upgraded
    emp = _session(ctx, "empleado", EMP_PW)
    invs = emp.get("/api/inventories").json()
    assert [i["name"] for i in invs] == ["Inventario general"]                   # su grupo aún no tiene inventario: no queda sin POS
    assert set(invs[0]["permissions"]) == set(EMP_PERMS) - {"finanzas.registrar"}  # conserva TODOS sus permisos de inventario
    products = emp.get("/api/products/lookup", params={"q": "0257"}).json()
    assert products[0]["code"] == "0257"
    quote = emp.post("/api/sales/quote", json={"lines": [{"product_id": 1, "qty": "2"}]}).json()
    assert quote["totals"]["total"] == "56000.00" and quote["can_sell"]
    cash = [m for m in emp.get("/api/payment-methods").json() if m["code"] == "efectivo"][0]["id"]
    sale = emp.post("/api/sales", headers={"Idempotency-Key": key()},
                    json={"lines": [{"product_id": 1, "qty": "2"}], "payments": [{"method_id": cash, "amount": "56000"}]})
    assert sale.status_code == 200, sale.text
    assert emp.get("/api/products/1").json()["stock"] == "8"                     # existencias descontadas
    assert emp.put("/api/products/2", json={"description": "ANILLO EXOSTO LUV"}).status_code == 200   # conserva editar
    adm = _session(ctx, "administrador", ADMIN_PW)
    assert sale.json()["id"] in [s["id"] for s in adm.get("/api/sales").json()["items"]]   # el administrador la ve
    emp.post("/api/auth/logout")
    emp = _session(ctx, "empleado", EMP_PW)                                     # cierra e inicia sesión: mismos permisos
    assert set(emp.get("/api/inventories").json()[0]["permissions"]) == set(EMP_PERMS) - {"finanzas.registrar"}
    # Usuario SIN permiso de venta: consulta pero no vende
    vit = _session(ctx, "vitrina", EMP2_PW)
    assert vit.get("/api/products").status_code == 200
    assert vit.post("/api/sales", headers={"Idempotency-Key": key()},
                    json={"lines": [{"product_id": 1, "qty": "1"}], "payments": [{"method_id": cash, "amount": "28000"}]}).status_code == 403
    # Cuando el administrador crea el inventario de su grupo, el empleado pasa a ese inventario (y deja el general)
    adm.post("/api/inventories", json={"name": "Inventario PRUEBA", "group": "G-E8470C68"})
    assert [i["name"] for i in emp.get("/api/inventories").json()] == ["Inventario PRUEBA"]
    assert emp.get("/api/products/1").status_code == 404                       # no entra al general por identificador
