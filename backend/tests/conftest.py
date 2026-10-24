from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext

ADMIN_PASSWORD = "Clave segura 2026"
EMPLOYEE_PASSWORD = "Caja segura 99x"


def key() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def ctx(tmp_path):
    app = AppContext(Config.from_env(data_dir=tmp_path / "data", web_dist=tmp_path / "no-dist", master_key="prueba"))
    code = app.auth.setup_file.read_text(encoding="utf-8").strip()
    app.auth.setup_admin(code, "admin", "Administradora", ADMIN_PASSWORD)
    return app


@pytest.fixture()
def admin(ctx):
    return ctx.auth.login("admin", ADMIN_PASSWORD).actor


@pytest.fixture()
def employee(ctx, admin):
    ctx.users.create(admin, {"username": "empleado", "full_name": "Empleado Uno", "role": "employee",
                             "password": EMPLOYEE_PASSWORD})
    with ctx.db.tx() as conn:   # simula que ya cambió su contraseña temporal
        conn.execute("UPDATE users SET must_change_password = 0 WHERE username = 'empleado'")
    return ctx.auth.login("empleado", EMPLOYEE_PASSWORD).actor


@pytest.fixture()
def product(ctx, admin):
    """Producto con IVA 19 % incluido: lista 20.000, oferta 18.000, costo 10.000, 10 unidades."""
    return ctx.inventory.create(admin, {"code": "MART-01", "description": "Martillo de uña", "price": "20000",
                                        "discount_price": "18000", "cost": "10000", "tax_rate": "19",
                                        "initial_stock": "10", "min_stock": "2"})


@pytest.fixture()
def cash_id(ctx):
    with ctx.db.read() as conn:
        return conn.execute("SELECT id FROM payment_methods WHERE code = 'efectivo'").fetchone()[0]


@pytest.fixture()
def credit_id(ctx):
    with ctx.db.read() as conn:
        return conn.execute("SELECT id FROM payment_methods WHERE code = 'credito'").fetchone()[0]


@pytest.fixture()
def bank_id(ctx):
    with ctx.db.read() as conn:
        return conn.execute("SELECT id FROM payment_methods WHERE code = 'transferencia'").fetchone()[0]


def balance(ctx, code: str) -> int:
    """Saldo débito − crédito de una cuenta."""
    with ctx.db.read() as conn:
        return conn.execute("SELECT COALESCE(SUM(debit_cents - credit_cents), 0) FROM journal_lines l"
                            " JOIN accounts a ON a.id = l.account_id WHERE a.code = ?", (code,)).fetchone()[0]


@pytest.fixture()
def client(ctx):
    test_client = TestClient(create_app(ctx))
    test_client.headers.update({"X-Requested-With": "pos-py"})
    return test_client


def login(client, username="admin", password=ADMIN_PASSWORD):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
