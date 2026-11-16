"""Expediente de proveedores: datos, notas, visitas, cotizaciones, archivos, permisos y aislamiento."""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from pospy.api.app import create_app
from pospy.config import Config
from pospy.context import AppContext
from pospy.services.suppliers import OLE_MAGIC, safe_filename

from .conftest import EMPLOYEE_PASSWORD, login

TODAY = date.today()


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def business_snapshot(app) -> dict:
    """Tablas que el expediente NUNCA debe tocar."""
    with app.db.read() as conn:
        return {t: conn.execute(f"SELECT COUNT(*), COALESCE(SUM(id), 0) FROM {t}").fetchone()[:]
                for t in ("products", "inventory_movements", "sales", "payables", "journal_entries", "commercial_documents")} | {
            "stock": conn.execute("SELECT COALESCE(SUM(stock_milli), 0) FROM products").fetchone()[0]}


@pytest.fixture()
def c(client):
    login(client)
    return client


@pytest.fixture()
def supplier(c):
    r = c.post("/api/parties/proveedores", json={"name": "Distribuidora Andina", "identification": "900123456",
                                                 "phone": "6025551234", "whatsapp": "3001234567", "city": "Cali",
                                                 "email": "ventas@andina.co", "address": "Cra 1 # 2-3",
                                                 "contact_notes": "Pedidos antes de las 10 a. m."})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ información general y contacto
def test_general_info_and_contact_edit(c, supplier):
    sid = supplier["id"]
    assert supplier["whatsapp"] == "3001234567" and supplier["city"] == "Cali"
    r = c.put(f"/api/parties/proveedores/{sid}", json={"name": "Distribuidora Andina S.A.S.", "identification": "900123456", "phone": "6025550000",
                                                         "whatsapp": "3009998877", "version": supplier["version"]})
    assert r.status_code == 200 and r.json()["whatsapp"] == "3009998877"
    assert r.json()["city"] == "Cali"                     # campo no enviado: se conserva
    assert c.put(f"/api/parties/proveedores/{sid}", json={"name": "X", "version": supplier["version"]}).status_code == 409
    assert c.put(f"/api/parties/proveedores/{sid}", json={"name": ""}).status_code == 422
    assert c.post("/api/parties/proveedores", json={"name": "Otro", "identification": "900123456"}).status_code == 409

    adv = c.put(f"/api/suppliers/{sid}/advisor", json={"advisor_name": "Laura Gómez", "advisor_phone": "3110000000",
                                                       "advisor_email": "laura@andina.co", "advisor_notes": "Martes"})
    assert adv.status_code == 200 and adv.json()["advisor_name"] == "Laura Gómez"
    assert c.put(f"/api/suppliers/{sid}/advisor", json={"advisor_email": "malo"}).status_code == 422
    dash = c.get(f"/api/suppliers/{sid}").json()
    assert dash["supplier"]["name"] == "Distribuidora Andina S.A.S." and dash["supplier"]["advisor_name"] == "Laura Gómez"
    # los clientes no se ven afectados por los campos nuevos
    assert c.post("/api/parties/clientes", json={"name": "Cliente", "city": "Ignorada"}).status_code == 200


