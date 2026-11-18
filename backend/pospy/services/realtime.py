"""Canal de tiempo real (Server-Sent Events) y presencia de usuarios.

Por qué SSE y no WebSocket: las notificaciones van solo del servidor al navegador (las acciones
viajan por la API REST, con sus permisos y su CSRF), el navegador reconecta solo, atraviesa proxies
y túneles HTTPS sin configuración especial, y no exige dependencias nuevas (uvicorn se distribuye
sin bibliotecas de WebSocket).

Los eventos solo AVISAN que algo cambió ({"type": "grupo", "group": "G…"}); la interfaz vuelve a
pedir los datos a la API, que es la única fuente autorizada. Así un evento nunca entrega
información a quien no tenga permiso de leerla.

El servidor es de un solo proceso (SQLite), por eso el reparto de eventos vive en memoria. La
presencia en vivo también: tras reiniciar el servidor, el estado vuelve a «desconocido» hasta que
cada persona reconecte (la última conexión conocida queda en la tabla user_presence).
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

# Tras perder la conexión, durante este tiempo se considera que la persona está reconectando
# (el navegador reintenta cada pocos segundos; un móvil puede tardar más al volver de segundo plano).
RECONNECT_GRACE_S = 60.0
QUEUE_SIZE = 200
# Un proxy o túnel puede seguir aceptando datos después de que el cliente se fue (conexión medio
# abierta): el servidor nunca vería el corte. Por eso el navegador envía un ping cada pocos segundos
# mientras tiene el canal abierto; un canal sin pings durante este tiempo se da por perdido.
STALE_AFTER_S = 30.0


@dataclass(eq=False)
class Subscriber:
    user_id: int
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    overflow: bool = False
    opened_at: float = field(default_factory=time.monotonic)


class RealtimeHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[int, set[Subscriber]] = {}
        self._dropped_at: dict[int, float] = {}   # monotonic: momento en que se cerró su última conexión
        self._pinged_at: dict[int, float] = {}    # monotonic: último ping del navegador de esa persona

    # ------------------------------------------------------------------ suscripción
    def subscribe(self, user_id: int, loop: asyncio.AbstractEventLoop) -> tuple[Subscriber, bool]:
        """Registra una conexión. Devuelve (suscriptor, era_la_primera_conexión_de_la_persona)."""
        sub = Subscriber(user_id, loop)
        with self._lock:
            subs = self._subs.setdefault(user_id, set())
            first = not subs
            subs.add(sub)
            self._dropped_at.pop(user_id, None)
        return sub, first

    def unsubscribe(self, sub: Subscriber) -> bool:
        """Quita una conexión. Devuelve True si la persona quedó sin conexiones."""
        with self._lock:
            subs = self._subs.get(sub.user_id)
            if not subs or sub not in subs:
                return False
            subs.discard(sub)
            if subs:
                return False
            del self._subs[sub.user_id]
            self._dropped_at[sub.user_id] = time.monotonic()
            return True

    def ping(self, user_id: int) -> None:
        """El navegador confirma que sigue ahí (lo envía mientras mantiene el canal abierto)."""
        with self._lock:
            self._pinged_at[user_id] = time.monotonic()

    def is_stale(self, sub: Subscriber, after_s: float = STALE_AFTER_S) -> bool:
        """True si el canal lleva demasiado sin pings. Solo aplica a clientes que envían ping."""
        with self._lock:
            pinged = self._pinged_at.get(sub.user_id)
        if pinged is None:
            return False
        return time.monotonic() - max(pinged, sub.opened_at) > after_s

    # ------------------------------------------------------------------ publicación
    def publish(self, user_ids, event: dict) -> int:
        """Entrega un evento a todas las conexiones de esas personas. Seguro desde cualquier hilo."""
        with self._lock:
            targets = [s for uid in set(user_ids) for s in self._subs.get(uid, ())]
        for sub in targets:
            try:
                sub.loop.call_soon_threadsafe(_offer, sub, event)
            except RuntimeError:     # el bucle de esa conexión ya terminó
                pass
        return len(targets)

    # ------------------------------------------------------------------ presencia
    def status(self, user_id: int, known_before: bool = False) -> str:
        """conectado | reconectando | desconectado | desconocido."""
        with self._lock:
            if self._subs.get(user_id):
                return "conectado"
            dropped = self._dropped_at.get(user_id)
        if dropped is not None:
            return "reconectando" if time.monotonic() - dropped < RECONNECT_GRACE_S else "desconectado"
        return "desconectado" if known_before else "desconocido"

    def connected_count(self) -> int:
        with self._lock:
            return sum(len(s) for s in self._subs.values())


def _offer(sub: Subscriber, event: dict) -> None:
    """Corre en el bucle de la conexión. Si la cola se llena, el cliente recibirá «resync» y recargará todo."""
    try:
        sub.queue.put_nowait(event)
    except asyncio.QueueFull:
        sub.overflow = True
