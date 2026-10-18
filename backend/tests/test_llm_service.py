from __future__ import annotations

import json

from app.services import llm_service
from tests.fakes import make_record


def test_build_context_only_uses_active_supplied_memories():
    active = make_record(content="I want to build an AI project by November", category="goal", subject="AI project")
    inactive = make_record(content="Used to study two hours", status="superseded")

    context = llm_service.build_context("What is my goal?", [active, inactive])

    assert [m.memory_id for m in context.memories] == [active["memory_id"]]
    assert active["memory_id"] in context.rendered
    assert inactive["memory_id"] not in context.rendered


def test_generate_answer_sends_bounded_evidence_and_does_not_accept_model_citations(monkeypatch):
    record = make_record(content="I can study one hour every day", category="commitment", subject="study availability")
    context = llm_service.build_context("What should I do?", [record])
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return {"answer": "Use the hour for a small project step each day."}

    monkeypatch.setattr(llm_service, "request_structured", fake_request)
    answer = llm_service.generate_answer(
        "What should I do?", context, [{"role": "user", "content": "I want to progress"}]
    )

    sent = json.loads(captured["user"])
    assert answer == "Use the hour for a small project step each day."
    assert sent["retrieved_records"][0]["memory_id"] == record["memory_id"]
    assert "Never invent" in captured["system"]
    assert "another user's data" in captured["system"]


def test_empty_evidence_is_explicitly_marked_in_context():
    context = llm_service.build_context("What is my favorite language?", [])
    assert context.memories == []
    assert json.loads(context.rendered.split("\n", 1)[1]) == []
    assert "no supplied memories" in llm_service._GROUNDING_SYSTEM
