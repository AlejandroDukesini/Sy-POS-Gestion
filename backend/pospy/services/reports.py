"""Reportes operativos (sobre ventas e inventario registrados; sin datos de ejemplo)."""
from __future__ import annotations

from datetime import timedelta

from ..core.actor import Actor
from ..core.clock import local_today, parse_date
from ..core.errors import ValidationError


class ReportService:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    def _range(self, date_from: str | None, date_to: str | None):
        end = parse_date(date_to) if date_to else local_today(self.settings.get("empresa")["timezone"])
        start = parse_date(date_from) if date_from else end - timedelta(days=29)
        if start > end:
            raise ValidationError("La fecha inicial es posterior a la final.")
        return str(start), str(end)

    def sales(self, actor: Actor, date_from: str | None = None, date_to: str | None = None) -> dict:
        actor.require("ventas.historial")
        start, end = self._range(date_from, date_to)
        with self.db.read() as conn:
            by_day = [dict(r) for r in conn.execute(
                "SELECT sale_date AS day, COUNT(*) AS sales, SUM(total_cents) AS total_cents, SUM(credit_cents) AS credit_cents"
                " FROM sales WHERE status = 'completada' AND sale_date BETWEEN ? AND ? GROUP BY sale_date ORDER BY sale_date",
                (start, end))]
            top = [dict(r) for r in conn.execute(
                "SELECT l.code, l.description, SUM(l.qty_milli - l.returned_milli) AS qty_milli,"
                " SUM(l.net_cents) AS net_cents FROM sale_lines l JOIN sales s ON s.id = l.sale_id"
                " WHERE s.status = 'completada' AND s.sale_date BETWEEN ? AND ? GROUP BY l.product_id"
                " ORDER BY net_cents DESC LIMIT 20", (start, end))]
            by_user = [dict(r) for r in conn.execute(
                "SELECT u.username, u.full_name, COUNT(*) AS sales, SUM(s.total_cents) AS total_cents FROM sales s"
                " JOIN users u ON u.id = s.user_id WHERE s.status = 'completada' AND s.sale_date BETWEEN ? AND ?"
                " GROUP BY u.id ORDER BY total_cents DESC", (start, end))]
            returns = conn.execute("SELECT COUNT(*), COALESCE(SUM(total_cents), 0) FROM sale_returns"
                                   " WHERE return_date BETWEEN ? AND ?", (start, end)).fetchone()
        total = sum(d["total_cents"] for d in by_day)
        count = sum(d["sales"] for d in by_day)
        return {"date_from": start, "date_to": end, "by_day": by_day, "top_products": top, "by_user": by_user,
                "total_cents": total, "sales": count, "average_ticket_cents": total // count if count else 0,
                "returns_count": returns[0], "returns_cents": returns[1]}

    def movements(self, actor: Actor, date_from: str | None = None, date_to: str | None = None) -> dict:
        actor.require("inventario.ver")
        start, end = self._range(date_from, date_to)
        with self.db.read() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT kind, COUNT(*) AS movements, SUM(CASE WHEN qty_milli > 0 THEN qty_milli ELSE 0 END) AS in_milli,"
                " SUM(CASE WHEN qty_milli < 0 THEN -qty_milli ELSE 0 END) AS out_milli FROM inventory_movements"
                " WHERE created_at >= ? AND created_at < date(?, '+1 day') GROUP BY kind ORDER BY kind", (start, end))]
        return {"date_from": start, "date_to": end, "by_kind": rows}
