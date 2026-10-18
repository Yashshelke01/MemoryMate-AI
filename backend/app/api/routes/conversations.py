from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SQLiteStoreDep
from app.errors import AppError
from app.models.api import ConversationListResponse, ConversationResponse

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
def list_conversations(user: CurrentUserDep, store: SQLiteStoreDep) -> ConversationListResponse:
    return ConversationListResponse(items=store.list_conversations(user["user_id"]))


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str, user: CurrentUserDep, store: SQLiteStoreDep
) -> ConversationResponse:
    conversation = store.get_conversation(user["user_id"], conversation_id)
    if conversation is None:
        raise AppError(404, "conversation_not_found", "Conversation not found.")
    return ConversationResponse(**conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, user: CurrentUserDep, store: SQLiteStoreDep
) -> None:
    if not store.delete_conversation(user["user_id"], conversation_id):
        raise AppError(404, "conversation_not_found", "Conversation not found.")
