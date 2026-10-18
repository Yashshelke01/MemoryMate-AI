"""TEST-ONLY in-memory fakes standing in for the modules owned by Members 2 and 4.

Nothing here is used by the application at runtime. Results from tests using
these fakes prove the API layer's behaviour against the agreed interfaces, NOT
real FalkorDB or real LLM behaviour.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from app.models.contracts import ProposedFact
from app.utils import new_id, utc_now_iso


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.relationships: list[dict[str, str]] = []
        self.healthy = True
        self.fail_with: Exception | None = None
        self.calls: list[tuple[str, tuple]] = []

    def _check(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.fail_with:
            raise self.fail_with

    def create(self, record):
        self._check("create", record["memory_id"])
        self.rows[record["memory_id"]] = copy.deepcopy(dict(record))
        return record

    def get(self, user_id, memory_id):
        self._check("get", user_id, memory_id)
        r = self.rows.get(memory_id)
        return copy.deepcopy(r) if r and r["user_id"] == user_id else None

    def list(self, user_id, limit, offset):
        self._check("list", user_id, limit, offset)
        mine = sorted(
            (r for r in self.rows.values() if r["user_id"] == user_id and r["status"] == "active"),
            key=lambda r: r["updated_at"],
            reverse=True,
        )
        return [copy.deepcopy(r) for r in mine[offset : offset + limit]], len(mine)

    def update(self, user_id, memory_id, *, content, category, subject, normalized_subject, updated_at):
        self._check("update", user_id, memory_id)
        r = self.rows.get(memory_id)
        if not r or r["user_id"] != user_id or r["status"] != "active":
            return None
        r.update(
            content=content,
            category=category,
            subject=subject,
            normalized_subject=normalized_subject,
            updated_at=updated_at,
        )
        return copy.deepcopy(r)

    def delete(self, user_id, memory_id):
        self._check("delete", user_id, memory_id)
        r = self.rows.get(memory_id)
        if not r or r["user_id"] != user_id:
            return False
        del self.rows[memory_id]
        self.relationships = [
            e for e in self.relationships if memory_id not in (e["source"], e["target"])
        ]
        return True

    def related(self, user_id, memory_id, limit):
        self._check("related", user_id, memory_id)
        return []

    def health(self):
        if self.fail_with:
            raise self.fail_with
        return self.healthy

    def list_relationships(self, user_id, limit):
        self._check("list_relationships", user_id)
        return list(self.relationships)


def make_record(user_id="demo-user-1", content="Currently learning Python", category="skill",
                subject="Python", status="active", memory_id=None, updated_at=None) -> dict[str, Any]:
    now = updated_at or utc_now_iso()
    return {
        "memory_id": memory_id or new_id("mem"),
        "user_id": user_id,
        "content": content,
        "category": category,
        "subject": subject,
        "normalized_subject": subject.lower(),
        "created_at": now,
        "updated_at": now,
        "source_message_id": new_id("msg"),
        "source_conversation_id": new_id("conv"),
        "provenance": {"kind": "user_statement", "source_text": content, "supersedes_memory_id": None},
        "status": status,
    }


class FakeAI:
    """Fake extractor / memory service / retrieval / LLM sharing one FakeRepository."""

    def __init__(self, repo: FakeRepository) -> None:
        self.repo = repo
        self.facts_to_extract: list[dict[str, Any]] = []
        self.extract_error: Exception | None = None
        self.upsert_error: Exception | None = None
        self.retrieve_error: Exception | None = None
        self.llm_error: Exception | None = None
        self.retrieve_override: list[dict[str, Any]] | None = None
        self.delay_extract = 0.0
        self.generate_calls: list[dict[str, Any]] = []
        self.upsert_calls = 0
        self._active = 0
        self.max_concurrent_upserts = 0
        self._guard = threading.Lock()

    # Member 4
    def extract_facts(self, message, user_id, conversation_id):
        if self.delay_extract:
            time.sleep(self.delay_extract)
        if self.extract_error:
            raise self.extract_error
        return [dict(f) for f in self.facts_to_extract]

    # Member 2
    def upsert_memories(self, user_id, proposed_facts, source_ids):
        with self._guard:
            self._active += 1
            self.max_concurrent_upserts = max(self.max_concurrent_upserts, self._active)
        try:
            self.upsert_calls += 1
            time.sleep(0.02)
            if self.upsert_error:
                raise self.upsert_error
            created = duplicates = 0
            for f in proposed_facts:
                assert isinstance(f, ProposedFact)
                existing = [
                    r for r in self.repo.rows.values()
                    if r["user_id"] == user_id and r["status"] == "active"
                    and r["normalized_subject"] == f.normalized_subject and r["content"] == f.content
                ]
                if existing:
                    duplicates += 1
                    continue
                rec = make_record(user_id, f.content, f.category.value, f.subject)
                rec["source_message_id"] = source_ids.message_id
                rec["source_conversation_id"] = source_ids.conversation_id
                self.repo.create(rec)
                created += 1
            return {"created": created, "updated": 0, "superseded": 0, "duplicates": duplicates}
        finally:
            with self._guard:
                self._active -= 1

    def retrieve_memories(self, user_id, question, limit=10):
        if self.retrieve_error:
            raise self.retrieve_error
        if self.retrieve_override is not None:
            return self.retrieve_override
        rows, _ = self.repo.list(user_id, limit, 0)
        words = {w.lower().strip("?.,!") for w in question.split()}
        hits = [r for r in rows if words & set(r["content"].lower().split()) or words & {r["subject"].lower()}]
        return hits[:limit]

    def build_context(self, question, memories):
        return {"question": question, "memories": list(memories), "rendered": "\n".join(m.content for m in memories)}

    def generate_answer(self, question, grounding_context, recent_turns):
        if self.llm_error:
            raise self.llm_error
        self.generate_calls.append(
            {"question": question, "memories": [m.memory_id for m in grounding_context.memories],
             "recent_turns": list(recent_turns)}
        )
        return f"answer using {len(grounding_context.memories)} memories"

    def overrides(self, repo: FakeRepository) -> dict[str, Any]:
        return {
            "repository": repo,
            "extract_facts": self.extract_facts,
            "upsert_memories": self.upsert_memories,
            "retrieve_memories": self.retrieve_memories,
            "build_context": self.build_context,
            "generate_answer": self.generate_answer,
            "llm_is_configured": lambda: True,
        }
