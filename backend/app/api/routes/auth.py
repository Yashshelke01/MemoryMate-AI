from __future__ import annotations

import time

import anyio
from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUserDep, SettingsDep, SQLiteStoreDep
from app.errors import AppError
from app.models.api import LoginRequest, SignupRequest, UserResponse
from app.services.auth_service import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    new_session_token,
    session_token_digest,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_session(response: Response, settings, store, user_id: str) -> None:
    token = new_session_token()
    store.create_session(
        session_token_digest(token), user_id, int(time.time()) + settings.session_ttl_seconds
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/signup", response_model=UserResponse, status_code=201)
async def signup(
    body: SignupRequest, response: Response, settings: SettingsDep, store: SQLiteStoreDep
) -> UserResponse:
    password_hash = await anyio.to_thread.run_sync(hash_password, body.password)
    user = store.create_user(
        body.email,
        password_hash,
        full_name=body.full_name,
        mobile_number=body.mobile_number,
        age=body.age,
    )
    if user is None:
        raise AppError(409, "account_exists", "An account with this email already exists.")
    _set_session(response, settings, store, user["user_id"])
    return UserResponse(**user)


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest, response: Response, settings: SettingsDep, store: SQLiteStoreDep
) -> UserResponse:
    user = store.user_by_email(body.email)
    candidate_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    password_ok = await anyio.to_thread.run_sync(verify_password, body.password, candidate_hash)
    if not user or not password_ok:
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
    _set_session(response, settings, store, user["user_id"])
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        full_name=user.get("full_name", ""),
        mobile_number=user.get("mobile_number"),
        age=user.get("age"),
        created_at=user["created_at"],
    )


@router.post("/logout")
def logout(request: Request, response: Response, settings: SettingsDep, store: SQLiteStoreDep) -> dict[str, bool]:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        store.delete_session(session_token_digest(token))
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"logged_out": True}


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse(**user)
