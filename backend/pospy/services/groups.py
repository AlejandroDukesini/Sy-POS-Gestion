"""Grupos de trabajo: un administrador crea el grupo e invita a empleados con un enlace.

Reglas (todas se validan aquí, nunca en la interfaz):
- Solo quien tiene «grupos.gestionar» (exclusivo de administradores) crea grupos, y solo el
  administrador dueño de un grupo lo gestiona. Para cualquier otra persona un grupo ajeno no existe (404).
- El enlace lleva un token aleatorio de 256 bits; se guarda solo su SHA-256. El token NO autentica:
  quien abre el enlace debe haber iniciado sesión con su propia cuenta, y el token solo le permite
  solicitar su ingreso como integrante (nunca otorga permisos de administración).
- Un enlace vale para varias personas mientras esté vigente: no vencido, no revocado, con cupo y con
  el grupo activo. El cupo se descuenta dentro de la misma transacción (sin carreras).
- UNIQUE(group_id, user_id): no hay ingresos duplicados. Abrir de nuevo el enlace siendo integrante
  no consume cupo.
- Quien fue retirado o rechazado por el administrador solo puede volver con un enlace generado
  DESPUÉS de esa decisión.
- Desconectarse no saca a nadie del grupo: la pertenencia y la conexión en tiempo real son cosas distintas.
"""
from __future__ import annotations

import ipaddress
import json
import secrets
import sqlite3
from datetime import timedelta
from urllib.parse import urlsplit

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, now_utc, parse_iso
from ..core.errors import ConflictError, DomainError, NotFoundError, PermissionDenied, ValidationError
from ..core.ratelimit import RateLimiter
from ..core.security import token_hash
from .realtime import RealtimeHub

POLICIES = ("automatica", "aprobacion")
MEMBER_ACTIONS = ("aprobar", "rechazar", "retirar")
INVITE_PATH = "/unirse/"


class InvitationGone(DomainError):
    status = 410
    title = "Invitación no disponible"


