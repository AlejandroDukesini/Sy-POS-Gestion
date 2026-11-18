"""Tareas: asignadas por un administrador o personales de cada persona.

Una sola tabla (tasks). La columna personal distingue el origen:
- Asignadas (personal = 0): con «tareas.gestionar» se crean, asignan, editan, consultan y eliminan.
  Sin ese permiso, cada persona consulta solo las que le asignaron y solo puede cambiar su estado:
  no puede editarlas, reasignarlas ni eliminarlas. Siguen existiendo aunque se desactive al
  responsable, y se pueden reasignar. El responsable puede ser un empleado sin cuenta de acceso.
- Personales (personal = 1): las crea cualquier persona para sí misma y solo ella las ve, edita o
  elimina. Ni siquiera un administrador ve las tareas personales de otra persona (para él no
  existen: 404). Tampoco se copian al historial de actividad, que los administradores pueden leer.

Estados: pendiente, en_curso (En progreso) y completada. «cancelada» solo aparece en tareas
antiguas; ya no se puede elegir.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError

STATUSES = ("pendiente", "en_curso", "completada")
LEGACY_STATUSES = ("cancelada",)
SCOPES = ("asignadas", "personales")
SELECT = ("SELECT t.*, u.full_name AS assignee_name, u.active AS assignee_active, c.full_name AS created_by_name"
          " FROM tasks t JOIN users u ON u.id = t.assignee_id LEFT JOIN users c ON c.id = t.created_by")


class TaskService:
    def __init__(self, db, hub=None):
        self.db = db
        self.hub = hub   # canal de tiempo real (opcional): avisa cambios de tareas asignadas

    def list(self, actor: Actor, assignee_id: int | None = None, status: str = "", scope: str = "asignadas") -> list[dict]:
        if scope not in SCOPES:
            raise ValidationError("Tipo de tarea no válido.")
        if scope == "personales":
            if assignee_id not in (None, actor.id):
                raise PermissionDenied("Las tareas personales son privadas.")
            where, params = ["t.personal = 1", "t.assignee_id = ?"], [actor.id]
        else:
            where, params = ["t.personal = 0"], []
            if not actor.can("tareas.gestionar"):
                if assignee_id not in (None, actor.id):
                    raise PermissionDenied("Solo puede consultar sus propias tareas.")
                assignee_id = actor.id
            if assignee_id is not None:
                where.append("t.assignee_id = ?")
                params.append(assignee_id)
        if status == "abiertas":
            where.append("t.status IN ('pendiente','en_curso')")
        elif status:
            if status not in STATUSES + LEGACY_STATUSES:
                raise ValidationError("Estado no válido.")
            where.append("t.status = ?")
            params.append(status)
        sql = SELECT + " WHERE " + " AND ".join(where) + \
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
        personal = bool(data.get("personal"))
        if not personal:
            actor.require("tareas.gestionar")
        title, description, due = _texts(data)
        if not title:
            raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
        with self.db.tx() as conn:
            # Una tarea personal es siempre de quien la crea: se ignora cualquier responsable enviado.
            assignee = actor.id if personal else _assignee(conn, data.get("assignee_id"))
            now = iso()
            cur = conn.execute("INSERT INTO tasks(title, description, assignee_id, due_date, created_by, created_at,"
                               " updated_at, personal) VALUES (?,?,?,?,?,?,?,?)",
                               (title, description, assignee, due, actor.id, now, now, int(personal)))
            if not personal:
                record(conn, actor, "tarea.crear", "task", cur.lastrowid, {"titulo": title, "responsable": assignee})
            task = self._get(conn, cur.lastrowid)
        self._notify(task)
        return task

    def update(self, actor: Actor, task_id: int, data: dict) -> dict:
        allowed = {"title", "description", "assignee_id", "due_date", "status", "version"}
        if set(data) - allowed:
            raise ValidationError("Campos no permitidos: " + ", ".join(sorted(set(data) - allowed)))
        with self.db.tx() as conn:
            task = self._visible(conn, actor, task_id)
            if task["personal"]:
                if "assignee_id" in data and data["assignee_id"] != actor.id:
                    raise PermissionDenied("Una tarea personal no se puede asignar a otra persona.")
            elif not actor.can("tareas.gestionar") and set(data) - {"status", "version"}:
                raise PermissionDenied("Solo puede cambiar el estado de las tareas que le asignaron.")
            if "version" in data and int(data["version"]) != task["version"]:
                raise ConflictError("Otra persona modificó esta tarea. Recargue y vuelva a intentarlo.")
            merged = {**task, **{k: v for k, v in data.items() if k != "version"}}
            title, description, due = _texts(merged)
            if not title:
                raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
            status = merged["status"]
            if status not in STATUSES and not (status in LEGACY_STATUSES and status == task["status"]):
                raise ValidationError("Estado no válido.", {"status": "Elija Pendiente, En progreso o Completada."})
            assignee = task["assignee_id"]
            if not task["personal"] and "assignee_id" in data:
                assignee = _assignee(conn, merged["assignee_id"])
            completed_at = (task["completed_at"] or iso()) if status == "completada" else None
            conn.execute("UPDATE tasks SET title = ?, description = ?, assignee_id = ?, due_date = ?, status = ?,"
                         " completed_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (title, description, assignee, due, status, completed_at, iso(), task_id))
            changes = {k: {"antes": task[k], "despues": v} for k, v in
                       (("title", title), ("assignee_id", assignee), ("due_date", due), ("status", status))
                       if task[k] != v}
            if changes and not task["personal"]:
                record(conn, actor, "tarea.actualizar", "task", task_id, changes)
            updated = self._get(conn, task_id)
        self._notify(updated, also=[task["assignee_id"]])
        return updated

    def delete(self, actor: Actor, task_id: int) -> dict:
        with self.db.tx() as conn:
            task = self._visible(conn, actor, task_id)
            if not task["personal"]:
                if not actor.can("tareas.gestionar"):
                    raise PermissionDenied("No puede eliminar una tarea que le asignaron. Puede cambiar su estado.")
                record(conn, actor, "tarea.eliminar", "task", task_id,
                       {"titulo": task["title"], "responsable": task["assignee_id"], "estado": task["status"]})
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._notify(task)
        return {"deleted": task_id}

    # ------------------------------------------------------------------ auxiliares
    def _visible(self, conn: sqlite3.Connection, actor: Actor, task_id: int) -> dict:
        """La tarea, si esta persona puede verla; si no, «no encontrada» (no revela que existe)."""
        task = self._get(conn, task_id)
        if task["personal"]:
            visible = task["assignee_id"] == actor.id
        else:
            visible = actor.can("tareas.gestionar") or task["assignee_id"] == actor.id
        if not visible:
            raise NotFoundError("Tarea no encontrada.")
        return task

    def _notify(self, task: dict, also: list[int] = ()) -> None:
        """Avisa en vivo al responsable y a quien asignó la tarea; las personales solo a su dueño."""
        if self.hub is None:
            return
        people = {task["assignee_id"], *(also if not task["personal"] else ())}
        if not task["personal"] and task.get("created_by"):
            people.add(task["created_by"])
        self.hub.publish(people, {"type": "tarea", "task": task["id"]})

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
