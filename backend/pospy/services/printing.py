"""Impresión de comprobantes de venta y registro de trabajos de impresión.

Modos:
  * escpos     el backend envía el ticket directamente a la impresora térmica (DIGITALPOS) por Windows.
               Una sola acción, sin diálogos. Requiere que el backend corra en el equipo con la impresora
               (aplicación de escritorio o servidor local con la impresora instalada).
  * navegador  la interfaz abre la vista del comprobante y el diálogo de impresión del navegador.
               Un navegador no permite elegir impresora ni imprimir en silencio: lo decide la persona.
"""
from __future__ import annotations

import sqlite3
from zoneinfo import ZoneInfo

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, parse_iso
from ..core.errors import ValidationError
from ..core.money import fmt_money, milli_str
from ..printing import escpos
from ..printing.printers import PrintError, list_printers, print_raw


class PrintingService:
    def __init__(self, db, settings, sales):
        self.db = db
        self.settings = settings
        self.sales = sales

    def printers(self, actor: Actor) -> dict:
        if not (actor.can("documentos.imprimir") or actor.can("ventas.vender") or actor.can("gestion.configuracion")):
            actor.require("documentos.imprimir")
        return list_printers()

    def log(self, conn: sqlite3.Connection, actor: Actor, target_type: str, target_id: int | None, label: str,
            printer: str, mode: str, copies: int, error: str | None = None) -> int:
        return conn.execute("INSERT INTO print_jobs(created_at, user_id, target_type, target_id, target_label, printer, mode,"
                            " copies, status, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (iso(), actor.id, target_type, target_id, label, printer, mode, copies,
                             "error" if error else "ok", error)).lastrowid

    def jobs(self, actor: Actor, target_type: str = "", target_id: int | None = None, limit: int = 100) -> list[dict]:
        if not (actor.can("documentos.imprimir") or actor.can("ventas.historial")):
            actor.require("documentos.imprimir")
        where, params = [], []
        if target_type:
            where.append("j.target_type = ?")
            params.append(target_type)
        if target_id:
            where.append("j.target_id = ?")
            params.append(target_id)
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT j.*, u.username FROM print_jobs j LEFT JOIN users u ON u.id = j.user_id"
                + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY j.id DESC LIMIT ?", (*params, min(500, limit)))]

    # ------------------------------------------------------------------ comprobante de venta
    def receipt_bytes(self, sale: dict) -> bytes:
        company = self.settings.get("empresa")
        conf = self.settings.get("impresion")
        sym = company["currency_symbol"]
        t = escpos.Ticket(int(conf["receipt_width_chars"]))
        t.line(company["name"], escpos.CENTER, bold=True, double=True)
        for text in (company["legal_name"], f"NIT {company['tax_id']}" if company["tax_id"] else "", company["address"],
                     company["phone"], conf["receipt_header"]):
            if text:
                t.line(text, escpos.CENTER)
        t.rule()
        t.line("COMPROBANTE DE VENTA", escpos.CENTER, bold=True)
        t.line("Documento interno - no es factura electrónica", escpos.CENTER)
        t.pair("No.", sale["number"], bold=True)
        t.pair("Fecha", parse_iso(sale["created_at"]).astimezone(ZoneInfo(company["timezone"])).strftime("%d/%m/%Y %H:%M"))
        t.pair("Atendió", sale["username"])
        if sale["customer_name"]:
            t.pair("Cliente", sale["customer_name"])
            if sale["customer_identification"]:
                t.pair("Identificación", sale["customer_identification"])
        if sale["status"] == "anulada":
            t.line("*** VENTA ANULADA ***", escpos.CENTER, bold=True)
        t.rule()
        for ln in sale["lines"]:
            t.line(f"{ln['code']} {ln['description']}")
            unit = fmt_money(ln["unit_price_cents"], sym)
            t.pair(f"  {milli_str(ln['qty_milli'])} x {unit}", fmt_money(ln["net_cents"], sym))
            if ln["discount_cents"]:
                t.pair("  Ahorro", "-" + fmt_money(ln["discount_cents"], sym))
        t.rule()
        if sale["discount_cents"]:
            t.pair("Subtotal", fmt_money(sale["gross_cents"], sym))
            t.pair("Descuentos", "-" + fmt_money(sale["discount_cents"], sym))
        t.pair("TOTAL", fmt_money(sale["total_cents"], sym), bold=True)
        if sale["tax_cents"]:
            t.pair("IVA incluido", fmt_money(sale["tax_cents"], sym))
        t.rule()
        for p in sale["payments"]:
            t.pair(p["method_name"], fmt_money(p["amount_cents"], sym))
            if p["tendered_cents"]:
                t.pair("  Recibido", fmt_money(p["tendered_cents"], sym))
        if sale["change_cents"]:
            t.pair("Cambio", fmt_money(sale["change_cents"], sym), bold=True)
        if sale.get("receivable"):
            t.pair("Saldo a crédito", fmt_money(sale["credit_cents"], sym))
            t.pair("Vence", sale["receivable"]["due_date"])
        if conf["receipt_footer"]:
            t.line()
            t.line(conf["receipt_footer"], escpos.CENTER)
        cash = any(p["method_kind"] == "efectivo" for p in sale["payments"])
        return t.finish(cut=bool(conf["receipt_cut"]), drawer=bool(conf["receipt_open_drawer"]) and cash)

    def receipt_text(self, actor: Actor, sale_id: int) -> dict:
        sale = self.sales.get(actor, sale_id)
        return {"text": escpos.plain_text(self.receipt_bytes(sale)), "sale": sale,
                "mode": self.settings.get("impresion")["receipt_mode"]}

    def print_receipt(self, actor: Actor, sale_id: int, copies: int | None = None) -> dict:
        if not (actor.can("ventas.vender") or actor.can("documentos.imprimir")):
            actor.require("ventas.vender")
        sale = self.sales.get(actor, sale_id)
        conf = self.settings.get("impresion")
        copies = max(1, min(5, int(copies or conf["receipt_copies"])))
        if conf["receipt_mode"] == "navegador":
            with self.db.tx() as conn:
                self.log(conn, actor, "venta", sale_id, sale["number"], "navegador", "navegador", copies)
            return {"mode": "navegador", "printed": False}
        data = self.receipt_bytes(sale)
        error = None
        try:
            for _ in range(copies):
                print_raw(conf["receipt_printer"], data, f"Venta {sale['number']}")
        except PrintError as exc:
            error = exc.detail
        with self.db.tx() as conn:
            self.log(conn, actor, "venta", sale_id, sale["number"], conf["receipt_printer"], "escpos", copies, error)
            record(conn, actor, "impresion.comprobante", "sale", sale_id,
                   {"impresora": conf["receipt_printer"], "copias": copies, "error": error})
        if error:
            raise PrintError(error)
        return {"mode": "escpos", "printed": True, "printer": conf["receipt_printer"], "copies": copies}

    def log_browser_print(self, actor: Actor, target_type: str, target_id: int, label: str) -> None:
        if target_type not in ("venta", "documento"):
            raise ValidationError("Tipo de impresión no válido.")
        with self.db.tx() as conn:
            self.log(conn, actor, target_type, target_id, label[:80], "navegador", "navegador", 1)

    def test_print(self, actor: Actor, printer: str | None = None) -> dict:
        actor.require("gestion.configuracion")
        conf = self.settings.get("impresion")
        name = printer or conf["receipt_printer"]
        t = escpos.Ticket(int(conf["receipt_width_chars"]))
        t.line("PRUEBA DE IMPRESIÓN", escpos.CENTER, bold=True, double=True)
        t.line("POS-PY", escpos.CENTER)
        t.rule()
        t.line("Tildes: áéíóú ÁÉÍÓÚ ñ Ñ")
        t.pair("Izquierda", "Derecha")
        t.line("1234567890" * (int(conf["receipt_width_chars"]) // 10))
        error = None
        try:
            print_raw(name, t.finish(cut=bool(conf["receipt_cut"]), drawer=False), "Prueba POS-PY")
        except PrintError as exc:
            error = exc.detail
        with self.db.tx() as conn:
            self.log(conn, actor, "prueba", None, "Prueba", name, "escpos", 1, error)
        if error:
            raise PrintError(error)
        return {"printed": True, "printer": name}
