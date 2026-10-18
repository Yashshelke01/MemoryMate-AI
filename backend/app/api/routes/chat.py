from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ConversationDep, CurrentUserDep, SettingsDep, SQLiteStoreDep
from app.errors import AppError
from app.models.api import ChatInput, ChatRequest, ChatResponse
from app.utils import run_blocking

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatInput,
    settings: SettingsDep,
    service: ConversationDep,
    user: CurrentUserDep,
    store: SQLiteStoreDep,
) -> ChatResponse:
    user_id = user["user_id"]
    if body.conversation_id and not store.conversation_exists(user_id, body.conversation_id):
        raise AppError(404, "conversation_not_found", "Conversation not found.")
    authenticated_body = ChatRequest(
        user_id=user_id, message=body.message, conversation_id=body.conversation_id
    )
    return await run_blocking(
        service.process_chat,
        authenticated_body,
        timeout=settings.chat_timeout_seconds,
        on_timeout=AppError(
            503,
            "timeout",
            "The request timed out. Memories from this message may not have been saved.",
        ),
    )
