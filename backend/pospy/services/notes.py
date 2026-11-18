"""Notas personales: cada persona crea, consulta, busca, edita y elimina SOLO las suyas.

La nota de otra persona no existe para quien la pide (404), sea empleado o administrador. Las notas
no se copian al historial de actividad, porque los administradores pueden leerlo.
"""
from __future__ import annotations

import sqlite3

from ..core.actor import Actor
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, ValidationError

TITLE_MAX = 200
CONTENT_MAX = 20000


class NoteService:
    def __init__(self, db):
        self.db = db

    def list(self, actor: Actor, q: str = "") -> list[dict]:
        sql, params = "SELECT * FROM notes WHERE owner_id = ?", [actor.id]
        q = (q or "").strip()[:100]
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += " AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"
            params += [like, like]
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY updated_at DESC, id DESC LIMIT 500", params)]

    def create(self, actor: Actor, data: dict) -> dict:
        title, content = _texts(data)
        now = iso()
        with self.db.tx() as conn:
            cur = conn.execute("INSERT INTO notes(owner_id, title, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                               (actor.id, title, content, now, now))
            return self._own(conn, actor, cur.lastrowid)

    def update(self, actor: Actor, note_id: int, data: dict) -> dict:
        with self.db.tx() as conn:
            note = self._own(conn, actor, note_id)
            if data.get("version") is not None and int(data["version"]) != note["version"]:
                raise ConflictError("Esta nota cambió en otra ventana. Recargue y vuelva a intentarlo.")
            title, content = _texts({**note, **{k: v for k, v in data.items() if k in ("title", "content")}})
            conn.execute("UPDATE notes SET title = ?, content = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (title, content, iso(), note_id))
            return self._own(conn, actor, note_id)

    def delete(self, actor: Actor, note_id: int) -> dict:
        with self.db.tx() as conn:
            self._own(conn, actor, note_id)
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return {"deleted": note_id}

    @staticmethod
    def _own(conn: sqlite3.Connection, actor: Actor, note_id: int) -> dict:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, actor.id)).fetchone()
        if row is None:
            raise NotFoundError("Nota no encontrada.")
        return dict(row)


def _texts(data: dict) -> tuple[str, str]:
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if len(title) > TITLE_MAX or len(content) > CONTENT_MAX:
        raise ValidationError("Texto demasiado largo.", {"title": f"Título: máximo {TITLE_MAX} caracteres; nota: {CONTENT_MAX}."})
    if not title and not content:
        raise ValidationError("La nota está vacía.", {"content": "Escriba un título o el contenido de la nota."})
    return title, content
