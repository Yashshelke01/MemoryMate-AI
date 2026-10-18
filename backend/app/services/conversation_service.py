"""Chat orchestration (PROJECT_CONTRACT.md sections 1, 5).

validate -> extract -> persist (match/correct) -> retrieve -> ground -> answer.
Every step that fails surfaces a 503; nothing is reported as saved or
graph-grounded unless it actually happened.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict, deque
from typing import Any, Callable

from pydantic import ValidationError

from app.config import Settings
from app.container import ServiceRegistry
from app.errors import AppError, component_error
from app.models.api import ChatRequest, ChatResponse, MemoryOperations, MemoryUsed
from app.models.contracts import (
    GroundingContext,
    MemoryOperationSummary,
    ProposedFact,
    RetrievedMemory,
    SourceIds,
)
from app.utils import new_id

logger = logging.getLogger(__name__)

_MAX_TURN_CHARS = 2000
_STANDALONE_QUESTION_START = re.compile(
    r"^(?:what|who|where|when|why|how|which|can you|could you|would you|"
    r"will you|do you|does|did|is|are|have you|has)\b",
    re.IGNORECASE,
)
_MEMORY_WRITE_INTENT = re.compile(
    r"\b(?:remember|save|store|update|correct|change|delete|forget|note)\b",
    re.IGNORECASE,
)
_ANSWER_REQUEST_INTENT = re.compile(
    r"\b(?:help|suggest|recommend|explain|tell me|give me|plan|what|how|why|"
    r"when|where|which|who|can you|could you|should i|advise)\b",
    re.IGNORECASE,
)


def _is_standalone_question(message: str) -> bool:
    """Avoid a redundant extraction LLM call for an obvious question-only turn.

    Statements, mixed turns, and explicit memory-edit requests still go
    through extraction. Keeping this gate narrow avoids dropping facts that
    happen to be phrased as questions.
    """
    text = message.strip()
    return (
        text.endswith("?")
        and text.count("?") == 1
        and not _MEMORY_WRITE_INTENT.search(text)
        and bool(_STANDALONE_QUESTION_START.match(text))
    )


def _is_memory_only_statement(message: str, facts: list[ProposedFact]) -> bool:
    """Recognize fact-only statements that need no generated reply.

    After extraction and a successful database write, a short confirmation is
    enough. If the same message asks for help or advice, keep the normal answer
    path so the user still receives a generated response.
    """
    text = message.strip()
    return bool(
        facts
        and "?" not in text
        and not _ANSWER_REQUEST_INTENT.search(text)
    )


class RecentTurnsBuffer:
    """Small in-process, non-persistent buffer of recent turns per conversation.

    Only used to resolve follow-ups. It is NOT memory: saved facts live in
    FalkorDB. Keyed by (user_id, conversation_id) so a conversation id is never
    an authorization token.
    """

    def __init__(self, max_turns: int, max_conversations: int = 500) -> None:
        self._max_turns = max_turns
        self._max_conversations = max_conversations
        self._data: OrderedDict[tuple[str, str], deque[dict[str, str]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, user_id: str, conversation_id: str) -> list[dict[str, str]]:
        if self._max_turns == 0:
            return []
        with self._lock:
            turns = self._data.get((user_id, conversation_id))
            return list(turns) if turns else []

    def add(self, user_id: str, conversation_id: str, user_text: str, answer: str) -> None:
        if self._max_turns == 0:
            return
        key = (user_id, conversation_id)
        with self._lock:
            turns = self._data.get(key)
            if turns is None:
                turns = deque(maxlen=self._max_turns)
                self._data[key] = turns
            self._data.move_to_end(key)
            turns.append({"role": "user", "content": user_text[:_MAX_TURN_CHARS]})
            turns.append({"role": "assistant", "content": answer[:_MAX_TURN_CHARS]})
            while len(self._data) > self._max_conversations:
                self._data.popitem(last=False)


class _UserLocks:
    """Serialize the write path per user so a duplicate submission cannot race
    the duplicate check (single-process only)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, threading.Lock())


