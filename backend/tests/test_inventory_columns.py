"""Inventario con columnas personalizables: Observaciones, columnas antes y después de importar, tipos,
edición segura, archivado, eliminación, orden, exportación, permisos y persistencia."""
from __future__ import annotations

import io

import openpyxl
import pytest

from pospy.config import Config
from pospy.context import AppContext
from pospy.core import permissions as perms
from pospy.core.errors import ConflictError, PermissionDenied, ValidationError

from .conftest import ADMIN_PASSWORD, login


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _cols(ctx, admin) -> dict[str, dict]:
    return {c["name"]: c for c in ctx.inventory.columns.list(admin, include_archived=True)["columns"]}


FILE = _xlsx([
    ["Código", "Producto", "Precio", "Cantidad", "Observaciones", "Marca", "Ubicación"],
    ["001", "Teclado", 50000, 10, "Revisar proveedor", "Logitech", "Bodega A"],
    ["002", "Mouse", 20000, 5, None, "Genius", "Bodega B"],
])


def _import(ctx, admin, content=FILE, custom=None, **opts):
    info = ctx.sync.inspect_upload(admin, "inventario.xlsx", content)
    run = ctx.sync.preview_upload(admin, "inventario.xlsx", content, {
        "columns": info["suggested_columns"], "custom": custom if custom is not None else [], **opts})
    return info, run


# ------------------------------------------------------------------ 1. Observaciones por defecto
def test_1_observations_column_exists_by_default_and_is_protected(ctx, admin, product):
    obs = _cols(ctx, admin)["Observaciones"]
    assert obs["is_system"] == 1 and obs["active"] == 1 and obs["data_type"] == "texto_largo"
    long_text = "Producto reservado para el cliente Ruiz. " * 40          # observación extensa (~1.600 caracteres)
    p = ctx.inventory.update(admin, product["id"], {"custom": {str(obs["id"]): long_text}})
    assert p["custom"][str(obs["id"])] == long_text.strip()
    assert p["price_cents"] == product["price_cents"] and p["stock_milli"] == product["stock_milli"]   # campos principales intactos
    with pytest.raises(ValidationError):
        ctx.inventory.columns.delete(admin, obs["id"])
    with pytest.raises(ValidationError):
        ctx.inventory.columns.set_active(admin, obs["id"], False)
    with pytest.raises(ValidationError):
        ctx.inventory.columns.update(admin, obs["id"], {"data_type": "entero"})
    renamed = ctx.inventory.columns.update(admin, obs["id"], {"description": "Notas internas del producto"})
    assert renamed["column"]["description"] == "Notas internas del producto"


# ------------------------------------------------------------------ 2-4. columnas antes de importar
def test_2_3_4_add_columns_before_import_and_values_are_saved(ctx, admin):
    obs = _cols(ctx, admin)["Observaciones"]
    info, run = _import(ctx, admin, custom=[
        {"column_id": obs["id"], "header": "Observaciones"},
        {"new": {"name": "Marca", "data_type": "texto"}, "header": "Marca"},
        {"new": {"name": "Ubicación", "data_type": "lista", "options": ["Bodega A", "Bodega B"]}, "header": "Ubicación"},
    ])
    assert info["suggested_custom"] == {str(obs["id"]): "Observaciones"}      # se reconoce por el nombre
    assert info["duplicate_headers"] == []
    assert run["summary"]["counts"]["new"] == 2
    assert run["summary"]["new"][0]["custom"] == {"Observaciones": "Revisar proveedor", "Marca": "Logitech",
                                                  "Ubicación": "Bodega A"}
    assert "Marca" not in _cols(ctx, admin)                       # la vista previa no crea nada todavía
    done = ctx.sync.apply(admin, run["id"])["summary"]["applied"]
    assert done["created"] == 2 and done["columns_created"] == ["Marca", "Ubicación"]
    cols = _cols(ctx, admin)
    names = [c["name"] for c in ctx.inventory.columns.list(admin)["columns"]]
    assert names == ["Observaciones", "Marca", "Ubicación"]       # quedan como parte de la estructura
    items = {p["code"]: p for p in ctx.inventory.list(admin)["items"]}
    assert items["001"]["custom"] == {str(obs["id"]): "Revisar proveedor", str(cols["Marca"]["id"]): "Logitech",
                                      str(cols["Ubicación"]["id"]): "Bodega A"}
    assert str(obs["id"]) not in items["002"]["custom"]          # celda vacía: sin valor
    assert ctx.inventory.list(admin, q="logitech")["items"][0]["code"] == "001"   # se busca también en las columnas


