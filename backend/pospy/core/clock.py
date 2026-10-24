"""Fechas: instantes en UTC ISO-8601 ('2026-10-24T15:04:05Z'); fechas de negocio en la zona de la empresa."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Bogota"


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def local_today(tz: str = DEFAULT_TZ) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def local_date_of(instant: str, tz: str = DEFAULT_TZ) -> date:
    return parse_iso(instant).astimezone(ZoneInfo(tz)).date()


def parse_date(text: str | None, label: str = "Fecha") -> date:
    from .errors import ValidationError
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        raise ValidationError(f"{label}: use el formato AAAA-MM-DD.") from None
