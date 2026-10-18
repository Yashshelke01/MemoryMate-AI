"""Shared types exchanged between the API layer and the separately developed
graph / extraction / LLM modules (PROJECT_CONTRACT.md section 8).

Members 2 and 4 import these so every module agrees on the same shapes.
All models accept either dicts or arbitrary objects with matching attributes
(``from_attributes``), so modules may return whichever is convenient.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils import normalize_subject


class MemoryCategory(str, Enum):
    goal = "goal"
    skill = "skill"
    project = "project"
    task = "task"
    preference = "preference"
    commitment = "commitment"
    decision = "decision"
    other = "other"


_BASE = ConfigDict(from_attributes=True, extra="ignore", use_enum_values=False)


class ProposedFact(BaseModel):
    """Output of ``extract_facts`` (one element of ``facts``)."""

    model_config = _BASE

    content: str = Field(min_length=1, max_length=500)
    category: MemoryCategory
    subject: str = Field(min_length=1, max_length=200)
    normalized_subject: str = ""
    source_quote: str | None = Field(default=None, max_length=500)
    operation_hint: Literal["new", "repeat", "correction", "conflict"] = "new"

    @model_validator(mode="after")
    def _fill_normalized(self) -> "ProposedFact":
        if not self.normalized_subject.strip():
            self.normalized_subject = normalize_subject(self.subject)
        return self


class SourceIds(BaseModel):
    """Identifiers passed to ``upsert_memories`` for provenance."""

    message_id: str
    conversation_id: str


class MemoryOperationSummary(BaseModel):
    """Output of ``upsert_memories``."""

    model_config = _BASE

    created: int = Field(default=0, ge=0)
    updated: int = Field(default=0, ge=0)
    superseded: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)  # informational; not part of the HTTP contract


class MemoryRecord(BaseModel):
    """A Memory node as returned by the GraphRepository."""

    model_config = _BASE

    memory_id: str
    user_id: str
    content: str
    category: MemoryCategory
    subject: str
    normalized_subject: str = ""
    created_at: str = ""
    updated_at: str
    source_message_id: str | None = None
    source_conversation_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: Literal["active", "superseded"] = "active"

    @field_validator("provenance", mode="before")
    @classmethod
    def _provenance_from_json_text(cls, v: Any) -> Any:
        # The graph may store provenance as JSON text (CONTRACT section 11).
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return v


class RetrievedMemory(MemoryRecord):
    """Output element of ``retrieve_memories``."""

    relationship: str | None = None


class GroundingContext(BaseModel):
    """Output of ``build_context``.

    ``memories`` is the exact set of records placed in the LLM request; the
    backend derives ``memories_used`` evidence from it (never from LLM text).
    """

    model_config = _BASE

    question: str
    memories: list[RetrievedMemory] = Field(default_factory=list)
    rendered: str = ""