class ConversationService:
    def __init__(self, settings: Settings, registry: ServiceRegistry, history_store=None) -> None:
        self._settings = settings
        self._registry = registry
        self._history_store = history_store
        self._turns = RecentTurnsBuffer(settings.recent_turns_max)
        self._locks = _UserLocks()

    # ------------------------------------------------------------------
    def process_chat(self, request: ChatRequest) -> ChatResponse:
        s = self._settings
        if len(request.message) > s.max_message_chars:
            raise AppError(
                400,
                "message_too_long",
                f"Message must be at most {s.max_message_chars} characters.",
            )

        user_id = request.user_id
        message = request.message
        conversation_id = request.conversation_id or new_id("conv")
        message_id = new_id("msg")

        # 1. Extract proposed facts (never fabricated; failure is surfaced).
        # A clear standalone question cannot add or correct a fact, so avoid
        # spending a provider round trip on extraction for that common path.
        facts = (
            []
            if _is_standalone_question(message)
            else self._extract(message, user_id, conversation_id)
        )

        # 2. Match / correct / persist. Failure must not look like success.
        ops = MemoryOperationSummary()
        if facts:
            source_ids = SourceIds(message_id=message_id, conversation_id=conversation_id)
            ops = self._persist(user_id, facts, source_ids)
        operations = MemoryOperations(
            created=ops.created, updated=ops.updated, superseded=ops.superseded
        )

        # Fact-only statements already required extraction and persistence.
        # Avoid a second provider call for an answer the user did not request.
        # Confirm only after the write has succeeded.
        if _is_memory_only_statement(message, facts):
            answer = "Got it — your memory has been updated."
            self._record_turn(
                user_id,
                conversation_id,
                message,
                answer,
                {"memory_operations": operations.model_dump(), "memories_used": []},
            )
            return ChatResponse(
                conversation_id=conversation_id,
                answer=answer,
                memories_used=[],
                memory_operations=operations,
            )

        # 3. Retrieve AFTER persisting so newly saved facts can be used.
        memories = self._retrieve(user_id, message)

        # 4. Ground + answer. Memories are already saved at this point, so a
        #    failure here reports what was saved.
        recent = self._recent_turns(user_id, conversation_id)
        grounding, answer = self._generate(message, memories, recent, operations)

        # Evidence = exactly the records placed in the generation request.
        retrieved_ids = {m.memory_id for m in memories}
        evidence = [m for m in grounding.memories if m.memory_id in retrieved_ids]

        used_items = [
            MemoryUsed(
                memory_id=m.memory_id,
                content=m.content,
                type=m.category,
                subject=m.subject,
                updated_at=m.updated_at,
                relationship=m.relationship,
            )
            for m in evidence
        ]
        self._record_turn(
            user_id,
            conversation_id,
            message,
            answer,
            {
                "memory_operations": operations.model_dump(),
                "memories_used": [item.model_dump(mode="json") for item in used_items],
            },
        )

        return ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            memories_used=used_items,
            memory_operations=operations,
        )

    def _recent_turns(self, user_id: str, conversation_id: str) -> list[dict[str, str]]:
        if self._history_store is None:
            return self._turns.get(user_id, conversation_id)
        try:
            return self._history_store.recent_messages(
                user_id, conversation_id, self._settings.recent_turns_max
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("conversation history read failed: %s", type(exc).__name__, exc_info=True)
            raise AppError(503, "conversation_history_unavailable", "Conversation history is unavailable.") from None

    def _record_turn(
        self,
        user_id: str,
        conversation_id: str,
        message: str,
        answer: str,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._history_store is not None:
            try:
                self._history_store.save_turn(
                    user_id, conversation_id, message, answer, assistant_metadata
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("conversation history write failed: %s", type(exc).__name__, exc_info=True)
                raise AppError(503, "conversation_history_unavailable", "Conversation history could not be saved.") from None
        self._turns.add(user_id, conversation_id, message, answer)

    # ------------------------------------------------------------------
    def _call(self, component: str, *args: Any, details: dict | None = None, **kwargs: Any) -> Any:
        try:
            fn: Callable[..., Any] = self._registry.get(component)
        except AppError:
            raise component_error(component, details) from None
        try:
            return fn(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("%s failed: %s", component, type(exc).__name__, exc_info=True)
            raise component_error(component, details) from None

    def _extract(self, message: str, user_id: str, conversation_id: str) -> list[ProposedFact]:
        raw = self._call("extract_facts", message, user_id, conversation_id)
        try:
            facts = [ProposedFact.model_validate(f) for f in (raw or [])]
        except (ValidationError, TypeError):
            logger.error("extract_facts returned malformed output")
            raise component_error("extract_facts") from None
        cap = self._settings.max_facts_per_message
        if len(facts) > cap:
            logger.warning("Extractor returned %d facts; keeping first %d", len(facts), cap)
            facts = facts[:cap]
        return facts

    def _persist(
        self, user_id: str, facts: list[ProposedFact], source_ids: SourceIds
    ) -> MemoryOperationSummary:
        with self._locks.get(user_id):
            raw = self._call("upsert_memories", user_id, facts, source_ids)
        try:
            return MemoryOperationSummary.model_validate(raw)
        except ValidationError:
            # We cannot tell what was written; do not claim success.
            logger.error("upsert_memories returned malformed summary")
            raise component_error("upsert_memories") from None

    def _retrieve(self, user_id: str, question: str) -> list[RetrievedMemory]:
        limit = self._settings.max_context_memories
        raw = self._call("retrieve_memories", user_id, question, limit=limit)
        try:
            records = [RetrievedMemory.model_validate(r) for r in (raw or [])]
        except (ValidationError, TypeError):
            logger.error("retrieve_memories returned malformed output")
            raise component_error("retrieve_memories") from None

        seen: set[str] = set()
        result: list[RetrievedMemory] = []
        for m in records:
            # Defense in depth: never let another user's or inactive record
            # reach the LLM or the evidence list.
            if m.user_id != user_id or m.status != "active":
                logger.error("retrieve_memories returned a foreign/inactive record; dropped")
                continue
            if m.memory_id in seen:
                continue
            seen.add(m.memory_id)
            result.append(m)
            if len(result) >= limit:
                break
        return result

    def _generate(
        self,
        question: str,
        memories: list[RetrievedMemory],
        recent: list[dict[str, str]],
        operations: MemoryOperations,
    ) -> tuple[GroundingContext, str]:
        details = {"memory_operations": operations.model_dump()}
        raw_ctx = self._call("build_context", question, memories, details=details)
        try:
            grounding = GroundingContext.model_validate(raw_ctx)
        except (ValidationError, TypeError):
            logger.error("build_context returned malformed output")
            raise component_error("build_context", details) from None

        answer = self._call("generate_answer", question, grounding, recent, details=details)
        if not isinstance(answer, str) or not answer.strip():
            logger.error("generate_answer returned an empty/non-string answer")
            raise component_error("generate_answer", details)
        return grounding, answer.strip()
