"""Identidad de quien ejecuta una operación. Los servicios la reciben explícitamente y validan permisos."""
from __future__ import annotations

from dataclasses import dataclass, field

from .errors import PermissionDenied
from .permissions import ALL


@dataclass(frozen=True)
class Actor:
    id: int | None
    username: str
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    full_name: str = ""
    inventory_id: int | None = None   # inventario de la petición (los permisos de inventario son los de ese inventario)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if p not in self.permissions]
        if missing:
            raise PermissionDenied("No tiene permiso para esta operación. Si la necesita para su trabajo, solicítela a un "
                                   "administrador.", {"permiso": ", ".join(missing)})


SYSTEM = Actor(id=None, username="sistema", role="admin",
               permissions=ALL,
               full_name="Proceso automático")
