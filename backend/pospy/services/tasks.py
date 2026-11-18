"""Tareas: asignadas (a una o varias personas, opcionalmente dentro de un grupo de trabajo) o personales.

Tipos (columna personal):
- Personales (personal = 1): cada persona las crea para sí misma; solo ella las ve, edita o elimina. Ni
  un administrador las ve (para él no existen: 404) y no se copian al historial de actividad.
- Asignadas (personal = 0), con «tareas.gestionar»:
  * De un grupo de trabajo (group_id): solo el administrador DUEÑO del grupo las crea y gestiona, y solo
    puede asignarlas a integrantes activos de ese grupo. Un responsable ve la tarea mientras siga siendo
    integrante activo; nadie más la ve (ni otros administradores).
  * Sin grupo (las de antes, o empleados del negocio sin cuenta de acceso): las gestiona cualquier
    persona con «tareas.gestionar», igual que antes.

Responsables (task_assignees): cada uno tiene su estado individual (pendiente, en_curso, completada).
El responsable solo cambia SU estado, comenta o pide cambios; no edita la tarea, ni la reasigna, ni
cambia prioridad o fechas, ni la elimina.

Estado general (tasks.status): pendiente, en_curso, en_revision, completada o cancelada. Se recalcula
con el avance de los responsables: pasa a «completada» solo cuando TODOS terminaron. El administrador
puede además marcarla En revisión, Completada o Cancelada. Una tarea cancelada no admite avances.

Historial (task_events): creación, ediciones, cambios de responsables y de estado, avances, comentarios
y solicitudes de cambio. Una tarea asignada solo se elimina si nadie registró avance ni comentarios;
si no, se cancela (así no se pierde el historial).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError

STATUSES = ("pendiente", "en_curso", "en_revision", "completada", "cancelada")
PERSONAL_STATUSES = ("pendiente", "en_curso", "completada")
INDIVIDUAL = ("pendiente", "en_curso", "completada")
PRIORITIES = ("baja", "media", "alta", "urgente")
SCOPES = ("asignadas", "personales")
MAX_ASSIGNEES = 50
SELECT = ("SELECT t.*, g.public_id AS group_public_id, g.name AS group_name, g.owner_id AS group_owner_id,"
          " g.status AS group_status, c.full_name AS created_by_name"
          " FROM tasks t LEFT JOIN work_groups g ON g.id = t.group_id LEFT JOIN users c ON c.id = t.created_by")
ORDER = (" ORDER BY t.status IN ('completada','cancelada'), t.due_date IS NULL, t.due_date,"
         " CASE t.priority WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, t.id DESC LIMIT 500")


class TaskService:
    def __init__(self, db, hub=None):
        self.db = db
        self.hub = hub   # canal de tiempo real (opcional): avisa los cambios a las personas involucradas

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor, assignee_id: int | None = None, status: str = "", scope: str = "asignadas",
             priority: str = "", group: str = "", due_from: str = "", due_to: str = "", my_status: str = "") -> list[dict]:
        if scope not in SCOPES:
            raise ValidationError("Tipo de tarea no válido.")
        where, params = [], []
        if scope == "personales":
            if assignee_id not in (None, actor.id):
                raise PermissionDenied("Las tareas personales son privadas.")
            where += ["t.personal = 1", "EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id AND a.user_id = ?)"]
            params.append(actor.id)
        else:
            if not actor.can("tareas.gestionar") and assignee_id not in (None, actor.id):
                raise PermissionDenied("Solo puede consultar sus propias tareas.")
            where.append("t.personal = 0")
            mine = ("(EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id AND a.user_id = ?) AND (t.group_id IS NULL"
                    " OR EXISTS (SELECT 1 FROM work_group_members m WHERE m.group_id = t.group_id AND m.user_id = ?"
                    " AND m.status = 'activo')))")
            if actor.can("tareas.gestionar"):
                where.append(f"((t.group_id IS NULL OR g.owner_id = ?) OR {mine})")
                params += [actor.id, actor.id, actor.id]
            else:
                where.append(mine)
                params += [actor.id, actor.id]
            if assignee_id is not None:
                where.append("EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id AND a.user_id = ?)")
                params.append(assignee_id)
            if group:
                where.append("g.public_id = ?")
                params.append(group[:20])
        if status == "abiertas":
            where.append("t.status IN ('pendiente','en_curso','en_revision')")
        elif status:
            if status not in STATUSES:
                raise ValidationError("Estado no válido.")
            where.append("t.status = ?")
            params.append(status)
        if my_status:
            if my_status not in INDIVIDUAL:
                raise ValidationError("Estado no válido.")
            where.append("EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id AND a.user_id = ? AND a.status = ?)")
            params += [actor.id, my_status]
        if priority:
            if priority not in PRIORITIES:
                raise ValidationError("Prioridad no válida.")
            where.append("t.priority = ?")
            params.append(priority)
        for value, op in ((due_from, ">="), (due_to, "<=")):
            if value:
                _date(value, "due_date")
                where.append(f"t.due_date {op} ?")
                params.append(value)
        with self.db.read() as conn:
            tasks = [dict(r) for r in conn.execute(SELECT + " WHERE " + " AND ".join(where) + ORDER, params)]
            self._attach(conn, actor, tasks)
        return tasks

    def get(self, actor: Actor, task_id: int) -> dict:
        """Detalle con responsables e historial (comentarios incluidos)."""
        with self.db.read() as conn:
            task, _ = self._visible(conn, actor, task_id)
            self._attach(conn, actor, [task])
            task["events"] = [_event_out(dict(r)) for r in conn.execute(
                "SELECT e.*, u.full_name AS user_name FROM task_events e LEFT JOIN users u ON u.id = e.user_id"
                " WHERE e.task_id = ? ORDER BY e.id DESC LIMIT 200", (task_id,))]
        return task

    def assignees(self, actor: Actor) -> list[dict]:
        """Personas activas para tareas sin grupo (con o sin cuenta de acceso)."""
        actor.require("tareas.gestionar")
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT id, full_name, role FROM users WHERE active = 1"
                                                  " ORDER BY full_name COLLATE NOCASE")]

    def groups(self, actor: Actor) -> list[dict]:
        """Grupos activos que administra esta persona, con sus integrantes activos (a quienes puede asignar)."""
        actor.require("tareas.gestionar")
        with self.db.read() as conn:
            groups = [dict(r) for r in conn.execute(
                "SELECT id, public_id, name FROM work_groups WHERE owner_id = ? AND status = 'activo'"
                " ORDER BY name COLLATE NOCASE", (actor.id,))]
            for g in groups:
                g["members"] = [dict(r) for r in conn.execute(
                    "SELECT u.id, u.full_name FROM work_group_members m JOIN users u ON u.id = m.user_id"
                    " WHERE m.group_id = ? AND m.status = 'activo' AND u.active = 1 ORDER BY u.full_name COLLATE NOCASE",
                    (g.pop("id"),))]
        return groups

    # ------------------------------------------------------------------ alta
    def create(self, actor: Actor, data: dict) -> dict:
        personal = bool(data.get("personal"))
        if not personal:
            actor.require("tareas.gestionar")
        fields = _fields(data)
        if not fields["title"]:
            raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
        with self.db.tx() as conn:
            group = None
            if personal:
                if data.get("group"):
                    raise ValidationError("Una tarea personal no pertenece a un grupo.")
                people = [actor.id]     # siempre de quien la crea: se ignora cualquier responsable enviado
            else:
                group = self._own_group(conn, actor, data.get("group")) if data.get("group") else None
                people = _assignee_ids(conn, _requested(data), group)
            now = iso()
            task_id = conn.execute(
                "INSERT INTO tasks(title, description, notes, group_id, priority, due_date, created_by, created_at,"
                " updated_at, personal) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fields["title"], fields["description"], fields["notes"], group["id"] if group else None,
                 fields["priority"] or "media", fields["due_date"], actor.id, now, now, int(personal))).lastrowid
            for uid in people:
                conn.execute("INSERT INTO task_assignees(task_id, user_id, assigned_at, updated_at) VALUES (?,?,?,?)",
                             (task_id, uid, now, now))
            _log(conn, task_id, actor, "creada", {"responsables": _names(conn, people),
                                                   **({"grupo": group["name"]} if group else {})})
            if not personal:
                record(conn, actor, "tarea.crear", "task", task_id, {"titulo": fields["title"], "responsables": people,
                                                                     "grupo": group["public_id"] if group else None})
            task = self._full(conn, actor, task_id)
        self._notify(task)
        return task

    # ------------------------------------------------------------------ edición
    def update(self, actor: Actor, task_id: int, data: dict) -> dict:
        allowed = {"title", "description", "notes", "assignee_id", "assignee_ids", "priority", "due_date", "status", "version"}
        if set(data) - allowed:
            raise ValidationError("Campos no permitidos: " + ", ".join(sorted(set(data) - allowed)))
        with self.db.tx() as conn:
            task, access = self._visible(conn, actor, task_id)
            if access == "assignee":
                # Quien recibió la tarea solo cambia su propio estado (compatibilidad: PUT {status}).
                if set(data) - {"status", "version"}:
                    raise PermissionDenied("Solo puede cambiar su estado en las tareas que le asignaron.")
                updated = (self._progress_conn(conn, actor, task, data["status"], data.get("version")) if "status" in data
                           else self._full(conn, actor, task_id))
                removed = []
            else:
                updated, removed = self._edit_conn(conn, actor, task, data)
        self._notify(updated, also=removed)
        return updated

    def _edit_conn(self, conn: sqlite3.Connection, actor: Actor, task: dict, data: dict) -> tuple[dict, list[int]]:
        """Edición completa por quien gestiona la tarea (o por el dueño de una tarea personal)."""
        task_id = task["id"]
        if "version" in data and data["version"] is not None and int(data["version"]) != task["version"]:
            raise ConflictError("Otra persona modificó esta tarea. Recargue y vuelva a intentarlo.")
        fields = _fields({**task, **{k: v for k, v in data.items() if k not in ("version", "assignee_id", "assignee_ids")}})
        if not fields["title"]:
            raise ValidationError("Faltan datos.", {"title": "Escriba la tarea."})
        status = data.get("status", task["status"])
        if status not in (PERSONAL_STATUSES if task["personal"] else STATUSES):
            raise ValidationError("Estado no válido.", {"status": "Elija un estado de la lista."})
        current = _assignee_rows(conn, task_id)
        before_people = [a["user_id"] for a in current]
        people = before_people
        if task["personal"]:
            if any(k in data for k in ("assignee_id", "assignee_ids")) and _requested(data) != [actor.id]:
                raise PermissionDenied("Una tarea personal no se puede asignar a otra persona.")
        elif any(k in data for k in ("assignee_id", "assignee_ids")):
            group = conn.execute("SELECT * FROM work_groups WHERE id = ?", (task["group_id"],)).fetchone() if task["group_id"] else None
            people = _assignee_ids(conn, _requested(data), dict(group) if group else None, keep=set(before_people))
        now = iso()
        added = [u for u in people if u not in before_people]
        removed = [u for u in before_people if u not in people]
        for uid in removed:
            conn.execute("DELETE FROM task_assignees WHERE task_id = ? AND user_id = ?", (task_id, uid))
        for uid in added:
            conn.execute("INSERT INTO task_assignees(task_id, user_id, assigned_at, updated_at) VALUES (?,?,?,?)",
                         (task_id, uid, now, now))
        if task["personal"] and status != task["status"]:
            _set_individual(conn, task_id, actor.id, status, now)
        elif not task["personal"] and (added or removed) and status == task["status"] and status not in ("cancelada", "en_revision"):
            status = _derived(conn, task_id)
        completed_at = (task["completed_at"] or now) if status == "completada" else None
        conn.execute("UPDATE tasks SET title = ?, description = ?, notes = ?, priority = ?, due_date = ?, status = ?,"
                     " completed_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                     (fields["title"], fields["description"], fields["notes"], fields["priority"] or task["priority"],
                      fields["due_date"], status, completed_at, now, task_id))
        changes = {k: {"antes": task[k], "despues": v} for k, v in
                   (("title", fields["title"]), ("description", fields["description"]), ("notes", fields["notes"]),
                    ("priority", fields["priority"] or task["priority"]), ("due_date", fields["due_date"]))
                   if task[k] != v}
        if changes:
            _log(conn, task_id, actor, "edicion", changes)
        if added or removed:
            _log(conn, task_id, actor, "responsables", {"agregados": _names(conn, added), "retirados": _names(conn, removed)})
        if status != task["status"]:
            _log(conn, task_id, actor, "estado", {"antes": task["status"], "despues": status})
        if not task["personal"] and (changes or added or removed or status != task["status"]):
            record(conn, actor, "tarea.actualizar", "task", task_id,
                   {**changes, **({"responsables": {"agregados": added, "retirados": removed}} if added or removed else {}),
                    **({"status": {"antes": task["status"], "despues": status}} if status != task["status"] else {})})
        return self._full(conn, actor, task_id), removed

    def set_my_status(self, actor: Actor, task_id: int, status: str) -> dict:
        """El responsable cambia SU estado individual (iniciar, completar o volver a pendiente)."""
        with self.db.tx() as conn:
            task, _ = self._visible(conn, actor, task_id)
            updated = self._progress_conn(conn, actor, task, status, None)
        self._notify(updated)
        return updated

    def _progress_conn(self, conn: sqlite3.Connection, actor: Actor, task: dict, status: str, version) -> dict:
        if status not in INDIVIDUAL:
            raise ValidationError("Estado no válido.", {"status": "Elija Pendiente, En progreso o Completada."})
        mine = conn.execute("SELECT * FROM task_assignees WHERE task_id = ? AND user_id = ?", (task["id"], actor.id)).fetchone()
        if mine is None:
            raise PermissionDenied("Usted no es responsable de esta tarea.")
        if task["status"] == "cancelada":
            raise ValidationError("La tarea fue cancelada: ya no admite avances.")
        if version is not None and int(version) != task["version"]:
            raise ConflictError("La tarea cambió. Recargue y vuelva a intentarlo.")
        if mine["status"] == status:
            return self._full(conn, actor, task["id"])
        now = iso()
        _set_individual(conn, task["id"], actor.id, status, now)
        general = status if task["personal"] else _derived(conn, task["id"])
        completed_at = (task["completed_at"] or now) if general == "completada" else None
        conn.execute("UPDATE tasks SET status = ?, completed_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                     (general, completed_at, now, task["id"]))
        _log(conn, task["id"], actor, "avance", {"antes": mine["status"], "despues": status})
        if general != task["status"]:
            _log(conn, task["id"], None, "estado", {"antes": task["status"], "despues": general, "automatico": True})
        if not task["personal"]:
            record(conn, actor, "tarea.avance", "task", task["id"], {"estado_individual": status, "estado_general": general})
        return self._full(conn, actor, task["id"])

    def comment(self, actor: Actor, task_id: int, text: str, request_change: bool = False) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValidationError("Escriba el comentario.", {"comment": "El comentario está vacío."})
        if len(text) > 1000:
            raise ValidationError("Comentario demasiado largo.", {"comment": "Máximo 1000 caracteres."})
        with self.db.tx() as conn:
            task, access = self._visible(conn, actor, task_id)
            kind = "solicitud" if request_change and access == "assignee" else "comentario"
            _log(conn, task_id, actor, kind, None, text)
            conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (iso(), task_id))
        self._notify(task)
        return self.get(actor, task_id)

    def delete(self, actor: Actor, task_id: int) -> dict:
        with self.db.tx() as conn:
            task, access = self._visible(conn, actor, task_id)
            if not task["personal"]:
                if access != "manage":
                    raise PermissionDenied("No puede eliminar una tarea que le asignaron. Puede cambiar su estado.")
                progress = conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id = ? AND kind IN ('avance','comentario','solicitud')",
                                        (task_id,)).fetchone()[0]
                if progress:
                    raise ValidationError("La tarea ya tiene avances o comentarios: cancélela en lugar de eliminarla para"
                                          " conservar su historial.")
                people = [a["user_id"] for a in _assignee_rows(conn, task_id)]
                record(conn, actor, "tarea.eliminar", "task", task_id,
                       {"titulo": task["title"], "responsables": people, "estado": task["status"]})
            task["assignees"] = [{"user_id": a["user_id"]} for a in _assignee_rows(conn, task_id)]
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._notify(task)
        return {"deleted": task_id}

    # ------------------------------------------------------------------ auxiliares
    def _visible(self, conn: sqlite3.Connection, actor: Actor, task_id: int) -> tuple[dict, str]:
        """La tarea y el tipo de acceso ('manage' o 'assignee'); si no la puede ver, «no encontrada»."""
        row = conn.execute(SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if row is None:
            raise NotFoundError("Tarea no encontrada.")
        task = dict(row)
        is_assignee = conn.execute("SELECT 1 FROM task_assignees WHERE task_id = ? AND user_id = ?",
                                   (task_id, actor.id)).fetchone() is not None
        if task["personal"]:
            if is_assignee:
                return task, "manage"
            raise NotFoundError("Tarea no encontrada.")
        if actor.can("tareas.gestionar") and (task["group_id"] is None or task["group_owner_id"] == actor.id):
            return task, "manage"
        if is_assignee and (task["group_id"] is None or conn.execute(
                "SELECT 1 FROM work_group_members WHERE group_id = ? AND user_id = ? AND status = 'activo'",
                (task["group_id"], actor.id)).fetchone()):
            return task, "assignee"
        raise NotFoundError("Tarea no encontrada.")

    def _full(self, conn: sqlite3.Connection, actor: Actor, task_id: int) -> dict:
        task = dict(conn.execute(SELECT + " WHERE t.id = ?", (task_id,)).fetchone())
        self._attach(conn, actor, [task])
        return task

    @staticmethod
    def _attach(conn: sqlite3.Connection, actor: Actor, tasks: list[dict]) -> None:
        """Responsables, avance, estado propio y si esta persona gestiona cada tarea."""
        if not tasks:
            return
        ids = [t["id"] for t in tasks]
        by_task: dict[int, list[dict]] = {i: [] for i in ids}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for r in conn.execute(
                    "SELECT a.*, u.full_name, u.active AS user_active, t.group_id,"
                    " (t.group_id IS NULL OR EXISTS (SELECT 1 FROM work_group_members m WHERE m.group_id = t.group_id"
                    "  AND m.user_id = a.user_id AND m.status = 'activo')) AS in_group"
                    " FROM task_assignees a JOIN users u ON u.id = a.user_id JOIN tasks t ON t.id = a.task_id"
                    f" WHERE a.task_id IN ({','.join('?' * len(chunk))}) ORDER BY u.full_name COLLATE NOCASE", chunk):
                a = dict(r)
                a.pop("task_id")
                a.pop("group_id")
                by_task[r["task_id"]].append(a)
        for t in tasks:
            people = by_task[t["id"]]
            t["assignees"] = people
            t["progress"] = {"done": sum(1 for a in people if a["status"] == "completada"), "total": len(people)}
            mine = next((a for a in people if a["user_id"] == actor.id), None)
            t["my_status"] = mine["status"] if mine else None
            t["can_manage"] = bool(t["personal"] and mine) or (not t["personal"] and actor.can("tareas.gestionar")
                                                                and (t["group_id"] is None or t["group_owner_id"] == actor.id))
            t.pop("group_owner_id", None)
            if t["personal"]:
                t["assignee_id"] = actor.id if mine else None

    def _own_group(self, conn: sqlite3.Connection, actor: Actor, public_id: str) -> dict:
        actor.require("grupos.gestionar")
        row = conn.execute("SELECT * FROM work_groups WHERE public_id = ?", (str(public_id)[:20],)).fetchone()
        if row is None or row["owner_id"] != actor.id:
            raise NotFoundError("Grupo no encontrado.")   # un grupo ajeno no existe para quien no lo administra
        if row["status"] != "activo":
            raise ValidationError("El grupo está cerrado: no admite tareas nuevas.")
        return dict(row)

    def _notify(self, task: dict, also: list[int] = ()) -> None:
        """Avisa en vivo a los responsables, a quien creó la tarea y al dueño del grupo; las personales solo a su dueño."""
        if self.hub is None:
            return
        people = {a["user_id"] for a in task.get("assignees") or []}
        if not task["personal"]:
            people |= set(also)
            if task.get("created_by"):
                people.add(task["created_by"])
        self.hub.publish(people, {"type": "tarea", "task": task["id"]})


# ------------------------------------------------------------------ funciones de apoyo
def _date(value: str, field: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Fecha no válida.", {field: "Use el formato AAAA-MM-DD."}) from None
    return value


def _fields(data: dict) -> dict:
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    notes = (data.get("notes") or "").strip()
    if len(title) > 200 or len(description) > 2000 or len(notes) > 2000:
        raise ValidationError("Texto demasiado largo.", {"title": "Máximo 200 caracteres; descripción y observaciones, 2000."})
    due = (data.get("due_date") or "").strip() or None
    if due:
        _date(due, "due_date")
    priority = data.get("priority") or None
    if priority is not None and priority not in PRIORITIES:
        raise ValidationError("Prioridad no válida.", {"priority": "Elija Baja, Media, Alta o Urgente."})
    return {"title": title, "description": description, "notes": notes, "due_date": due, "priority": priority}


def _requested(data: dict) -> list:
    if data.get("assignee_ids") is not None:
        return list(data["assignee_ids"])
    return [data["assignee_id"]] if data.get("assignee_id") is not None else []


def _assignee_ids(conn: sqlite3.Connection, requested: list, group: dict | None, keep: set[int] = frozenset()) -> list[int]:
    """Responsables validados: personas activas y, si la tarea es de un grupo, integrantes activos de ese grupo.

    keep: quienes ya eran responsables pueden seguir siéndolo aunque se hayan desactivado (no se pierde su avance).
    """
    people: list[int] = []
    for value in requested:
        try:
            uid = int(value)
        except (TypeError, ValueError):
            raise ValidationError("Responsable no válido.", {"assignee_ids": "Elija los responsables."}) from None
        if uid not in people:
            people.append(uid)
    if not people:
        raise ValidationError("Faltan datos.", {"assignee_ids": "Elija al menos un responsable."})
    if len(people) > MAX_ASSIGNEES:
        raise ValidationError("Demasiados responsables.", {"assignee_ids": f"Máximo {MAX_ASSIGNEES} personas por tarea."})
    for uid in people:
        user = conn.execute("SELECT full_name, active FROM users WHERE id = ?", (uid,)).fetchone()
        if user is None:
            raise ValidationError("Responsable no encontrado.", {"assignee_ids": "Elija los responsables."})
        if uid in keep:
            continue
        if not user["active"]:
            raise ValidationError(f"{user['full_name']} está desactivado.", {"assignee_ids": "Elija personas activas."})
        if group is not None and not conn.execute(
                "SELECT 1 FROM work_group_members WHERE group_id = ? AND user_id = ? AND status = 'activo'",
                (group["id"], uid)).fetchone():
            raise ValidationError(f"{user['full_name']} no es integrante activo del grupo «{group['name']}».",
                                  {"assignee_ids": "Solo puede asignar la tarea a integrantes del grupo."})
    return people


def _assignee_rows(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM task_assignees WHERE task_id = ? ORDER BY user_id", (task_id,))]


def _set_individual(conn: sqlite3.Connection, task_id: int, user_id: int, status: str, now: str) -> None:
    conn.execute("UPDATE task_assignees SET status = ?, started_at = CASE WHEN ? = 'pendiente' THEN NULL"
                 " ELSE COALESCE(started_at, ?) END, completed_at = CASE WHEN ? = 'completada' THEN ? END, updated_at = ?"
                 " WHERE task_id = ? AND user_id = ?", (status, status, now, status, now, now, task_id, user_id))


def _derived(conn: sqlite3.Connection, task_id: int) -> str:
    """Estado general según el avance: completada solo si TODOS terminaron; en curso si alguien empezó."""
    states = [r[0] for r in conn.execute("SELECT status FROM task_assignees WHERE task_id = ?", (task_id,))]
    if states and all(s == "completada" for s in states):
        return "completada"
    if any(s != "pendiente" for s in states):
        return "en_curso"
    return "pendiente"


def _names(conn: sqlite3.Connection, ids: list[int]) -> list[str]:
    if not ids:
        return []
    rows = dict(conn.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall())
    return [rows.get(i, f"#{i}") for i in ids]


def _log(conn: sqlite3.Connection, task_id: int, actor: Actor | None, kind: str, details: dict | None,
         comment: str = "") -> None:
    conn.execute("INSERT INTO task_events(task_id, user_id, kind, details, comment, created_at) VALUES (?,?,?,?,?,?)",
                 (task_id, actor.id if actor else None, kind,
                  json.dumps(details, ensure_ascii=False, default=str) if details else None, comment, iso()))


def _event_out(e: dict) -> dict:
    e["details"] = json.loads(e["details"]) if e["details"] else None
    return e
