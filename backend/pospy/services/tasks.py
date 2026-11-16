"""Tareas asignadas a empleados (y administradores).

- Con «tareas.gestionar» se crean, asignan, editan y consultan todas las tareas.
- Sin ese permiso, cada persona consulta solo las suyas y puede cambiar su estado.
- Las tareas no se eliminan (se cancelan) para conservar el historial; tampoco se pierden al
  desactivar a un empleado: siguen consultables y se pueden reasignar.
- Funcionan igual con el inicio de sesión activado o desactivado: el responsable puede ser un
  empleado sin cuenta de acceso.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError

STATUSES = ("pendiente", "en_curso", "completada", "cancelada")
SELECT = ("SELECT t.*, u.full_name AS assignee_name, u.active AS assignee_active, c.full_name AS created_by_name"
          " FROM tasks t JOIN users u ON u.id = t.assignee_id LEFT JOIN users c ON c.id = t.created_by")


class TaskService:
    def __init__(self, db):
        self.db = db

    def list(self, actor: Actor, assignee_id: int | None = None, status: str = "") -> list[dict]:
        if not actor.can("tareas.gestionar"):
            if assignee_id not in (None, actor.id):
                raise PermissionDenied("Solo puede consultar sus propias tareas.")
            assignee_id = actor.id
        where, params = [], []
        if assignee_id is not None:
            where.append("t.assignee_id = ?")
            params.append(assignee_id)
        if status == "abiertas":
            where.append("t.status IN ('pendiente','en_curso')")
        elif status:
            if status not in STATUSES:
                raise ValidationError("Estado no válido.")
            where.append("t.status = ?")
            params.append(status)
        sql = SELECT + (" WHERE " + " AND ".join(where) if where else "") + \
            " ORDER BY t.status IN ('completada','cancelada'), t.due_date IS NULL, t.due_date, t.id DESC LIMIT 500"
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def assignees(self, actor: Actor) -> list[dict]:
        """Personas activas a las que se puede asignar una tarea (con o sin cuenta de acceso)."""
        actor.require("tareas.gestionar")
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT id, full_name, role FROM users WHERE active = 1"
                                                  " ORDER BY full_name COLLATE NOCASE")]

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("tareas.gestionar")
        title, description, due = _texts(data)
        if not title:
            raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
        with self.db.tx() as conn:
            assignee = _assignee(conn, data.get("assignee_id"))
            now = iso()
            cur = conn.execute("INSERT INTO tasks(title, description, assignee_id, due_date, created_by, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?,?)", (title, description, assignee, due, actor.id, now, now))
            record(conn, actor, "tarea.crear", "task", cur.lastrowid, {"titulo": title, "responsable": assignee})
            return self._get(conn, cur.lastrowid)

    def update(self, actor: Actor, task_id: int, data: dict) -> dict:
        allowed = {"title", "description", "assignee_id", "due_date", "status", "version"}
        if set(data) - allowed:
            raise ValidationError("Campos no permitidos: " + ", ".join(sorted(set(data) - allowed)))
        manager = actor.can("tareas.gestionar")
        with self.db.tx() as conn:
            task = self._get(conn, task_id)
            if not manager:
                if task["assignee_id"] != actor.id:
                    raise PermissionDenied("Solo puede actualizar sus propias tareas.")
                if set(data) - {"status", "version"}:
                    raise PermissionDenied("Solo puede cambiar el estado de sus tareas.")
            if "version" in data and int(data["version"]) != task["version"]:
                raise ConflictError("Otra persona modificó esta tarea. Recargue y vuelva a intentarlo.")
            merged = {**task, **{k: v for k, v in data.items() if k != "version"}}
            title, description, due = _texts(merged)
            if not title:
                raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
            status = merged["status"]
            if status not in STATUSES:
                raise ValidationError("Estado no válido.", {"status": "Opción no válida."})
            assignee = _assignee(conn, merged["assignee_id"]) if "assignee_id" in data else task["assignee_id"]
            completed_at = (task["completed_at"] or iso()) if status == "completada" else None
            conn.execute("UPDATE tasks SET title = ?, description = ?, assignee_id = ?, due_date = ?, status = ?,"
                         " completed_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (title, description, assignee, due, status, completed_at, iso(), task_id))
            changes = {k: {"antes": task[k], "despues": v} for k, v in
                       (("title", title), ("assignee_id", assignee), ("due_date", due), ("status", status))
                       if task[k] != v}
            if changes:
                record(conn, actor, "tarea.actualizar", "task", task_id, changes)
            return self._get(conn, task_id)

    @staticmethod
    def _get(conn: sqlite3.Connection, task_id: int) -> dict:
        row = conn.execute(SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if not row:
            raise NotFoundError("Tarea no encontrada.")
        return dict(row)


def _texts(data: dict) -> tuple[str, str, str | None]:
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if len(title) > 200 or len(description) > 2000:
        raise ValidationError("Texto demasiado largo.", {"title": "Máximo 200 caracteres; descripción, 2000."})
    due = (data.get("due_date") or "").strip() or None
    if due:
        try:
            date.fromisoformat(due)
        except ValueError:
            raise ValidationError("Fecha no válida.", {"due_date": "Use el formato AAAA-MM-DD."}) from None
    return title, description, due


def _assignee(conn: sqlite3.Connection, user_id) -> int:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise ValidationError("Faltan datos.", {"assignee_id": "Elija el responsable."}) from None
    row = conn.execute("SELECT active FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        raise ValidationError("Responsable no encontrado.", {"assignee_id": "Elija el responsable."})
    if not row["active"]:
        raise ValidationError("El responsable está desactivado.", {"assignee_id": "Elija una persona activa."})
    return uid
