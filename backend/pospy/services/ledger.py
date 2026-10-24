"""Libro diario: asientos balanceados, idempotentes por origen e inmutables (se corrigen con reversos).

Reglas de contabilización (contabilidad de gestión, partida doble):

  Venta              Dr Caja/Bancos (parte pagada)   Dr Clientes (parte a crédito)
                     Cr Ingresos por ventas (base)   Cr IVA por pagar
                     Dr Costo de ventas              Cr Inventario            (al costo promedio)
  Devolución         Dr Devoluciones en ventas (base) Dr IVA por pagar
                     Cr Caja/Bancos (reembolso)       Cr Clientes (si reduce cartera)
                     Dr Inventario                    Cr Costo de ventas
  Anulación de venta reverso exacto del asiento de la venta
  Cobro de cartera   Dr Caja/Bancos                   Cr Clientes
  Factura proveedor  Dr Inventario o gasto elegido    Cr Proveedores
  Pago a proveedor   Dr Proveedores                   Cr Caja/Bancos
  Entrada inventario Dr Inventario  Cr Caja/Bancos | Proveedores | Capital (inventario inicial) | Otros ingresos
  Salida inventario  Dr Pérdidas por ajustes o gasto  Cr Inventario
  Ajuste (+/-)       Inventario contra Otros ingresos (sobrante) o Pérdidas por ajustes (faltante)

Una venta a crédito NO es un cobro: solo el cobro posterior mueve Caja/Bancos.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from ..core.actor import Actor
from ..core.clock import iso
from ..core.errors import ValidationError

CASH = "1105"
BANK = "1110"
RECEIVABLE = "1305"
INVENTORY = "1435"
PAYABLE = "2205"
VAT = "2408"
CAPITAL = "3105"
SALES = "4135"
SALES_RETURNS = "4175"
OTHER_INCOME = "4295"
COGS = "6135"
INVENTORY_LOSS = "5315"


@dataclass
class Line:
    account: str | int            # código ("1105") o id
    debit: int = 0
    credit: int = 0
    memo: str = ""
    party_type: str | None = None
    party_id: int | None = None


def account_id(conn: sqlite3.Connection, ref: str | int) -> int:
    if isinstance(ref, int):
        row = conn.execute("SELECT id, active FROM accounts WHERE id = ?", (ref,)).fetchone()
    else:
        row = conn.execute("SELECT id, active FROM accounts WHERE code = ?", (ref,)).fetchone()
    if not row:
        raise ValidationError(f"La cuenta contable {ref} no existe.")
    if not row["active"]:
        raise ValidationError(f"La cuenta contable {ref} está inactiva.")
    return row["id"]


def post(conn: sqlite3.Connection, actor: Actor, entry_date: date | str, description: str, source_type: str,
         source_id: int | None, lines: list[Line], purpose: str = "principal", reverses_id: int | None = None) -> int | None:
    """Registra un asiento. Devuelve su id; None si no hay importes. Idempotente por (origen, id, propósito)."""
    lines = [ln for ln in lines if ln.debit or ln.credit]
    if not lines:
        return None
    existing = conn.execute("SELECT id FROM journal_entries WHERE source_type = ? AND source_id IS ? AND purpose = ?",
                            (source_type, source_id, purpose)).fetchone()
    if existing:
        return existing[0]
    for ln in lines:  # un importe negativo o en ambos lados se normaliza a su saldo neto
        net = ln.debit - ln.credit
        ln.debit, ln.credit = (net, 0) if net > 0 else (0, -net)
    lines = [ln for ln in lines if ln.debit or ln.credit]
    debit, credit = sum(ln.debit for ln in lines), sum(ln.credit for ln in lines)
    if debit != credit:
        raise ValidationError(f"El asiento no cuadra (débitos {debit} ≠ créditos {credit}).")
    cur = conn.execute("INSERT INTO journal_entries(entry_date, description, source_type, source_id, purpose, reverses_id,"
                       " user_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                       (str(entry_date), description[:300], source_type, source_id, purpose, reverses_id, actor.id, iso()))
    entry = cur.lastrowid
    conn.executemany("INSERT INTO journal_lines(entry_id, account_id, debit_cents, credit_cents, party_type, party_id, memo)"
                     " VALUES (?,?,?,?,?,?,?)",
                     [(entry, account_id(conn, ln.account), ln.debit, ln.credit, ln.party_type, ln.party_id, ln.memo[:200])
                      for ln in lines])
    return entry


def reverse(conn: sqlite3.Connection, actor: Actor, entry_id: int, entry_date: date | str, reason: str) -> int:
    entry = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise ValidationError("Asiento no encontrado.")
    if entry["reversed_by_id"]:
        raise ValidationError("El asiento ya fue reversado.")
    if entry["reverses_id"]:
        raise ValidationError("Un asiento de reverso no se puede reversar; registre un asiento nuevo.")
    lines = [Line(r["account_id"], debit=r["credit_cents"], credit=r["debit_cents"], memo=r["memo"],
                  party_type=r["party_type"], party_id=r["party_id"])
             for r in conn.execute("SELECT * FROM journal_lines WHERE entry_id = ?", (entry_id,))]
    new_id = post(conn, actor, entry_date, f"Reverso: {entry['description']} ({reason})"[:300], entry["source_type"],
                  entry["source_id"], lines, purpose=f"reverso:{entry['purpose']}:{entry_id}", reverses_id=entry_id)
    conn.execute("UPDATE journal_entries SET reversed_by_id = ? WHERE id = ?", (new_id, entry_id))
    return new_id


def entries_for(conn: sqlite3.Connection, source_type: str, source_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM journal_entries WHERE source_type = ? AND source_id = ? ORDER BY id",
                        (source_type, source_id)).fetchall()


def method_account(conn: sqlite3.Connection, method_id: int) -> tuple[sqlite3.Row, int | None]:
    m = conn.execute("SELECT * FROM payment_methods WHERE id = ?", (method_id,)).fetchone()
    if not m:
        raise ValidationError("Método de pago no encontrado.")
    if not m["active"]:
        raise ValidationError(f"El método de pago {m['name']} está inactivo.")
    return m, m["account_id"]