def test_import_validates_types_duplicates_and_never_blanks_existing_values(ctx, admin):
    obs = _cols(ctx, admin)["Observaciones"]
    _info, run = _import(ctx, admin, custom=[{"column_id": obs["id"], "header": "Observaciones"}])
    ctx.sync.apply(admin, run["id"])
    bad = _xlsx([["Código", "Producto", "Precio", "Garantía", "Observaciones", "Código"],
                 ["001", "Teclado", 50000, "doce", None, "x"],
                 ["003", "Monitor", 900000, 12, "Nuevo", "y"]])
    info = ctx.sync.inspect_upload(admin, "b.xlsx", bad)
    assert info["duplicate_headers"] == ["Código"]
    with pytest.raises(ValidationError):                          # encabezado repetido: ambiguo
        ctx.sync.preview_upload(admin, "b.xlsx", bad, {"columns": {"code": "Código", "description": "Producto",
                                                                   "price": "Precio"}})
    fixed = _xlsx([["Código", "Producto", "Precio", "Garantía", "Observaciones"],
                   ["001", "Teclado", 50000, "doce", None],
                   ["003", "Monitor", 900000, 12, "Nuevo"]])
    with pytest.raises(ValidationError):                          # misma columna del archivo asignada dos veces
        _import(ctx, admin, fixed, custom=[{"column_id": obs["id"], "header": "Producto"}])
    with pytest.raises(ValidationError):                          # nombre de campo principal
        _import(ctx, admin, fixed, custom=[{"new": {"name": "Precio sin descuento"}, "header": "Garantía"}])
    with pytest.raises(ValidationError):                          # nombres nuevos repetidos
        _import(ctx, admin, fixed, custom=[{"new": {"name": "Garantía"}, "header": "Garantía"},
                                           {"new": {"name": "garantia"}, "header": "Observaciones"}])
    _info, run = _import(ctx, admin, fixed, custom=[
        {"new": {"name": "Garantía (meses)", "data_type": "entero"}, "header": "Garantía"},
        {"column_id": obs["id"], "header": "Observaciones"}])
    s = run["summary"]
    assert s["counts"]["invalid"] == 1 and "no es un número" in s["invalid"][0]["errors"][0]   # fila inválida informada
    applied = ctx.sync.apply(admin, run["id"])["summary"]["applied"]
    assert applied["created"] == 1 and applied["skipped"] == 1
    items = {p["code"]: p for p in ctx.inventory.list(admin)["items"]}
    assert items["001"]["custom"][str(obs["id"])] == "Revisar proveedor"     # la celda vacía no borró la observación
    garantia = _cols(ctx, admin)["Garantía (meses)"]
    assert items["003"]["custom"][str(garantia["id"])] == "12"


def test_discarded_preview_creates_no_columns(ctx, admin):
    _info, run = _import(ctx, admin, custom=[{"new": {"name": "Marca"}, "header": "Marca"}])
    ctx.sync.discard(admin, run["id"])
    assert "Marca" not in _cols(ctx, admin) and ctx.inventory.list(admin)["total"] == 0


# ------------------------------------------------------------------ 5-8. administrar columnas después
def test_5_to_8_manage_columns_after_creating_the_inventory(ctx, admin, product):
    col = ctx.inventory.columns.create(admin, {"name": "Proveedor", "data_type": "texto", "description": "Quién lo surte"})
    vence = ctx.inventory.columns.create(admin, {"name": "Vence", "data_type": "fecha"})
    estado = ctx.inventory.columns.create(admin, {"name": "Estado del producto", "data_type": "lista",
                                                  "options": ["Nuevo", "Usado"], "required": True, "default_value": "nuevo"})
    assert estado["default_value"] == "Nuevo" and estado["filled"] == 1     # el producto existente toma el predeterminado
    p = ctx.inventory.update(admin, product["id"], {"custom": {str(col["id"]): "Andina", str(vence["id"]): "31/12/2026"}})
    assert p["custom"][str(vence["id"])] == "2026-12-31" and p["custom"][str(estado["id"])] == "Nuevo"
    with pytest.raises(ValidationError):
        ctx.inventory.update(admin, product["id"], {"custom": {str(vence["id"]): "mañana"}})
    with pytest.raises(ValidationError):                                    # obligatoria: no se vacía
        ctx.inventory.update(admin, product["id"], {"custom": {str(estado["id"]): ""}})
    with pytest.raises(ValidationError):                                    # obligatoria sin predeterminado
        ctx.inventory.columns.create(admin, {"name": "Lote", "required": True})
    with pytest.raises(ValidationError):                                    # nombre repetido
        ctx.inventory.columns.create(admin, {"name": "proveedor"})

    # 6. editar: nombre, descripción, opciones y tipo solo si la conversión es segura
    edited = ctx.inventory.columns.update(admin, col["id"], {"name": "Proveedor principal", "version": col["version"]})
    assert edited["column"]["name"] == "Proveedor principal"
    with pytest.raises(ConflictError):
        ctx.inventory.columns.update(admin, col["id"], {"name": "X", "version": col["version"]})
    check = ctx.inventory.columns.update(admin, col["id"], {"data_type": "entero"}, dry_run=True)
    assert check["dry_run"] and check["impact"]["invalid_count"] == 1           # «Andina» no es un número
    with pytest.raises(ValidationError):
        ctx.inventory.columns.update(admin, col["id"], {"data_type": "entero"})
    with pytest.raises(ValidationError):                                    # quitar una opción en uso
        ctx.inventory.columns.update(admin, estado["id"], {"options": ["Usado"]})
    widened = ctx.inventory.columns.update(admin, estado["id"], {"options": ["Nuevo", "Usado", "Dañado"]})
    assert widened["column"]["options"] == ["Nuevo", "Usado", "Dañado"]
    as_text = ctx.inventory.columns.update(admin, vence["id"], {"data_type": "texto"})
    assert as_text["impact"]["values"] == 1 and as_text["impact"]["invalid_count"] == 0

    # 7. archivar conserva los datos; eliminar informa y borra
    ctx.inventory.columns.set_active(admin, vence["id"], False)
    assert str(vence["id"]) not in ctx.inventory.get(admin, product["id"])["custom"]
    ctx.inventory.columns.set_active(admin, vence["id"], True)
    assert ctx.inventory.get(admin, product["id"])["custom"][str(vence["id"])] == "2026-12-31"
    preview = ctx.inventory.columns.delete(admin, col["id"], dry_run=True)
    assert preview["values"] == 1 and _cols(ctx, admin).get("Proveedor principal")
    assert ctx.inventory.columns.delete(admin, col["id"])["values"] == 1
    assert "Proveedor principal" not in _cols(ctx, admin)
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM inventory_custom_values WHERE column_id = ?", (col["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'inventario.columna_eliminar'").fetchone()[0] == 1

    # 8. reordenar
    ids = [c["id"] for c in ctx.inventory.columns.list(admin)["columns"]]
    ctx.inventory.columns.reorder(admin, list(reversed(ids)))
    assert [c["id"] for c in ctx.inventory.columns.list(admin)["columns"]] == list(reversed(ids))
    with pytest.raises(ConflictError):
        ctx.inventory.columns.reorder(admin, ids[:1])