# ------------------------------------------------------------------ notas
def test_notes_lifecycle(c, supplier, ctx):
    sid = supplier["id"]
    before = business_snapshot(ctx)
    debt = c.post(f"/api/suppliers/{sid}/notes", json={"category": "deuda", "title": "Debemos factura 123 por $1.200.000",
                                                       "body": "Pagar en 2 cuotas", "important": True, "due_date": d(-1)})
    assert debt.status_code == 200, debt.text
    c.post(f"/api/suppliers/{sid}/notes", json={"category": "entrega", "title": "Faltan 10 cajas de tornillos"})
    c.post(f"/api/suppliers/{sid}/notes", json={"category": "acuerdo", "title": "Descuento 5 % por pronto pago"})
    assert c.post(f"/api/suppliers/{sid}/notes", json={"title": ""}).status_code == 422          # incompleta
    assert c.post(f"/api/suppliers/{sid}/notes", json={"title": "x", "category": "otra"}).status_code == 422
    assert c.post(f"/api/suppliers/{sid}/notes", json={"title": "x", "due_date": "31/12/2026"}).status_code == 422

    note = debt.json()
    resolved = c.put(f"/api/suppliers/{sid}/notes/{note['id']}", json={"status": "resuelta", "version": note["version"]}).json()
    assert resolved["status"] == "resuelta" and resolved["resolved_at"] and resolved["title"] == note["title"]
    assert resolved["created_at"] == note["created_at"] and resolved["updated_at"] >= note["updated_at"]
    pending = c.get(f"/api/suppliers/{sid}/notes?status=pendiente").json()
    assert {n["category"] for n in pending} == {"entrega", "acuerdo"}
    assert len(c.get(f"/api/suppliers/{sid}/notes?category=deuda").json()) == 1
    assert c.get(f"/api/suppliers/{sid}").json()["pending_notes"] == 2

    # edición y eliminación (la auditoría conserva el contenido)
    edited = c.put(f"/api/suppliers/{sid}/notes/{pending[0]['id']}", json={"body": "Llamar el lunes"}).json()
    assert edited["body"] == "Llamar el lunes"
    assert c.delete(f"/api/suppliers/{sid}/notes/{pending[0]['id']}").status_code == 200
    assert c.delete(f"/api/suppliers/{sid}/notes/{pending[0]['id']}").status_code == 404
    with ctx.db.read() as conn:
        audit = conn.execute("SELECT details FROM audit_log WHERE action = 'proveedor.nota_eliminar'").fetchone()[0]
    assert pending[0]["title"] in audit
    assert business_snapshot(ctx) == before          # las notas (incluida la deuda) no tocan transacciones


# ------------------------------------------------------------------ visitas
def test_visits_history_and_last_visit(c, supplier):
    sid = supplier["id"]
    c.put(f"/api/suppliers/{sid}/advisor", json={"advisor_name": "Laura Gómez"})
    ids = []
    for days, reason in ((-40, "Presentación"), (-3, "Toma de pedido"), (-15, "Reclamo")):   # fuera de orden
        r = c.post(f"/api/suppliers/{sid}/visits", json={"visit_date": d(days), "reason": reason,
                                                          "agreements": "Entrega el viernes", "next_visit_date": d(10)})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    visits = c.get(f"/api/suppliers/{sid}/visits").json()
    assert len(visits) == 3 and visits[0]["visit_date"] == d(-3)          # no se sobrescriben; más reciente primero
    assert visits[0]["advisor_name"] == "Laura Gómez"                      # toma el asesor actual si no se indica
    dash = c.get(f"/api/suppliers/{sid}").json()
    assert dash["last_visit"]["visit_date"] == d(-3) and dash["visits"] == 3 and dash["next_visit"] == d(10)
    assert c.post(f"/api/suppliers/{sid}/visits", json={"visit_date": d(5), "reason": "x"}).status_code == 422  # futura
    assert c.post(f"/api/suppliers/{sid}/visits", json={"visit_date": d(-1)}).status_code == 422               # sin motivo
    assert c.post(f"/api/suppliers/{sid}/visits", json={"visit_date": d(-1), "reason": "x",
                                                        "next_visit_date": d(-5)}).status_code == 422
    assert c.delete(f"/api/suppliers/{sid}/visits/{ids[1]}").status_code == 200    # borra la de hace 3 días
    assert c.get(f"/api/suppliers/{sid}").json()["last_visit"]["visit_date"] == d(-15)
    overview = c.get("/api/suppliers").json()
    assert overview["metrics"]["recent_visits"] == 1


