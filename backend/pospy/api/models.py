"""Modelos de entrada de la API (validación estructural; las reglas de negocio las validan los servicios).

Los importes y cantidades se envían como texto decimal ("1234.50") para no perder precisión.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Num = str | int | float


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def data(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class Login(Strict):
    username: str = Field(max_length=60)
    password: str = Field(max_length=200)


class Setup(Strict):
    code: str = Field(max_length=40)
    username: str = Field(max_length=40)
    full_name: str = Field(max_length=120)
    password: str = Field(max_length=200)


class ChangePassword(Strict):
    current: str = Field(max_length=200)
    password: str = Field(max_length=200)


class UserCreate(Strict):
    username: str = Field(max_length=40)
    full_name: str = Field(max_length=120)
    role: Literal["admin", "employee"] = "employee"
    password: str = Field(max_length=200)
    permissions: list[str] | None = None


class UserUpdate(Strict):
    full_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "employee"] | None = None
    active: bool | None = None
    permissions: list[str] | None = None
    version: int | None = None


class PasswordReset(Strict):
    password: str = Field(max_length=200)


class Product(Strict):
    code: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=200)
    category_id: int | None = None
    unit: str | None = None
    price: Num | None = None
    discount_price: Num | None = None
    cost: Num | None = None
    tax_rate: Num | None = None
    min_stock: Num | None = None
    active: bool | None = None
    external_ref: str | None = Field(default=None, max_length=80)
    initial_stock: Num | None = None
    version: int | None = None


class Movement(Strict):
    kind: Literal["entrada", "salida", "ajuste"]
    qty: Num | None = None
    counted_qty: Num | None = None
    unit_cost: Num | None = None
    reason: str = Field(max_length=300)
    counterpart: str | None = None
    method_id: int | None = None
    supplier_id: int | None = None
    invoice_number: str | None = Field(default=None, max_length=60)
    due_date: str | None = None


class Category(Strict):
    name: str = Field(max_length=80)
    active: bool = True


class Party(Strict):
    identification: str | None = Field(default=None, max_length=40)
    name: str = Field(max_length=160)
    phone: str | None = Field(default="", max_length=60)
    email: str | None = Field(default="", max_length=120)
    address: str | None = Field(default="", max_length=200)
    credit_days: int | None = None
    payment_days: int | None = None
    active: bool = True
    version: int | None = None


class PaymentMethod(Strict):
    name: str = Field(max_length=60)
    kind: Literal["efectivo", "tarjeta", "transferencia", "credito", "otro"]
    account_code: str | None = None
    active: bool = True


class Item(Strict):
    product_id: int
    qty: Num
    discount_pct: Num | None = None


class Quote(Strict):
    lines: list[Item] = Field(max_length=500)


class SalePayment(Strict):
    method_id: int
    amount: Num
    tendered: Num | None = None
    reference: str | None = Field(default="", max_length=120)


class Checkout(Strict):
    lines: list[Item] = Field(max_length=500)
    payments: list[SalePayment] = Field(max_length=10)
    customer_id: int | None = None
    notes: str | None = Field(default="", max_length=500)
    due_date: str | None = None
    source_document_id: int | None = None


class Reason(Strict):
    reason: str = Field(max_length=300)


class ReturnLine(Strict):
    sale_line_id: int
    qty: Num


class SaleReturn(Strict):
    reason: str = Field(max_length=300)
    lines: list[ReturnLine]
    refund_method_id: int | None = None


class PrintRequest(Strict):
    printer: str | None = Field(default=None, max_length=200)
    copies: int | None = Field(default=None, ge=1, le=20)


class BrowserPrintLog(Strict):
    target_type: Literal["venta", "documento"]
    target_id: int
    label: str = Field(default="", max_length=80)


class ExtraField(Strict):
    key: str | None = Field(default=None, max_length=30)
    label: str = Field(max_length=60)
    required: bool = False


class PageSetup(Strict):
    paper: Literal["letter", "legal", "a4", "a5"] = "letter"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins_cm: float = Field(default=1.5, ge=0, le=5)
    fit_width: bool = True
    scale: int = Field(default=100, ge=10, le=400)


class DocumentType(Strict):
    code: str | None = Field(default=None, max_length=30)
    name: str = Field(max_length=60)
    prefix: str | None = Field(default="", max_length=10)
    next_number: int | None = Field(default=1, ge=1)
    numbering: bool = True
    validity_days: int = Field(default=0, ge=0, le=365)
    printer: str | None = Field(default="", max_length=200)
    page_setup: PageSetup = PageSetup()
    fields: list[ExtraField] = Field(default_factory=list, max_length=20)
    active: bool = True
    version: int | None = None


class FieldAssignment(Strict):
    field: str = Field(max_length=60)
    cell: str | None = Field(default=None, max_length=20)


class Capacity(Strict):
    capacity: int = Field(ge=1, le=500)


class Document(Strict):
    type_id: int | None = None
    number: str | None = Field(default=None, max_length=40)
    customer_id: int | None = None
    customer_name: str | None = Field(default="", max_length=160)
    customer_identification: str | None = Field(default="", max_length=40)
    customer_phone: str | None = Field(default="", max_length=60)
    customer_email: str | None = Field(default="", max_length=120)
    customer_address: str | None = Field(default="", max_length=200)
    notes: str | None = Field(default="", max_length=1000)
    extra: dict[str, str] = Field(default_factory=dict)
    lines: list[Item] = Field(max_length=500)
    version: int | None = None


class OpenItem(Strict):
    customer_id: int | None = None
    supplier_id: int | None = None
    number: str | None = Field(default=None, max_length=60)
    amount: Num
    issue_date: str | None = None
    due_date: str | None = None
    description: str | None = Field(default="", max_length=300)
    account_code: str | None = None


class OpenItemPayment(Strict):
    amount: Num
    method_id: int
    payment_date: str | None = None
    reference: str | None = Field(default="", max_length=120)


class EntryLine(Strict):
    account_code: str
    debit: Num | None = None
    credit: Num | None = None
    memo: str | None = Field(default="", max_length=200)


class ManualEntry(Strict):
    entry_date: str | None = None
    description: str = Field(max_length=300)
    lines: list[EntryLine] = Field(max_length=50)


class Expense(Strict):
    entry_date: str | None = None
    description: str = Field(max_length=300)
    account_code: str
    amount: Num
    method_id: int


class Account(Strict):
    code: str
    name: str = Field(max_length=120)
    type: Literal["activo", "pasivo", "patrimonio", "ingreso", "costo", "gasto"]
    is_cash: bool = False
    cost_behavior: Literal["fijo", "variable"] | None = None
    active: bool = True


class Reconcile(Strict):
    account_code: str
    statement_date: str
    statement_balance: Num
    line_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default="", max_length=500)


class BreakEvenOverrides(Strict):
    date_from: str | None = None
    date_to: str | None = None
    fixed_costs: Num | None = None
    price: Num | None = None
    variable_cost: Num | None = None


class Connection(Strict):
    name: str = Field(max_length=80)
    provider: Literal["excel", "carpeta", "onedrive", "gdrive"]
    config: dict[str, Any] = Field(default_factory=dict)
    is_master: bool = False
    sync_mode: Literal["manual", "intervalo"] = "manual"
    sync_interval_min: int = Field(default=60, ge=5, le=1440)
    stock_policy: Literal["informar", "ajustar"] = "informar"
    update_catalog: bool = True
    create_missing: bool = True
    active: bool = True
    version: int | None = None


class GoogleSecret(Strict):
    client_secret: str = Field(default="", max_length=200)


class Restore(Strict):
    file: str = Field(max_length=80)
    confirm: Literal["RESTAURAR"]
