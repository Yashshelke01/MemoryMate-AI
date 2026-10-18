from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.deps import RegistryDep, SettingsDep
from app.errors import AppError
from app.models.api import HealthResponse
from app.utils import run_blocking

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep, registry: RegistryDep) -> HealthResponse:
    # FalkorDB: real lightweight read via the repository.
    falkordb = "unavailable"
    repo = registry.get_optional("repository")
    if repo is not None:
        try:
            ok = await run_blocking(
                repo.health,
                timeout=settings.health_timeout_seconds,
                on_timeout=AppError(503, "timeout", "Health check timed out."),
            )
            falkordb = "ok" if ok else "unavailable"
        except Exception as exc:  # noqa: BLE001
            logger.warning("FalkorDB health check failed: %s", type(exc).__name__)

    # LLM: configuration only; never a billable generation call.
    llm = "not_configured"
    llm_check = registry.get_optional("llm_is_configured")
    try:
        configured = bool(llm_check()) if llm_check is not None else settings.llm_configured
    except Exception:  # noqa: BLE001
        configured = False
    if configured:
        llm = "configured"

    status = "ok" if falkordb == "ok" and llm == "configured" else "degraded"
    return HealthResponse(status=status, dependencies={"falkordb": falkordb, "llm": llm})
