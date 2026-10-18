"""List / patch / delete / graph logic for the memory endpoints.

All persistence goes through the GraphRepository; no Cypher here. Every call
is scoped by user_id, and results are re-checked for ownership.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.container import ServiceRegistry
from app.errors import AppError, component_error, memory_not_found
from app.models.api import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryItem,
    MemoryListResponse,
    MemoryPatched,
    MemoryPatchRequest,
    MemoryPatchResponse,
    PublicProvenance,
)
from app.models.contracts import MemoryRecord
from app.utils import normalize_subject, utc_now_iso

logger = logging.getLogger(__name__)


def _to_record(raw: Any) -> MemoryRecord:
    try:
        return MemoryRecord.model_validate(raw)
    except (ValidationError, TypeError):
        logger.error("Repository returned a malformed memory record")
        raise component_error("repository") from None


def _to_item(m: MemoryRecord) -> MemoryItem:
    return MemoryItem(
        memory_id=m.memory_id,
        user_id=m.user_id,
        content=m.content,
        category=m.category,
        subject=m.subject,
        created_at=m.created_at,
        updated_at=m.updated_at,
        provenance=PublicProvenance(
            kind=str(m.provenance.get("kind") or "user_statement"),
            source_message_id=m.source_message_id,
            supersedes_memory_id=m.provenance.get("supersedes_memory_id"),
        ),
    )


class MemoryAdminService:
    def __init__(self, settings: Settings, registry: ServiceRegistry) -> None:
        self._settings = settings
        self._registry = registry

    def _repo(self) -> Any:
        return self._registry.get("repository")

    def _guard(self, fn, *args, **kwargs):
        """Call the repository; map any failure to a safe 503."""
        try:
            return fn(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Repository call failed: %s", type(exc).__name__, exc_info=True)
            raise component_error("repository") from None

    # ------------------------------------------------------------------
    def list_memories(self, user_id: str, limit: int, offset: int) -> MemoryListResponse:
        repo = self._repo()
        result = self._guard(repo.list, user_id, limit, offset)
        try:
            raw_items, total = result
        except (TypeError, ValueError):
            logger.error("Repository.list returned an unexpected shape")
            raise component_error("repository") from None
        records = [_to_record(r) for r in raw_items]
        owned = [r for r in records if r.user_id == user_id and r.status == "active"]
        if len(owned) != len(records):
            logger.error("Repository.list returned foreign/inactive records; dropped")
        return MemoryListResponse(
            items=[_to_item(r) for r in owned],
            limit=limit,
            offset=offset,
            total=int(total),
        )

    def update_memory(self, memory_id: str, req: MemoryPatchRequest) -> MemoryPatchResponse:
        repo = self._repo()
        raw = self._guard(repo.get, req.user_id, memory_id)
        if raw is None:
            raise memory_not_found()
        current = _to_record(raw)
        if current.user_id != req.user_id or current.status != "active":
            raise memory_not_found()

        content = req.content if req.content is not None else current.content
        category = req.category if req.category is not None else current.category
        subject = req.subject if req.subject is not None else current.subject

        updated_raw = self._guard(
            repo.update,
            req.user_id,
            memory_id,
            content=content,
            category=category.value,
            subject=subject,
            normalized_subject=normalize_subject(subject),
            updated_at=utc_now_iso(),
        )
        if updated_raw is None:
            raise memory_not_found()
        updated = _to_record(updated_raw)
        if updated.user_id != req.user_id:
            raise memory_not_found()
        return MemoryPatchResponse(
            memory=MemoryPatched(
                memory_id=updated.memory_id,
                user_id=updated.user_id,
                content=updated.content,
                category=updated.category,
                subject=updated.subject,
                updated_at=updated.updated_at,
            )
        )

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        repo = self._repo()
        deleted = self._guard(repo.delete, user_id, memory_id)
        if not deleted:
            raise memory_not_found()
        return True

    # ------------------------------------------------------------------
    def graph(self, user_id: str) -> GraphResponse:
        repo = self._repo()
        raw_items, _total = self._guard(repo.list, user_id, self._settings.graph_max_nodes, 0)
        records = [
            r for r in (_to_record(x) for x in raw_items) if r.user_id == user_id and r.status == "active"
        ]
        user_node = f"user:{user_id}"
        nodes = [GraphNode(id=user_node, label=user_id, type="user")]
        edges: list[GraphEdge] = []
        ids = {r.memory_id for r in records}
        for r in records:
            label = r.content if len(r.content) <= 120 else r.content[:117] + "..."
            nodes.append(GraphNode(id=r.memory_id, label=label, type=r.category.value))
            edges.append(GraphEdge(source=user_node, target=r.memory_id, type="HAS_MEMORY"))

        # RELATED_TO edges need the optional repository method; without it only
        # ownership edges are returned (documented in README).
        list_rel = getattr(repo, "list_relationships", None)
        if callable(list_rel) and ids:
            rels = self._guard(list_rel, user_id, self._settings.graph_max_nodes * 5)
            for rel in rels or []:
                src, tgt = rel.get("source"), rel.get("target")
                if src in ids and tgt in ids:
                    edges.append(GraphEdge(source=src, target=tgt, type="RELATED_TO"))
        return GraphResponse(nodes=nodes, edges=edges)