# ------------------------------------------------------------------ cotizaciones
def test_quotes_history_and_attachment(c, supplier, ctx):
    sid = supplier["id"]
    before = business_snapshot(ctx)
    q1 = c.post(f"/api/suppliers/{sid}/quotes", json={"number": "COT-001", "issue_date": d(-30), "due_date": d(-1),
                                                      "total": "1.250.000,50", "description": "Tornillería"})
    assert q1.status_code == 200, q1.text
    assert q1.json()["total"] == "1250000.50" and q1.json()["expired"]          # pendiente con vencimiento pasado
    q2 = c.post(f"/api/suppliers/{sid}/quotes", json={"number": "COT-002", "issue_date": d(-2), "status": "aceptada"}).json()
    assert q2["total"] is None                                                  # valor desconocido
    assert c.post(f"/api/suppliers/{sid}/quotes", json={"number": "cot-001", "issue_date": d(0)}).status_code == 409
    assert c.post(f"/api/suppliers/{sid}/quotes", json={"issue_date": d(0)}).status_code == 422
    assert c.post(f"/api/suppliers/{sid}/quotes", json={"number": "N", "issue_date": d(0), "due_date": d(-1)}).status_code == 422
    assert c.post(f"/api/suppliers/{sid}/quotes", json={"number": "N", "issue_date": d(0), "total": "-5"}).status_code == 422

    history = c.get(f"/api/suppliers/{sid}/quotes").json()
    assert [q["number"] for q in history] == ["COT-002", "COT-001"]
    assert c.get(f"/api/suppliers/{sid}").json()["latest_quote"]["number"] == "COT-002"
    assert [q["number"] for q in c.get(f"/api/suppliers/{sid}/quotes?status=aceptada").json()] == ["COT-002"]
    upd = c.put(f"/api/suppliers/{sid}/quotes/{q2['id']}", json={"total": "980000", "version": q2["version"]})
    assert upd.json()["total"] == "980000.00"

    pdf = b"%PDF-1.4\n%prueba\n"
    att = c.post(f"/api/suppliers/{sid}/quotes/{q2['id']}/file", files={"file": ("cot 002.pdf", pdf, "application/pdf")})
    assert att.status_code == 200, att.text
    att2 = c.post(f"/api/suppliers/{sid}/quotes/{q2['id']}/file", files={"file": ("cot-002-v2.pdf", pdf + b"2", "application/pdf")})
    assert att2.status_code == 200
    listed = c.get(f"/api/suppliers/{sid}/quotes").json()[0]
    assert listed["file_name"] == "cot-002-v2.pdf"                              # el adjunto se reemplaza
    assert c.get(f"/api/suppliers/{sid}/files/{listed['file_id']}/download").content == pdf + b"2"
    assert len(list((ctx.config.data_dir / "proveedores" / str(sid)).iterdir())) == 1   # el anterior se borró
    assert c.delete(f"/api/suppliers/{sid}/quotes/{q2['id']}").status_code == 200
    assert not any((ctx.config.data_dir / "proveedores" / str(sid)).iterdir())
    assert business_snapshot(ctx) == before          # una cotización (incluso aceptada) no crea compras


# ------------------------------------------------------------------ lista de productos (Excel)
def test_product_excel_upload_download_replace_delete(c, supplier, ctx):
    sid = supplier["id"]
    before = business_snapshot(ctx)
    v1 = xlsx([["Código", "Producto", "Precio"], ["T-1", "Tornillo", 120]])
    r = c.post(f"/api/suppliers/{sid}/files", files={"file": ("Lista precios ENERO.xlsx", v1, "application/octet-stream")})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["original_name"] == "Lista precios ENERO.xlsx" and "stored_name" not in first
    dl = c.get(f"/api/suppliers/{sid}/files/{first['id']}/download")
    assert dl.status_code == 200 and dl.content == v1                           # descarga el original, byte a byte
    assert "Lista%20precios%20ENERO.xlsx" in dl.headers["content-disposition"] or "Lista precios ENERO.xlsx" in dl.headers["content-disposition"]

    v2 = xlsx([["Código", "Producto", "Precio"], ["T-1", "Tornillo", 130]])
    second = c.post(f"/api/suppliers/{sid}/files", files={"file": ("lista-febrero.xlsx", v2, "x")}).json()
    files = c.get(f"/api/suppliers/{sid}/files").json()
    assert [f["id"] for f in files] == [second["id"], first["id"]]             # reemplazo: la anterior se conserva
    assert files[0]["current"] and not files[1]["current"] and files[0]["version"] == 2 and all(f["available"] for f in files)
    assert c.get(f"/api/suppliers/{sid}").json()["product_file"]["id"] == second["id"]
    xls = c.post(f"/api/suppliers/{sid}/files", files={"file": ("viejo.xls", OLE_MAGIC + b"\0" * 600, "x")})
    assert xls.status_code == 200                                               # formato .xls (Excel 97-2003)

    assert c.delete(f"/api/suppliers/{sid}/files/{second['id']}").status_code == 200
    assert c.get(f"/api/suppliers/{sid}/files/{second['id']}/download").status_code == 404
    assert c.get(f"/api/suppliers/{sid}/files/{first['id']}/download").content == v1   # las demás siguen
    assert business_snapshot(ctx) == before          # el Excel NO se importa al inventario


