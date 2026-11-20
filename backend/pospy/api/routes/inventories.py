"""Inventarios: lista de los que la persona puede usar (con resumen real) y administración del dueño."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from ...context import AppContext
from ...core.actor import Actor
from ..deps import actor, ctx
from ..models import Strict
from ..serialize import out

router = APIRouter(tags=["inventarios"])


class MemberPerms(Strict):
    user_id: int
    permissions: list[str] | None = None


class InventoryIn(Strict):
    name: str = Field(max_length=80)
    description: str = Field(default="", max_length=300)
    group: str = Field(max_length=20)
    settings: dict[str, Any] | None = None
    members: list[MemberPerms] | None = None


class InventoryUpdate(Strict):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    group: str | None = Field(default=None, max_length=20)
    status: Literal["activo", "inactivo", "archivado"] | None = None
    settings: dict[str, Any] | None = None
    members: list[MemberPerms] | None = None
    version: int | None = None


@router.get("/inventories")
def list_inventories(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventories.list(current))


@router.get("/inventories/permissions")
def permission_catalog(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventories.catalog()


@router.get("/inventories/groups")
def my_groups(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventories.groups(current)


@router.post("/inventories")
def create(body: InventoryIn, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = body.model_dump()
    data["members"] = [m.model_dump() for m in body.members or []]
    return out(app.inventories.create(current, data))


@router.get("/inventories/{public_id}")
def get(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventories.get(current, public_id))


@router.put("/inventories/{public_id}")
def update(public_id: str, body: InventoryUpdate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = body.model_dump(exclude_unset=True)
    if body.members is not None:
        data["members"] = [m.model_dump() for m in body.members]
    return out(app.inventories.update(current, public_id, data))


@router.delete("/inventories/{public_id}")
def delete(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventories.delete(current, public_id)
