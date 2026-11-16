"""Finanzas › Informes: informes de ingresos por periodo, cierres anticipados, historial y exportación."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ...context import AppContext
from ...core.actor import Actor
from ..deps import actor, ctx, idempotency_key
from ..models import FinancialReportNote, FinancialReportRequest, Reason
from ..serialize import out

router = APIRouter(prefix="/finance/reports", tags=["finanzas"])


@router.get("/presets")
def presets(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.financial_reports.presets(current)


@router.post("/preview")
def preview(body: FinancialReportRequest, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.preview(current, body.kind, body.date_from, body.date_to))


@router.get("")
def history(kind: str = "", date_from: str = "", date_to: str = "", q: str = "", include_replaced: bool = False,
            current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.list(current, kind, date_from, date_to, q, include_replaced))


@router.post("")
def save(body: FinancialReportRequest, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
         app: AppContext = Depends(ctx)):
    return out(app.financial_reports.save(current, body.data() | {"kind": body.kind}, key))


@router.get("/{report_id}")
def detail(report_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.detail(current, report_id))


@router.post("/{report_id}/revise")
def revise(report_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.revise(current, report_id, body.reason))


@router.post("/{report_id}/notes")
def add_note(report_id: int, body: FinancialReportNote, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.add_note(current, report_id, body.model_dump()))


@router.put("/{report_id}/notes/{note_id}")
def update_note(report_id: int, note_id: int, body: FinancialReportNote, current: Actor = Depends(actor),
                app: AppContext = Depends(ctx)):
    return out(app.financial_reports.update_note(current, report_id, note_id, body.model_dump()))


@router.delete("/{report_id}/notes/{note_id}")
def delete_note(report_id: int, note_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.financial_reports.delete_note(current, report_id, note_id))


@router.get("/{report_id}/export/{fmt}")
def export(report_id: int, fmt: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    content, filename, media_type = app.financial_reports.export(current, report_id, fmt)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
