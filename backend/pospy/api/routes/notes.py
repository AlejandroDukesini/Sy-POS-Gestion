"""Notas personales de la persona que inició sesión."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...context import AppContext
from ...core.actor import Actor
from ..deps import actor, ctx
from ..models import NoteIn, NoteUpdate

router = APIRouter(tags=["notas"])


@router.get("/notes")
def notes(q: str = "", current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.notes.list(current, q)


@router.post("/notes")
def create_note(body: NoteIn, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.notes.create(current, body.data())


@router.put("/notes/{note_id}")
def update_note(note_id: int, body: NoteUpdate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.notes.update(current, note_id, body.data())


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.notes.delete(current, note_id)