def test_invalid_uploads(c, supplier, ctx):
    sid = supplier["id"]
    bad = [("virus.exe", b"MZ\x90\x00", "extensión"), ("falso.xlsx", b"esto no es excel", "contenido"),
           ("vacio.xlsx", b"", "vacío"), ("falso.xls", b"PK\x03\x04abc", "contenido"),
           ("zip.xlsx", _zip_without_workbook(), "zip sin libro")]
    for name, content, why in bad:
        r = c.post(f"/api/suppliers/{sid}/files", files={"file": (name, content, "x")})
        assert r.status_code == 422, (why, r.text)
    ctx.settings.update("proveedores", {"max_file_mb": 1}, ctx.auth.login("admin", "Clave segura 2026").actor)
    big = xlsx([["x" * 100] for _ in range(1)]) + b"\0" * (1024 * 1024)
    r = c.post(f"/api/suppliers/{sid}/files", files={"file": ("grande.xlsx", big, "x")})
    assert r.status_code == 422 and "1 MB" in r.text
    assert c.post("/api/suppliers/99999/files", files={"file": ("a.xlsx", xlsx([[1]]), "x")}).status_code == 404
    folder = ctx.config.data_dir / "proveedores" / str(sid)
    assert not folder.exists() or not any(folder.iterdir())                      # nada quedó en disco


def _zip_without_workbook() -> bytes:
    import zipfile
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hola.txt", "x")
    return buf.getvalue()


def test_path_manipulation_is_neutralised(c, supplier, ctx):
    sid = supplier["id"]
    r = c.post(f"/api/suppliers/{sid}/files", files={"file": ("..\\..\\..\\Windows\\win.ini.xlsx", xlsx([[1]]), "x")})
    assert r.status_code == 200 and r.json()["original_name"] == "win.ini.xlsx"
    stored = list((ctx.config.data_dir / "proveedores" / str(sid)).iterdir())
    assert len(stored) == 1 and stored[0].parent == ctx.config.data_dir / "proveedores" / str(sid)
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename('a<b>:"c|?*.XLSX') == "abc.xlsx"
    assert safe_filename("CON.xlsx") == "_CON.xlsx"
    assert safe_filename("") == "archivo"


