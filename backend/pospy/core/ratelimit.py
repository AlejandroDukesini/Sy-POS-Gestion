"""Límite de intentos en memoria (ventana deslizante). Suficiente para un servidor de un solo proceso."""
from __future__ import annotations

import threading
import time
from collections import deque

from .errors import DomainError


class TooManyRequests(DomainError):
    status = 429
    title = "Demasiados intentos"


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        return hits

    def check(self, *keys: str) -> None:
        """Lanza TooManyRequests si alguna clave agotó sus intentos."""
        now = time.monotonic()
        with self._lock:
            for key in keys:
                hits = self._recent(key, now)
                if len(hits) >= self.limit:
                    wait = int(self.window_s - (now - hits[0])) + 1
                    raise TooManyRequests(f"Demasiados intentos con enlaces no válidos. Espere {max(1, wait // 60)} minuto(s)"
                                          " e intente de nuevo.")

    def hit(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._recent(key, now).append(now)
            if len(self._hits) > 10_000:   # evita crecer sin límite con claves viejas
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window_s]:
                    del self._hits[k]
