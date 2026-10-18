"""FastAPI dependencies: settings, services, and identity resolution."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, Path, Request

from app.config import Settings
from app.container import ServiceRegistry
from app.errors import AppError
from app.models.api import MEMORY_ID_PATTERN, USER_ID_PATTERN
from app.services.conversation_service import ConversationService
from app.services.memory_admin_service import MemoryAdminService
from app.db.sqlite_store import SQLiteStore
from app.services.auth_service import session_token_digest

UserIdPath = Annotated[str, Path(pattern=USER_ID_PATTERN)]
MemoryIdPath = Annotated[str, Path(pattern=MEMORY_ID_PATTERN)]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ServiceRegistry:
    return request.app.state.registry


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_memory_admin_service(request: Request) -> MemoryAdminService:
    return request.app.state.memory_admin_service


def get_sqlite_store(request: Request) -> SQLiteStore:
    return request.app.state.sqlite_store


def get_current_user(request: Request) -> dict[str, str]:
    session_token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not session_token:
        raise AppError(401, "authentication_required", "Please sign in to continue.")
    store: SQLiteStore = request.app.state.sqlite_store
    user = store.session_user(session_token_digest(session_token), int(time.time()))
    if not user:
        raise AppError(401, "authentication_required", "Please sign in to continue.")
    return user


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RegistryDep = Annotated[ServiceRegistry, Depends(get_registry)]
ConversationDep = Annotated[ConversationService, Depends(get_conversation_service)]
MemoryAdminDep = Annotated[MemoryAdminService, Depends(get_memory_admin_service)]
SQLiteStoreDep = Annotated[SQLiteStore, Depends(get_sqlite_store)]
CurrentUserDep = Annotated[dict[str, str], Depends(get_current_user)]