# ------------------------------------------------------------------ aislamiento entre proveedores
def test_records_are_isolated_between_suppliers(c, supplier, ctx):
    a = supplier["id"]
    b = c.post("/api/parties/proveedores", json={"name": "Ferretería B"}).json()["id"]
    note = c.post(f"/api/suppliers/{a}/notes", json={"title": "Solo de A"}).json()
    visit = c.post(f"/api/suppliers/{a}/visits", json={"visit_date": d(0), "reason": "A"}).json()
    quote = c.post(f"/api/suppliers/{a}/quotes", json={"number": "1", "issue_date": d(0)}).json()
    file = c.post(f"/api/suppliers/{a}/files", files={"file": ("a.xlsx", xlsx([[1]]), "x")}).json()
    # el mismo número de cotización sí puede existir en otro proveedor
    assert c.post(f"/api/suppliers/{b}/quotes", json={"number": "1", "issue_date": d(0)}).status_code == 200
    for method, path in (("put", f"/notes/{note['id']}"), ("delete", f"/notes/{note['id']}"),
                         ("put", f"/visits/{visit['id']}"), ("delete", f"/visits/{visit['id']}"),
                         ("put", f"/quotes/{quote['id']}"), ("delete", f"/quotes/{quote['id']}"),
                         ("get", f"/files/{file['id']}/download"), ("delete", f"/files/{file['id']}")):
        body = {"notes": {"title": "hack"}, "visits": {"reason": "hack"}, "quotes": {"number": "hack"}}.get(path.split("/")[1])
        r = getattr(c, method)(f"/api/suppliers/{b}{path}", **({"json": body} if method == "put" else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    assert c.get(f"/api/suppliers/{b}/notes").json() == []
    assert c.get(f"/api/suppliers/{a}/notes").json()[0]["title"] == "Solo de A"
    assert c.get(f"/api/suppliers/{a}/files/{file['id']}/download").status_code == 200


# ------------------------------------------------------------------ permisos
def test_permissions(client, ctx, admin, employee, supplier):
    client.cookies.clear()
    login(client, "empleado", EMPLOYEE_PASSWORD)
    sid = supplier["id"]
    for method, path in (("get", "/api/suppliers"), ("get", f"/api/suppliers/{sid}"), ("get", f"/api/suppliers/{sid}/notes"),
                         ("post", f"/api/suppliers/{sid}/notes"), ("put", f"/api/suppliers/{sid}/advisor")):
        kwargs = {"json": {"advisor_name": "x"} if path.endswith("advisor") else {"title": "x"}} if method in ("post", "put") else {}
        assert getattr(client, method)(path, **kwargs).status_code == 403, path
    ctx.users.update(admin, employee.id, {"permissions": ["terceros.gestionar"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    assert client.get(f"/api/suppliers/{sid}").status_code == 200


# ------------------------------------------------------------------ vista general, persistencia y compatibilidad
def test_overview_filters_and_metrics(c, supplier):
    sid = supplier["id"]
    other = c.post("/api/parties/proveedores", json={"name": "Zeta Inactiva", "active": False}).json()
    c.post(f"/api/suppliers/{sid}/notes", json={"title": "Pendiente", "important": True})
    c.post(f"/api/suppliers/{sid}/quotes", json={"number": "Q", "issue_date": d(0)})
    data = c.get("/api/suppliers").json()
    assert [s["name"] for s in data["items"]] == ["Distribuidora Andina"]
    assert data["metrics"] == {"total": 2, "active": 1, "with_pending": 1, "recent_visits": 0, "with_quotes": 1}
    assert data["items"][0]["pending_notes"] == 1 and data["items"][0]["important_notes"] == 1
    assert [s["id"] for s in c.get("/api/suppliers?status=inactivos").json()["items"]] == [other["id"]]
    assert len(c.get("/api/suppliers?status=todos").json()["items"]) == 2
    assert c.get("/api/suppliers?q=andina").json()["items"][0]["id"] == sid
    assert c.get("/api/suppliers?q=900123").json()["items"][0]["id"] == sid
    assert c.get("/api/suppliers?status=raro").status_code == 422
    assert c.get("/api/suppliers/99999").status_code == 404


def test_persistence_after_restart(c, supplier, ctx, tmp_path):
    sid = supplier["id"]
    c.put(f"/api/suppliers/{sid}/advisor", json={"advisor_name": "Laura"})
    c.post(f"/api/suppliers/{sid}/notes", json={"title": "Persistente", "category": "pago"})
    c.post(f"/api/suppliers/{sid}/visits", json={"visit_date": d(-2), "reason": "Pedido"})
    c.post(f"/api/suppliers/{sid}/quotes", json={"number": "P-1", "issue_date": d(-2), "total": "100"})
    content = xlsx([["persistente"]])
    fid = c.post(f"/api/suppliers/{sid}/files", files={"file": ("p.xlsx", content, "x")}).json()["id"]

    again = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    c2 = TestClient(create_app(again))
    c2.headers.update({"X-Requested-With": "pos-py"})
    login(c2)
    dash = c2.get(f"/api/suppliers/{sid}").json()
    assert dash["supplier"]["advisor_name"] == "Laura" and dash["pending_notes"] == 1
    assert dash["last_visit"]["reason"] == "Pedido" and dash["latest_quote"]["total"] == "100.00"
    assert c2.get(f"/api/suppliers/{sid}/files/{fid}/download").content == content


def test_existing_suppliers_and_payables_keep_working(c, ctx, admin, product):
    """Proveedores anteriores siguen disponibles para compras a crédito (cuentas por pagar)."""
    sup = ctx.catalog.save_party(admin, "proveedores", {"name": "Proveedor previo", "payment_days": 15})
    assert sup["whatsapp"] == "" and sup["advisor_name"] == ""
    ctx.inventory.register_movement(admin, product["id"], {
        "kind": "entrada", "qty": "2", "unit_cost": "10000", "reason": "Compra F-9", "counterpart": "compra_credito",
        "supplier_id": sup["id"], "invoice_number": "F-9", "due_date": "2099-01-01"}, "clave-prueba-proveedor")
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM payables WHERE supplier_id = ?", (sup["id"],)).fetchone()[0] == 1
    assert c.get(f"/api/suppliers/{sup['id']}").json()["pending_notes"] == 0   # el expediente no las mezcla
