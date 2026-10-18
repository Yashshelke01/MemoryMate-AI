from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, MemoryAdminDep, MemoryIdPath, SettingsDep, UserIdPath
from app.errors import AppError
from app.models.api import (
    MemoryDeleteInput,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryPatchInput,
    MemoryPatchRequest,
    MemoryPatchResponse,
)
from app.utils import run_blocking

router = APIRouter()


def _timeout(settings) -> AppError:
    return AppError(503, "timeout", "The request timed out.")


@router.get("/memories/{user_id}", response_model=MemoryListResponse)
async def list_memories(
    user_id: UserIdPath,
    settings: SettingsDep,
    service: MemoryAdminDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> MemoryListResponse:
    if user_id != user["user_id"]:
        raise AppError(404, "memory_not_found", "Memory collection not found.")
    user_id = user["user_id"]
    return await run_blocking(
        service.list_memories,
        user_id,
        limit,
        offset,
        timeout=settings.request_timeout_seconds,
        on_timeout=_timeout(settings),
    )


@router.patch("/memories/{memory_id}", response_model=MemoryPatchResponse)
async def patch_memory(
    memory_id: MemoryIdPath,
    body: MemoryPatchInput,
    settings: SettingsDep,
    service: MemoryAdminDep,
    user: CurrentUserDep,
) -> MemoryPatchResponse:
    authenticated_body = MemoryPatchRequest(user_id=user["user_id"], **body.model_dump())
    return await run_blocking(
        service.update_memory,
        memory_id,
        authenticated_body,
        timeout=settings.request_timeout_seconds,
        on_timeout=_timeout(settings),
    )


@router.delete("/memories/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: MemoryIdPath,
    _body: MemoryDeleteInput,
    settings: SettingsDep,
    service: MemoryAdminDep,
    user: CurrentUserDep,
) -> MemoryDeleteResponse:
    await run_blocking(
        service.delete_memory,
        user["user_id"],
        memory_id,
        timeout=settings.request_timeout_seconds,
        on_timeout=_timeout(settings),
    )
    return MemoryDeleteResponse(deleted=True, memory_id=memory_id)
