"""Interfaces the backend expects from the separately developed modules.

These document (and type-check) what Members 2 and 4 must provide. The
function names/signatures come from PROJECT_CONTRACT.md section 8; the
GraphRepository method signatures are not fixed by the contract, so the ones
below are the backend's proposal and must be confirmed with Member 2.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from app.models.contracts import (
    GroundingContext,
    MemoryOperationSummary,
    ProposedFact,
    RetrievedMemory,
    SourceIds,
)

# --- Member 4: app/services/memory_extractor.py --------------------------------
class ExtractFacts(Protocol):
    def __call__(
        self, message: str, user_id: str, conversation_id: str
    ) -> Sequence[ProposedFact | Mapping[str, Any]]: ...


# --- Member 2: app/services/memory_service.py ----------------------------------
class UpsertMemories(Protocol):
    def __call__(
        self, user_id: str, proposed_facts: Sequence[ProposedFact], source_ids: SourceIds
    ) -> MemoryOperationSummary | Mapping[str, Any]: ...


# --- Member 2: app/services/retrieval_service.py -------------------------------
class RetrieveMemories(Protocol):
    def __call__(
        self, user_id: str, question: str, limit: int = 10
    ) -> Sequence[RetrievedMemory | Mapping[str, Any]]: ...


# --- Member 4: app/services/llm_service.py (or retrieval_service.py) -----------
class BuildContext(Protocol):
    def __call__(
        self, question: str, memories: Sequence[RetrievedMemory]
    ) -> GroundingContext | Mapping[str, Any]: ...


class GenerateAnswer(Protocol):
    def __call__(
        self,
        question: str,
        grounding_context: GroundingContext,
        recent_turns: list[dict[str, str]],  # [{"role": "user"|"assistant", "content": str}]
    ) -> str: ...


# --- Member 2: app/db/falkordb_client.py ---------------------------------------
@runtime_checkable
class GraphRepository(Protocol):
    """All FalkorDB access. Records are mappings with the Memory node fields.

    Every method must scope by ``user_id`` and must be fully parameterized.
    ``list``/``get``/``update``/``delete`` only touch the caller's own records.
    """

    def create(self, record: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def get(self, user_id: str, memory_id: str) -> Mapping[str, Any] | None:
        """Owned record (any status) or None."""

    def list(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[Sequence[Mapping[str, Any]], int]:
        """Active records, newest ``updated_at`` first, plus total active count."""

    def update(
        self,
        user_id: str,
        memory_id: str,
        *,
        content: str,
        category: str,
        subject: str,
        normalized_subject: str,
        updated_at: str,
    ) -> Mapping[str, Any] | None:
        """Update an ACTIVE owned record; None if missing/not owned/not active."""

    def delete(self, user_id: str, memory_id: str) -> bool:
        """Delete owned record and its RELATED_TO edges. False if no match."""

    def related(self, user_id: str, memory_id: str, limit: int) -> Sequence[Mapping[str, Any]]:
        """One-hop same-user active neighbours (used by retrieval)."""

    def health(self) -> bool:
        """Lightweight read query; True when reachable."""

    # OPTIONAL (not required by the Protocol check): used by GET /graph/{user_id}
    # def list_relationships(self, user_id: str, limit: int) -> Sequence[Mapping[str, str]]:
    #     """RELATED_TO edges among the user's active memories:
    #     [{"source": memory_id, "target": memory_id}, ...]"""
