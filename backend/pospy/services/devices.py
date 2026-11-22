"""Equipos autorizados: restricción de acceso por dispositivo.

Objetivo: que no baste con copiar la dirección del POS y usar las credenciales desde otro computador.

Cómo funciona (prueba de posesión de clave, no huella del navegador):
1. Cada equipo genera en el navegador un par de claves ECDSA P-256 con WebCrypto. La clave PRIVADA se crea
   como NO exportable y se guarda en IndexedDB del navegador: la página no puede leerla ni enviarla.
2. El servidor solo conoce la clave PÚBLICA. Para registrarse o iniciar sesión, el equipo firma un desafío de un
   solo uso (vence en 2 minutos) emitido por el servidor: así se demuestra que tiene la clave sin revelarla.
3. Un administrador autoriza (o rechaza) cada equipo. Con la restricción activa, el inicio de sesión desde un
   equipo no autorizado se rechaza aunque la contraseña sea correcta, y cada petición comprueba que la sesión
   fue abierta por un equipo que SIGUE autorizado: revocarlo cierra de inmediato sus sesiones.
4. El equipo servidor (peticiones locales, sin proxy) queda exento: es donde está la base de datos y evita que
   el negocio quede bloqueado. La aplicación de escritorio funciona allí.

No se usa IP, User-Agent ni huellas del navegador para autenticar (solo como información). Limitaciones:
un navegador no identifica de forma infalible un equipo físico (ver docs/developer/seguridad.md).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import AuthError, NotFoundError, ValidationError

KEY = "dispositivos"
CHALLENGE_TTL = 120
STATUSES = ("pendiente", "autorizado", "revocado", "rechazado")


class DeviceError(AuthError):
    """Inicio de sesión rechazado por el equipo. code: sin_prueba | no_registrado | pendiente | revocado | rechazado."""
    title = "Equipo no autorizado"
    status = 403

    def __init__(self, detail: str, code: str):
        super().__init__(detail, {"device": code})
        self.code = code


def thumbprint(spki_der: bytes) -> str:
    return hashlib.sha256(spki_der).hexdigest()


class DeviceService:
    def __init__(self, db):
        self.db = db
        self._challenges: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ política
    def enforced(self, conn: sqlite3.Connection | None = None) -> bool:
        def read(c):
            row = c.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
            return bool(json.loads(row[0]).get("enforced")) if row else False
        if conn is not None:
            return read(conn)
        with self.db.read() as c:
            return read(c)

    # ------------------------------------------------------------------ desafíos de un solo uso
    def challenge(self) -> dict:
        nonce = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            for k in [k for k, exp in self._challenges.items() if exp < now]:
                del self._challenges[k]
            if len(self._challenges) > 5000:
                raise ValidationError("Demasiadas solicitudes de verificación. Intente en un momento.")
            self._challenges[nonce] = now + CHALLENGE_TTL
        return {"nonce": nonce, "expires_in": CHALLENGE_TTL}

    def _consume(self, nonce: str) -> bool:
        with self._lock:
            exp = self._challenges.pop(nonce or "", None)
        return exp is not None and exp >= time.monotonic()

    def verify_proof(self, proof: dict | None) -> tuple[bytes, str]:
        """Comprueba la firma del desafío con la clave pública enviada. Devuelve (spki, huella)."""
        if not isinstance(proof, dict):
            raise DeviceError("Este equipo no envió su identificación. Use la dirección segura (https) del POS y un "
                              "navegador actualizado.", "sin_prueba")
        try:
            spki = base64.b64decode(str(proof.get("public_key", "")), validate=True)
            sig = base64.b64decode(str(proof.get("signature", "")), validate=True)
            key = load_der_public_key(spki)
        except (ValueError, TypeError):
            raise DeviceError("La identificación del equipo no es válida.", "sin_prueba") from None
        if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1" or len(sig) != 64:
            raise DeviceError("La identificación del equipo no es válida.", "sin_prueba")
        nonce = str(proof.get("nonce", ""))
        if not self._consume(nonce):
            raise DeviceError("La verificación del equipo venció. Intente de nuevo.", "sin_prueba")
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        try:
            key.verify(der, nonce.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise DeviceError("La firma del equipo no es válida.", "sin_prueba") from None
        return spki, thumbprint(spki)

    # ------------------------------------------------------------------ registro y verificación
    def request(self, conn: sqlite3.Connection, user, spki: bytes, thumb: str, name: str, user_agent: str,
                auto_authorize: Actor | None = None) -> dict:
        """Registra el equipo como «pendiente» (o lo autoriza si lo pide un administrador desde ese equipo)."""
        row = conn.execute("SELECT * FROM devices WHERE key_thumbprint = ?", (thumb,)).fetchone()
        if row:
            if auto_authorize and row["status"] in ("pendiente", "rechazado", "revocado"):
                self._decide_conn(conn, auto_authorize, row, "autorizado", "autorizado por el administrador desde este equipo")
                row = conn.execute("SELECT * FROM devices WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)
        clean = " ".join((name or "").split())[:60] or "Equipo sin nombre"
        now = iso()
        status = "autorizado" if auto_authorize else "pendiente"
        cur = conn.execute(
            "INSERT INTO devices(public_id, name, public_key, key_thumbprint, status, user_agent, requested_by, decided_by,"
            " created_at, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("D-" + secrets.token_hex(4).upper(), clean, base64.b64encode(spki).decode(), thumb, status, (user_agent or "")[:200],
             user["id"], auto_authorize.id if auto_authorize else None, now, now if auto_authorize else None))
        record(conn, Actor(user["id"], user["username"], user["role"]), "dispositivo.solicitado", "device", cur.lastrowid,
               {"equipo": clean, "estado": status})
        if auto_authorize:
            record(conn, auto_authorize, "dispositivo.autorizado", "device", cur.lastrowid, {"equipo": clean, "nota": "desde el mismo equipo"})
        return dict(conn.execute("SELECT * FROM devices WHERE id = ?", (cur.lastrowid,)).fetchone())

    @staticmethod
    def require_authorized(device: dict | None) -> None:
        if device is None:
            raise DeviceError("Este equipo no está autorizado para usar el POS. Solicite la autorización.", "no_registrado")
        messages = {"pendiente": "Este equipo está pendiente de autorización. Pida a un administrador que lo apruebe.",
                    "revocado": "La autorización de este equipo fue revocada. Consulte con un administrador.",
                    "rechazado": "La solicitud de este equipo fue rechazada. Consulte con un administrador."}
        if device["status"] != "autorizado":
            raise DeviceError(messages[device["status"]], device["status"])

    def by_thumbprint(self, conn: sqlite3.Connection, thumb: str) -> dict | None:
        row = conn.execute("SELECT * FROM devices WHERE key_thumbprint = ?", (thumb,)).fetchone()
        return dict(row) if row else None

    def touch(self, conn: sqlite3.Connection, device_id: int, user_id: int) -> None:
        conn.execute("UPDATE devices SET last_seen_at = ?, last_user_id = ? WHERE id = ?", (iso(), user_id, device_id))

    # ------------------------------------------------------------------ administración
    def list(self, actor: Actor) -> dict:
        actor.require("gestion.configuracion")
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT d.id, d.public_id, d.name, d.status, d.user_agent, d.created_at, d.decided_at, d.last_seen_at, d.note,"
                " substr(d.key_thumbprint, 1, 16) AS fingerprint,"
                " r.full_name AS requested_by_name, k.full_name AS decided_by_name, l.full_name AS last_user_name,"
                " (SELECT COUNT(*) FROM sessions s WHERE s.device_id = d.id AND s.revoked_at IS NULL AND s.expires_at > ?) AS active_sessions"
                " FROM devices d LEFT JOIN users r ON r.id = d.requested_by LEFT JOIN users k ON k.id = d.decided_by"
                " LEFT JOIN users l ON l.id = d.last_user_id ORDER BY d.status = 'pendiente' DESC, d.created_at DESC", (iso(),)).fetchall()
            history = conn.execute(
                "SELECT a.created_at, a.action, a.entity_id, a.details, u.full_name FROM audit_log a LEFT JOIN users u ON u.id = a.user_id"
                " WHERE a.action LIKE 'dispositivo.%' OR a.action LIKE 'seguridad.dispositivos%' OR a.action = 'sesion.equipo_rechazado'"
                " ORDER BY a.id DESC LIMIT 100").fetchall()
            return {"enforced": self.enforced(conn), "devices": [dict(r) for r in rows], "history": [dict(h) for h in history]}

    def decide(self, actor: Actor, device_id: int, status: str, note: str = "") -> dict:
        actor.require("gestion.configuracion")
        if status not in ("autorizado", "revocado", "rechazado"):
            raise ValidationError("Estado no válido.", {"status": "Autorizado, revocado o rechazado."})
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not row:
                raise NotFoundError("Equipo no encontrado.")
            self._decide_conn(conn, actor, row, status, note)
        return self.list(actor)

    def _decide_conn(self, conn: sqlite3.Connection, actor: Actor, row, status: str, note: str) -> None:
        conn.execute("UPDATE devices SET status = ?, decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                     (status, actor.id, iso(), (note or "")[:200], row["id"]))
        closed = 0
        if status != "autorizado":                    # las sesiones abiertas con ese equipo dejan de valer YA
            closed = conn.execute("UPDATE sessions SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                                  (iso(), row["id"])).rowcount
        record(conn, actor, f"dispositivo.{status}", "device", row["id"],
               {"equipo": row["name"], "antes": row["status"], "sesiones_cerradas": closed, "nota": (note or "")[:200]})

    def rename(self, actor: Actor, device_id: int, name: str) -> dict:
        actor.require("gestion.configuracion")
        clean = " ".join((name or "").split())[:60]
        if not clean:
            raise ValidationError("Escriba el nombre del equipo.", {"name": "Nombre obligatorio."})
        with self.db.tx() as conn:
            if not conn.execute("UPDATE devices SET name = ? WHERE id = ?", (clean, device_id)).rowcount:
                raise NotFoundError("Equipo no encontrado.")
            record(conn, actor, "dispositivo.renombrado", "device", device_id, {"nombre": clean})
        return self.list(actor)

    def set_enforced(self, actor: Actor, enabled: bool, current_device_id: int | None, local: bool) -> dict:
        """Activa o desactiva la restricción. Para no quedar fuera, quien la activa debe estar en el equipo servidor o
        en una sesión abierta con un equipo autorizado."""
        actor.require("gestion.configuracion")
        with self.db.tx() as conn:
            if enabled and not local:
                ok = current_device_id is not None and conn.execute(
                    "SELECT 1 FROM devices WHERE id = ? AND status = 'autorizado'", (current_device_id,)).fetchone()
                if not ok:
                    raise ValidationError("Primero registre y autorice ESTE equipo (botón «Autorizar este equipo»); si no, "
                                          "quedaría sin acceso al activar la restricción.")
            conn.execute("INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE"
                         " SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                         (KEY, json.dumps({"enforced": bool(enabled)}), iso(), actor.id))
            record(conn, actor, "seguridad.dispositivos_" + ("activada" if enabled else "desactivada"), "settings", KEY)
        return self.list(actor)
