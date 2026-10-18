from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, MemoryAdminDep, SettingsDep, UserIdPath
from app.errors import AppError
from app.models.api import GraphResponse
from app.utils import run_blocking

router = APIRouter()


@router.get("/graph/{user_id}", response_model=GraphResponse)
async def get_graph(
    user_id: UserIdPath,
    settings: SettingsDep,
    service: MemoryAdminDep,
    user: CurrentUserDep,
) -> GraphResponse:
    if user_id != user["user_id"]:
        raise AppError(404, "graph_not_found", "Graph not found.")
    user_id = user["user_id"]
    return await run_blocking(
        service.graph,
        user_id,
        timeout=settings.request_timeout_seconds,
        on_timeout=AppError(503, "timeout", "The request timed out."),
    )
