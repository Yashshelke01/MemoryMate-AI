"""FastAPI application factory.

Run from the backend/ directory:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import auth, chat, conversations, graph, health, memories
from app.config import Settings, get_settings
from app.container import ServiceRegistry
from app.db.sqlite_store import SQLiteStore
from app.errors import AppError
from app.services.conversation_service import ConversationService
from app.services.memory_admin_service import MemoryAdminService

logger = logging.getLogger(__name__)


def _error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    err: dict[str, Any] = {"code": code, "message": message}
    if details:
        err["details"] = details
    return JSONResponse(status_code=status, content={"error": err})


def create_app(
    settings: Settings | None = None,
    overrides: dict[str, Any] | None = None,
) -> FastAPI:
    """``overrides`` injects components by name (tests / alternative wiring)."""
    settings = settings or get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    app = FastAPI(title=settings.app_name, version="0.1.0")
    registry = ServiceRegistry(settings, overrides)
    sqlite_store = SQLiteStore(settings.sqlite_db_path)
    app.state.settings = settings
    app.state.registry = registry
    app.state.sqlite_store = sqlite_store
    app.state.conversation_service = ConversationService(settings, registry, sqlite_store)
    app.state.memory_admin_service = MemoryAdminService(settings, registry)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.on_event("shutdown")
    def _close_sqlite_store() -> None:
        sqlite_store.close()

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only; never echo submitted values.
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "Invalid value.")}
            for e in exc.errors()
        ]
        return _error_response(422, "validation_error", "Request validation failed.", {"errors": details})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = "Resource not found." if exc.status_code == 404 else "Request could not be processed."
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s", type(exc).__name__, exc_info=True)
        return _error_response(500, "internal_error", "An unexpected error occurred.")

    for module in (health, auth, chat, conversations, memories, graph):
        app.include_router(module.router)
    return app


app = create_app()
