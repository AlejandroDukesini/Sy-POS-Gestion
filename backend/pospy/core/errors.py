"""Errores de dominio. La capa HTTP los traduce a códigos de estado; nunca exponen detalles internos."""
from __future__ import annotations


class DomainError(Exception):
    status = 422
    title = "No se pudo completar la operación"

    def __init__(self, detail: str, fields: dict[str, str] | None = None):
        super().__init__(detail)
        self.detail = detail
        self.fields = fields or {}


class ValidationError(DomainError):
    title = "Revise los datos"


class NotFoundError(DomainError):
    status = 404
    title = "No encontrado"


class ConflictError(DomainError):
    status = 409
    title = "Conflicto"


class AuthError(DomainError):
    status = 401
    title = "Sesión no válida"


class PermissionDenied(DomainError):
    status = 403
    title = "Sin permiso"


class ExternalServiceError(DomainError):
    status = 502
    title = "Servicio externo no disponible"


def require_fields(data: dict, labels: dict[str, str]) -> None:
    missing = {k: f"{label} es obligatorio." for k, label in labels.items() if data.get(k) in (None, "")}
    if missing:
        raise ValidationError("Faltan datos obligatorios.", missing)