# ------------------------------------------------------------------ 9-11. compatibilidad, exportación, persistencia
def test_9_10_11_old_records_export_and_restart(tmp_path, ctx, admin, product):
    # 9. un producto creado antes de las columnas sigue funcionando (vender, mover, editar)
    assert ctx.inventory.get(admin, product["id"])["custom"] == {}
    ctx.inventory.update(admin, product["id"], {"description": "Martillo de uña 16 oz"})
    marca = ctx.inventory.columns.create(admin, {"name": "Marca"})
    disponible = ctx.inventory.columns.create(admin, {"name": "Garantía", "data_type": "si_no"})
    ctx.inventory.update(admin, product["id"], {"custom": {str(marca["id"]): "Stanley", str(disponible["id"]): "sí"}})
    # 10. exportación con las columnas en su orden
    data, _name, _mime = ctx.inventory.export(admin, "xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    header = [c.value for c in ws[1]]
    assert header[-3:] == ["Observaciones", "Marca", "Garantía"]
    assert [c.value for c in ws[2]][-3:] == [None, "Stanley", "Sí"]
    csv_data, _n, _m = ctx.inventory.export(admin, "csv")
    assert "Stanley" in csv_data.decode("utf-8-sig")
    # 11. tras reiniciar, columnas, orden y valores siguen ahí
    restarted = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    adm = restarted.auth.login("admin", ADMIN_PASSWORD).actor
    assert [c["name"] for c in restarted.inventory.columns.list(adm)["columns"]] == ["Observaciones", "Marca", "Garantía"]
    assert restarted.inventory.get(adm, product["id"])["custom"][str(marca["id"])] == "Stanley"


def test_permissions_are_enforced_by_the_server(ctx, admin, employee, product, client):
    with pytest.raises(PermissionDenied):
        ctx.inventory.columns.create(employee, {"name": "Marca"})
    assert ctx.inventory.columns.list(employee)["columns"][0]["name"] == "Observaciones"   # puede consultarlas
    with pytest.raises(PermissionDenied):
        ctx.inventory.columns.list(employee, include_archived=True)
    assert "inventario.columnas" not in perms.ASSIGNABLE_TO_EMPLOYEE      # exclusivo del administrador
    login(client)
    created = client.post("/api/inventory/columns", json={"name": "Marca", "data_type": "texto"})
    assert created.status_code == 200, created.text
    col = created.json()
    assert client.post("/api/inventory/columns", json={"name": "X", "is_system": 1}).status_code == 422
    r = client.put(f"/api/products/{product['id']}", json={"custom": {str(col["id"]): "Truper"}, "version": product["version"]})
    assert r.status_code == 200 and r.json()["custom"][str(col["id"])] == "Truper"
    assert client.put("/api/inventory/columns/order", json={"ids": [col["id"]]}).status_code == 409
    assert client.delete(f"/api/inventory/columns/{col['id']}?dry_run=true").json()["values"] == 1
    assert client.post(f"/api/inventory/columns/{col['id']}/archive").json()["active"] == 0
