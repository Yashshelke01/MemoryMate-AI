from __future__ import annotations

import pytest

from app.models.contracts import MemoryCategory
from app.services import memory_extractor


def test_extract_facts_accepts_only_verbatim_supported_durable_facts(monkeypatch):
    message = "I'm learning Python. I want to build an AI project by November. I can study one hour every day."
    raw = {
        "facts": [
            {"content": "I'm learning Python", "category": "skill", "subject": "Python", "source_quote": "I'm learning Python", "operation_hint": "new"},
            {"content": "I want to build an AI project by November", "category": "goal", "subject": "AI project", "source_quote": "I want to build an AI project by November", "operation_hint": "new"},
            {"content": "I can study one hour every day", "category": "commitment", "subject": "one hour every day", "source_quote": "I can study one hour every day", "operation_hint": "new"},
        ]
    }
    seen = {}

    def fake_request(**kwargs):
        seen.update(kwargs)
        return raw

    monkeypatch.setattr(memory_extractor, "request_structured", fake_request)
    facts = memory_extractor.extract_facts(message, "private-user", "private-conversation")

    assert [f.category for f in facts] == [MemoryCategory.skill, MemoryCategory.goal, MemoryCategory.commitment]
    assert [f.content for f in facts] == [f.source_quote for f in facts]
    assert "private-user" not in str(seen)
    assert "private-conversation" not in str(seen)


def test_extract_facts_rejects_a_quote_not_in_the_message(monkeypatch):
    monkeypatch.setattr(
        memory_extractor,
        "request_structured",
        lambda **_: {"facts": [{"content": "My favorite language is Rust", "category": "preference", "subject": "Rust", "source_quote": "My favorite language is Rust", "operation_hint": "new"}]},
    )
    with pytest.raises(ValueError, match="source quote"):
        memory_extractor.extract_facts("I am learning Python", "u", "c")


def test_extract_facts_rejects_non_verbatim_paraphrases(monkeypatch):
    monkeypatch.setattr(
        memory_extractor,
        "request_structured",
        lambda **_: {"facts": [{"content": "Currently learning Python", "category": "skill", "subject": "Python", "source_quote": "I'm learning Python", "operation_hint": "new"}]},
    )
    with pytest.raises(ValueError, match="source quote"):
        memory_extractor.extract_facts("I'm learning Python", "u", "c")


@pytest.mark.parametrize(
    "message",
    [
        "My friend is yash. He is a great cricketer.",
        "Yash Shelke is my friend, and he is also my roommate.",
        "Sarthak and Yash are my Friends.",
    ],
)
def test_explicit_person_relationship_is_saved_verbatim_without_llm(monkeypatch, message):
    def unexpected_provider_call(**_kwargs):
        raise AssertionError("explicit relationship extraction should not call the LLM")

    monkeypatch.setattr(memory_extractor, "request_structured", unexpected_provider_call)
    fact = memory_extractor.extract_facts(message, "private-user", "private-conversation")[0]

    assert fact.content == fact.source_quote == message
    assert fact.category == MemoryCategory.other
    assert fact.subject.casefold() in message.casefold()