class GroupService:
    def __init__(self, db, hub: RealtimeHub, public_url: str = "", settings=None):
        self.db = db
        self.hub = hub
        self.public_url = public_url.rstrip("/")
        self.settings = settings
        # 10 enlaces no válidos cada 15 minutos por persona y por dirección.
        self.limiter = RateLimiter(limit=10, window_s=15 * 60)

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor) -> dict:
        with self.db.read() as conn:
            owned = []
            if actor.can("grupos.gestionar"):
                owned = [dict(r) for r in conn.execute(
                    "SELECT g.public_id, g.name, g.description, g.status, g.join_policy, g.created_at,"
                    " (SELECT COUNT(*) FROM work_group_members m WHERE m.group_id = g.id AND m.status = 'activo') AS members,"
                    " (SELECT COUNT(*) FROM work_group_members m WHERE m.group_id = g.id AND m.status = 'pendiente') AS pending"
                    " FROM work_groups g WHERE g.owner_id = ? ORDER BY g.status, g.created_at DESC", (actor.id,))]
                for g in owned:
                    g["online"] = self._online_count(conn, g["public_id"])
            member_of = [dict(r) for r in conn.execute(
                "SELECT g.public_id, g.name, g.description, g.status, o.full_name AS owner_name, m.status AS my_status,"
                " m.joined_at FROM work_group_members m JOIN work_groups g ON g.id = m.group_id"
                " JOIN users o ON o.id = g.owner_id WHERE m.user_id = ? AND m.status IN ('activo','pendiente')"
                " ORDER BY g.name COLLATE NOCASE", (actor.id,))]
        return {"can_manage": actor.can("grupos.gestionar"), "owned": owned, "member_of": member_of,
                "connection": self.hub.status(actor.id)}

    def get(self, actor: Actor, public_id: str) -> dict:
        with self.db.read() as conn:
            group = self._group(conn, public_id)
            if group["owner_id"] == actor.id and actor.can("grupos.gestionar"):
                return self._owner_view(conn, group)
            mine = conn.execute("SELECT * FROM work_group_members WHERE group_id = ? AND user_id = ?"
                                " AND status IN ('activo','pendiente')", (group["id"], actor.id)).fetchone()
            if mine is None:
                raise NotFoundError("Grupo no encontrado.")
            return self._member_view(conn, group, dict(mine), actor)

    def _owner_view(self, conn: sqlite3.Connection, group: dict) -> dict:
        members = [dict(r) for r in conn.execute(
            "SELECT m.user_id, m.status, m.requested_at, m.joined_at, m.ended_at, u.full_name, u.username, u.role,"
            " u.active AS account_active, p.last_connected_at, p.last_disconnected_at,"
            " (SELECT COUNT(*) FROM user_permissions up WHERE up.user_id = u.id) AS permission_count"
            " FROM work_group_members m JOIN users u ON u.id = m.user_id LEFT JOIN user_presence p ON p.user_id = u.id"
            " WHERE m.group_id = ? ORDER BY m.status <> 'pendiente', m.status <> 'activo', u.full_name COLLATE NOCASE",
            (group["id"],))]
        for m in members:
            m["connection"] = self.hub.status(m["user_id"], known_before=bool(m["last_connected_at"]))
        now = now_utc()
        invitations = [dict(r) for r in conn.execute(
            "SELECT i.id, i.hint, i.created_at, i.expires_at, i.max_uses, i.uses, i.revoked_at, u.full_name AS created_by_name"
            " FROM work_group_invitations i JOIN users u ON u.id = i.created_by WHERE i.group_id = ?"
            " ORDER BY i.id DESC LIMIT 50", (group["id"],))]
        for inv in invitations:
            inv["status"] = _invitation_status(inv, group, now)
        events = [dict(r) for r in conn.execute(
            "SELECT e.id, e.created_at, e.type, e.details, a.full_name AS actor_name, s.full_name AS subject_name"
            " FROM work_group_events e LEFT JOIN users a ON a.id = e.actor_id LEFT JOIN users s ON s.id = e.subject_id"
            " WHERE e.group_id = ? ORDER BY e.id DESC LIMIT 30", (group["id"],))]
        for e in events:
            e["details"] = json.loads(e["details"]) if e["details"] else None
        return {"view": "admin", "group": self._public_group(conn, group), "members": members,
                "invitations": invitations, "events": events, "invite_base": self.invite_base_info()}

    def _member_view(self, conn: sqlite3.Connection, group: dict, mine: dict, actor: Actor) -> dict:
        members = []
        if group["members_visible"] and mine["status"] == "activo":
            members = [dict(r) for r in conn.execute(
                "SELECT u.full_name, m.joined_at FROM work_group_members m JOIN users u ON u.id = m.user_id"
                " WHERE m.group_id = ? AND m.status = 'activo' ORDER BY u.full_name COLLATE NOCASE", (group["id"],))]
        return {"view": "member", "group": self._public_group(conn, group),
                "me": {"status": mine["status"], "requested_at": mine["requested_at"], "joined_at": mine["joined_at"],
                       "connection": self.hub.status(actor.id)},
                "members": members, "members_visible": bool(group["members_visible"]),
                "permissions": sorted(actor.permissions)}

    @staticmethod
    def _public_group(conn: sqlite3.Connection, group: dict) -> dict:
        owner = conn.execute("SELECT full_name FROM users WHERE id = ?", (group["owner_id"],)).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM work_group_members WHERE group_id = ? AND status = 'activo'",
                             (group["id"],)).fetchone()[0]
        return {"public_id": group["public_id"], "name": group["name"], "description": group["description"],
                "status": group["status"], "join_policy": group["join_policy"],
                "members_visible": bool(group["members_visible"]), "owner_name": owner[0] if owner else "",
                "member_count": count, "created_at": group["created_at"], "closed_at": group["closed_at"],
                "version": group["version"]}

    def _online_count(self, conn: sqlite3.Connection, public_id: str) -> int:
        ids = [r[0] for r in conn.execute("SELECT m.user_id FROM work_group_members m JOIN work_groups g ON g.id = m.group_id"
                                          " WHERE g.public_id = ? AND m.status = 'activo'", (public_id,))]
        return sum(1 for uid in ids if self.hub.status(uid) == "conectado")

    # ------------------------------------------------------------------ administración del grupo
    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("grupos.gestionar")
        name, description = _texts(data)
        policy = data.get("join_policy") or "automatica"
        if policy not in POLICIES:
            raise ValidationError("Opción no válida.", {"join_policy": "Elija ingreso automático o con aprobación."})
        with self.db.tx() as conn:
            now = iso()
            public_id = _new_public_id(conn)
            cur = conn.execute("INSERT INTO work_groups(public_id, name, description, owner_id, join_policy, members_visible,"
                               " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                               (public_id, name, description, actor.id, policy, int(data.get("members_visible", True)), now, now))
            _event(conn, cur.lastrowid, actor, None, "grupo_creado", {"nombre": name})
            record(conn, actor, "grupo.crear", "work_group", public_id, {"nombre": name})
        return self.get(actor, public_id)

    def update(self, actor: Actor, public_id: str, data: dict) -> dict:
        with self.db.tx() as conn:
            group = self._owned(conn, actor, public_id)
            if "version" in data and int(data["version"]) != group["version"]:
                raise ConflictError("El grupo cambió mientras lo editaba. Recargue y vuelva a intentarlo.")
            merged = {**group, **{k: v for k, v in data.items() if k != "version"}}
            name, description = _texts(merged)
            policy = merged["join_policy"]
            if policy not in POLICIES:
                raise ValidationError("Opción no válida.", {"join_policy": "Elija ingreso automático o con aprobación."})
            visible = int(bool(merged["members_visible"]))
            conn.execute("UPDATE work_groups SET name = ?, description = ?, join_policy = ?, members_visible = ?,"
                         " updated_at = ?, version = version + 1 WHERE id = ?",
                         (name, description, policy, visible, iso(), group["id"]))
            changes = {k: {"antes": group[k], "despues": v} for k, v in
                       (("name", name), ("description", description), ("join_policy", policy), ("members_visible", visible))
                       if group[k] != v}
            if changes:
                _event(conn, group["id"], actor, None, "grupo_actualizado", changes)
                record(conn, actor, "grupo.actualizar", "work_group", public_id, changes)
            audience = self._audience(conn, group)
        self.hub.publish(audience, {"type": "grupo", "group": public_id})
        return self.get(actor, public_id)

    def set_open(self, actor: Actor, public_id: str, open_: bool) -> dict:
        with self.db.tx() as conn:
            group = self._owned(conn, actor, public_id)
            target = "activo" if open_ else "cerrado"
            if group["status"] == target:
                raise ConflictError("El grupo ya está " + ("activo." if open_ else "cerrado."))
            now = iso()
            conn.execute("UPDATE work_groups SET status = ?, closed_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                         (target, None if open_ else now, now, group["id"]))
            revoked = 0
            if not open_:   # cerrar revoca todos los enlaces vigentes
                revoked = conn.execute("UPDATE work_group_invitations SET revoked_at = ?, revoked_by = ? WHERE group_id = ?"
                                       " AND revoked_at IS NULL", (now, actor.id, group["id"])).rowcount
            _event(conn, group["id"], actor, None, "grupo_reabierto" if open_ else "grupo_cerrado",
                   {"enlaces_revocados": revoked} if revoked else None)
            record(conn, actor, "grupo.reabrir" if open_ else "grupo.cerrar", "work_group", public_id)
            audience = self._audience(conn, group)
        self.hub.publish(audience, {"type": "grupo", "group": public_id})
        return self.get(actor, public_id)

    # ------------------------------------------------------------------ invitaciones
    def create_invitation(self, actor: Actor, public_id: str, data: dict, request_base: str = "") -> dict:
        hours = int(data.get("expires_in_hours") or 72)
        max_uses = int(data.get("max_uses") or 10)
        if not 1 <= hours <= 24 * 30:
            raise ValidationError("Vigencia no válida.", {"expires_in_hours": "Entre 1 hora y 30 días."})
        if not 1 <= max_uses <= 500:
            raise ValidationError("Cupo no válido.", {"max_uses": "Entre 1 y 500 personas."})
        token = secrets.token_urlsafe(32)
        with self.db.tx() as conn:
            group = self._owned(conn, actor, public_id)
            if group["status"] != "activo":
                raise ConflictError("El grupo está cerrado: reábralo para invitar personas.")
            now = now_utc()
            cur = conn.execute("INSERT INTO work_group_invitations(group_id, token_hash, hint, created_by, created_at,"
                               " expires_at, max_uses) VALUES (?,?,?,?,?,?,?)",
                               (group["id"], token_hash(token), token[:4], actor.id, iso(now),
                                iso(now + timedelta(hours=hours)), max_uses))
            _event(conn, group["id"], actor, None, "invitacion_creada",
                   {"enlace": token[:4] + "…", "horas": hours, "cupo": max_uses})
            record(conn, actor, "grupo.invitacion_crear", "work_group", public_id,
                   {"invitacion": cur.lastrowid, "horas": hours, "cupo": max_uses})
            inv = dict(conn.execute("SELECT id, hint, created_at, expires_at, max_uses, uses, revoked_at"
                                    " FROM work_group_invitations WHERE id = ?", (cur.lastrowid,)).fetchone())
            inv["status"] = _invitation_status(inv, group, now)
        base = self.invite_base(request_base)
        # El token en claro solo se entrega en esta respuesta; después ya no se puede recuperar.
        return {"invitation": inv, "url": base + INVITE_PATH + token, "invite_base": self.invite_base_info(request_base)}

    def revoke_invitation(self, actor: Actor, public_id: str, invitation_id: int) -> dict:
        with self.db.tx() as conn:
            group = self._owned(conn, actor, public_id)
            inv = conn.execute("SELECT * FROM work_group_invitations WHERE id = ? AND group_id = ?",
                               (invitation_id, group["id"])).fetchone()
            if inv is None:
                raise NotFoundError("Invitación no encontrada.")
            if inv["revoked_at"]:
                raise ConflictError("El enlace ya estaba revocado.")
            conn.execute("UPDATE work_group_invitations SET revoked_at = ?, revoked_by = ? WHERE id = ?",
                         (iso(), actor.id, invitation_id))
            _event(conn, group["id"], actor, None, "invitacion_revocada", {"enlace": inv["hint"] + "…"})
            record(conn, actor, "grupo.invitacion_revocar", "work_group", public_id, {"invitacion": invitation_id})
        return self.get(actor, public_id)

    # ------------------------------------------------------------------ integrantes
    def member_action(self, actor: Actor, public_id: str, user_id: int, action: str) -> dict:
        if action not in MEMBER_ACTIONS:
            raise ValidationError("Acción no válida.")
        with self.db.tx() as conn:
            group = self._owned(conn, actor, public_id)
            member = conn.execute("SELECT * FROM work_group_members WHERE group_id = ? AND user_id = ?",
                                  (group["id"], user_id)).fetchone()
            if member is None:
                raise NotFoundError("Esa persona no pertenece al grupo.")
            expected = {"aprobar": ("pendiente",), "rechazar": ("pendiente",), "retirar": ("activo", "pendiente")}[action]
            if member["status"] not in expected:
                raise ConflictError("La solicitud ya fue atendida o la persona ya no está en el grupo. Recargue la página.")
            now = iso()
            if action == "aprobar":
                conn.execute("UPDATE work_group_members SET status = 'activo', joined_at = ?, updated_at = ? WHERE id = ?",
                             (now, now, member["id"]))
            else:
                conn.execute("UPDATE work_group_members SET status = ?, ended_at = ?, updated_at = ? WHERE id = ?",
                             ("rechazado" if action == "rechazar" else "eliminado", now, now, member["id"]))
            kind = {"aprobar": "solicitud_aprobada", "rechazar": "solicitud_rechazada", "retirar": "integrante_retirado"}[action]
            _event(conn, group["id"], actor, user_id, kind)
            record(conn, actor, "grupo." + kind, "work_group", public_id, {"usuario": user_id})
            audience = self._audience(conn, group) | {user_id}
        self.hub.publish(audience, {"type": "grupo", "group": public_id})
        return self.get(actor, public_id)

    def leave(self, actor: Actor, public_id: str) -> dict:
        with self.db.tx() as conn:
            group = self._group(conn, public_id)
            member = conn.execute("SELECT * FROM work_group_members WHERE group_id = ? AND user_id = ?"
                                  " AND status IN ('activo','pendiente')", (group["id"], actor.id)).fetchone()
            if member is None:
                raise NotFoundError("Grupo no encontrado.")
            now = iso()
            conn.execute("UPDATE work_group_members SET status = 'retirado', ended_at = ?, updated_at = ? WHERE id = ?",
                         (now, now, member["id"]))
            _event(conn, group["id"], actor, actor.id, "integrante_salio")
            record(conn, actor, "grupo.salir", "work_group", public_id)
            audience = self._audience(conn, group)
        self.hub.publish(audience | {actor.id}, {"type": "grupo", "group": public_id})
        return {"ok": True}

    # ------------------------------------------------------------------ enlace de invitación
    def preview(self, actor: Actor, token: str, client_key: str = "") -> dict:
        """Lo que ve quien abre el enlace (ya autenticado) antes de confirmar su ingreso."""
        keys = self._limit_keys(actor, client_key)
        self.limiter.check(*keys)
        with self.db.read() as conn:
            inv, group = self._valid_invitation(conn, token, keys)
            owner = conn.execute("SELECT full_name FROM users WHERE id = ?", (group["owner_id"],)).fetchone()
            mine = conn.execute("SELECT status FROM work_group_members WHERE group_id = ? AND user_id = ?",
                                (group["id"], actor.id)).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM work_group_members WHERE group_id = ? AND status = 'activo'",
                                 (group["id"],)).fetchone()[0]
        return {"group": {"public_id": group["public_id"], "name": group["name"], "description": group["description"],
                          "owner_name": owner[0] if owner else "", "member_count": count,
                          "join_policy": group["join_policy"]},
                "invitation": {"expires_at": inv["expires_at"], "remaining": inv["max_uses"] - inv["uses"]},
                "is_owner": group["owner_id"] == actor.id,
                "my_status": mine[0] if mine else None}

    def accept(self, actor: Actor, token: str, client_key: str = "") -> dict:
        keys = self._limit_keys(actor, client_key)
        self.limiter.check(*keys)
        with self.db.tx() as conn:
            inv, group = self._valid_invitation(conn, token, keys)
            if group["owner_id"] == actor.id:
                raise ConflictError("Usted es el administrador de este grupo; no necesita unirse.")
            member = conn.execute("SELECT * FROM work_group_members WHERE group_id = ? AND user_id = ?",
                                  (group["id"], actor.id)).fetchone()
            if member and member["status"] in ("activo", "pendiente"):
                # Sin duplicados y sin consumir cupo.
                return {"result": "ya_integrante" if member["status"] == "activo" else "pendiente",
                        "group": group["public_id"]}
            if member and member["status"] in ("eliminado", "rechazado") and inv["created_at"] <= member["updated_at"]:
                raise PermissionDenied("El administrador lo retiró de este grupo. Para volver pídale un enlace nuevo.")
            now = iso()
            status = "activo" if group["join_policy"] == "automatica" else "pendiente"
            joined = now if status == "activo" else None
            if member:
                conn.execute("UPDATE work_group_members SET status = ?, invitation_id = ?, requested_at = ?, joined_at = ?,"
                             " ended_at = NULL, updated_at = ? WHERE id = ?", (status, inv["id"], now, joined, now, member["id"]))
            else:
                conn.execute("INSERT INTO work_group_members(group_id, user_id, status, invitation_id, requested_at, joined_at,"
                             " updated_at) VALUES (?,?,?,?,?,?,?)", (group["id"], actor.id, status, inv["id"], now, joined, now))
            conn.execute("UPDATE work_group_invitations SET uses = uses + 1 WHERE id = ?", (inv["id"],))
            kind = "integrante_unido" if status == "activo" else "solicitud_ingreso"
            _event(conn, group["id"], actor, actor.id, kind, {"enlace": inv["hint"] + "…"})
            record(conn, actor, "grupo." + kind, "work_group", group["public_id"], {"invitacion": inv["id"]})
            audience = self._audience(conn, group)
        self.hub.publish(audience, {"type": "grupo", "group": group["public_id"], "change": kind})
        return {"result": "unido" if status == "activo" else "pendiente", "group": group["public_id"]}

    def _valid_invitation(self, conn: sqlite3.Connection, token: str, keys: list[str]) -> tuple[dict, dict]:
        token = (token or "").strip()
        inv = None
        if 20 <= len(token) <= 100:
            inv = conn.execute("SELECT * FROM work_group_invitations WHERE token_hash = ?", (token_hash(token),)).fetchone()
        if inv is None:
            self.limiter.hit(*keys)
            raise NotFoundError("El enlace de invitación no es válido. Revise que esté completo o pida uno nuevo al administrador.")
        group = dict(conn.execute("SELECT * FROM work_groups WHERE id = ?", (inv["group_id"],)).fetchone())
        status = _invitation_status(dict(inv), group, now_utc())
        messages = {
            "revocada": "El administrador revocó este enlace. Pídale uno nuevo.",
            "vencida": "Este enlace de invitación venció. Pida uno nuevo al administrador.",
            "completa": "Este enlace ya alcanzó el número máximo de personas. Pida uno nuevo al administrador.",
            "grupo_cerrado": "El grupo de trabajo fue cerrado por el administrador.",
        }
        if status != "vigente":
            raise InvitationGone(messages[status], {"invitacion": status})
        return dict(inv), group

    @staticmethod
    def _limit_keys(actor: Actor, client_key: str) -> list[str]:
        return [f"u:{actor.id}"] + ([f"ip:{client_key}"] if client_key else [])

    # ------------------------------------------------------------------ presencia
    def presence_changed(self, user_id: int, connected: bool) -> None:
        """Guarda la última conexión y avisa a los administradores de los grupos de esa persona."""
        now = iso()
        column = "last_connected_at" if connected else "last_disconnected_at"
        with self.db.tx() as conn:
            conn.execute(f"INSERT INTO user_presence(user_id, {column}) VALUES (?, ?)"  # noqa: S608 - columna fija
                         f" ON CONFLICT(user_id) DO UPDATE SET {column} = excluded.{column}", (user_id, now))
            rows = conn.execute("SELECT DISTINCT g.owner_id, g.public_id FROM work_group_members m"
                                " JOIN work_groups g ON g.id = m.group_id WHERE m.user_id = ? AND m.status = 'activo'",
                                (user_id,)).fetchall()
        for owner_id, gid in rows:
            self.hub.publish([owner_id], {"type": "presencia", "group": gid, "user": user_id})

    # ------------------------------------------------------------------ dirección pública
    def configured_base(self) -> str:
        if self.public_url:
            return self.public_url
        if self.settings is not None:
            return (self.settings.get("grupos").get("public_url") or "").rstrip("/")
        return ""

    def invite_base(self, request_base: str = "") -> str:
        return self.configured_base() or request_base.rstrip("/")

    def invite_base_info(self, request_base: str = "") -> dict:
        base = self.invite_base(request_base)
        source = "entorno" if self.public_url else ("configuracion" if self.configured_base() else "navegador")
        return {"url": base, "source": source, "reachable_from_internet": _looks_public(base) if base else None}

    # ------------------------------------------------------------------ auxiliares
    @staticmethod
    def _group(conn: sqlite3.Connection, public_id: str) -> dict:
        row = conn.execute("SELECT * FROM work_groups WHERE public_id = ?", ((public_id or "")[:20],)).fetchone()
        if row is None:
            raise NotFoundError("Grupo no encontrado.")
        return dict(row)

    def _owned(self, conn: sqlite3.Connection, actor: Actor, public_id: str) -> dict:
        actor.require("grupos.gestionar")
        group = self._group(conn, public_id)
        if group["owner_id"] != actor.id:
            raise NotFoundError("Grupo no encontrado.")   # un grupo ajeno no existe para quien no lo administra
        return group

    @staticmethod
    def _audience(conn: sqlite3.Connection, group: dict) -> set[int]:
        ids = {r[0] for r in conn.execute("SELECT user_id FROM work_group_members WHERE group_id = ?"
                                           " AND status IN ('activo','pendiente')", (group["id"],))}
        return ids | {group["owner_id"]}


def _invitation_status(inv: dict, group: dict, now) -> str:
    if inv.get("revoked_at"):
        return "revocada"
    if group["status"] != "activo":
        return "grupo_cerrado"
    if parse_iso(inv["expires_at"]) <= now:
        return "vencida"
    if inv["uses"] >= inv["max_uses"]:
        return "completa"
    return "vigente"


def _texts(data: dict) -> tuple[str, str]:
    name = " ".join((data.get("name") or "").split())
    description = (data.get("description") or "").strip()
    if not name:
        raise ValidationError("Faltan datos.", {"name": "Escriba el nombre del grupo."})
    if len(name) > 80 or len(description) > 500:
        raise ValidationError("Texto demasiado largo.", {"name": "Nombre: máximo 80 caracteres; descripción: 500."})
    return name, description


def _new_public_id(conn: sqlite3.Connection) -> str:
    while True:
        candidate = "G-" + secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM work_groups WHERE public_id = ?", (candidate,)).fetchone():
            return candidate


def _event(conn: sqlite3.Connection, group_id: int, actor: Actor | None, subject_id: int | None, kind: str,
           details: dict | None = None) -> None:
    conn.execute("INSERT INTO work_group_events(group_id, created_at, actor_id, subject_id, type, details) VALUES (?,?,?,?,?,?)",
                 (group_id, iso(), actor.id if actor else None, subject_id, kind,
                  json.dumps(details, ensure_ascii=False, default=str) if details else None))


def _looks_public(url: str) -> bool:
    """False si la dirección solo funciona en este equipo o en la red local."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith((".local", ".lan", ".home")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (ip.is_loopback or ip.is_private or ip.is_link_local)

