from __future__ import annotations

import pytest

from app.config import Settings
from app.container import ServiceRegistry
from app.errors import AppError
from app.models.api import ChatRequest
from app.services.conversation_service import (
    ConversationService,
    _is_memory_only_statement,
    _is_standalone_question,
)
from app.models.contracts import ProposedFact
from tests.fakes import FakeAI, FakeRepository


def _service(ai: FakeAI, repo: FakeRepository) -> ConversationService:
    settings = Settings(_env_file=None)
    return ConversationService(settings, ServiceRegistry(settings, ai.overrides(repo)))


def test_standalone_question_skips_extraction_round_trip():
    repo = FakeRepository()
    ai = FakeAI(repo)
    ai.extract_error = RuntimeError("extractor should not be called")
    service = _service(ai, repo)

    response = service.process_chat(
        ChatRequest(user_id="demo-user-1", message="What should I focus on this week?")
    )

    assert response.memory_operations.created == 0
    assert len(ai.generate_calls) == 1


def test_saved_fact_statement_skips_generation_round_trip():
    repo = FakeRepository()
    ai = FakeAI(repo)
    ai.facts_to_extract = [{
        "content": "I also want to learn Java",
        "category": "skill",
        "subject": "Java",
    }]
    service = _service(ai, repo)

    response = service.process_chat(
        ChatRequest(user_id="demo-user-1", message="I also want to learn Java.")
    )

    assert response.memory_operations.created == 1
    assert response.answer == "Got it — your memory has been updated."
    assert response.memories_used == []
    assert ai.generate_calls == []
    assert len(repo.rows) == 1


def test_person_context_statement_is_confirmed_after_persistence():
    from app.services.memory_extractor import extract_facts

    repo = FakeRepository()
    ai = FakeAI(repo)
    message = "My friend is yash. He is a great cricketer."
    overrides = ai.overrides(repo)
    overrides["extract_facts"] = extract_facts
    settings = Settings(_env_file=None)
    service = ConversationService(settings, ServiceRegistry(settings, overrides))
    response = service.process_chat(
        ChatRequest(user_id="demo-user-1", message=message)
    )

    assert response.memory_operations.created == 1
    assert response.answer == "Got it — your memory has been updated."
    assert len(repo.rows) == 1
    saved = next(iter(repo.rows.values()))
    assert saved["content"] == message and saved["subject"] == "yash"
    assert ai.generate_calls == []


def test_fact_statement_with_advice_request_still_generates_answer():
    repo = FakeRepository()
    ai = FakeAI(repo)
    ai.facts_to_extract = [{
        "content": "I can study two hours daily",
        "category": "commitment",
        "subject": "study",
    }]
    service = _service(ai, repo)

    response = service.process_chat(
        ChatRequest(
            user_id="demo-user-1",
            message="I can study two hours daily. What should I focus on?",
        )
    )

    assert response.memory_operations.created == 1
    assert len(ai.generate_calls) == 1


def test_explicit_memory_request_still_runs_extraction():
    repo = FakeRepository()
    ai = FakeAI(repo)
    ai.extract_error = RuntimeError("extractor unavailable")
    service = _service(ai, repo)

    with pytest.raises(AppError) as error:
        service.process_chat(
            ChatRequest(
                user_id="demo-user-1",
                message="Can you remember that I am learning Java?",
            )
        )

    assert error.value.code == "extraction_unavailable"
    assert ai.generate_calls == []


@pytest.mark.parametrize(
    "message",
    [
        "I also want to learn Java.",
        "Can you remember that I study one hour daily?",
        "I can study two hours. What should I do?",
        "What should I focus on? I can study two hours daily.",
    ],
)
def test_statements_and_mixed_turns_still_use_extraction(message: str):
    assert not _is_standalone_question(message)


@pytest.mark.parametrize(
    ("message", "should_skip"),
    [
        ("I want to learn Java.", True),
        ("I can study two hours. What should I do?", False),
        ("My goal is to build an app. Help me plan.", False),
        ("I am learning Python.", True),
    ],
)
def test_memory_only_detection_preserves_mixed_requests(message, should_skip):
    fact = ProposedFact(content="example fact", category="skill", subject="Python")
    assert _is_memory_only_statement(message, [fact]) is should_skip
