"""LIVE FalkorDB integration tests for MemoryMate AI.

NOTE ON TEST SCOPE:
Unlike ``tests/test_graph_layer.py`` (which uses a mocked FalkorDB engine),
every test in this module connects to a REAL FalkorDB server instance using the
official ``FalkorDB`` Python client. If the ``falkordb`` package is not
installed or the FalkorDB server is not reachable at ``FALKORDB_HOST:FALKORDB_PORT``,
these tests are skipped with an explicit diagnostic reason rather than faking
success.
"""

from __future__ import annotations

import os

import pytest

from app.db.falkordb_client import GraphDatabaseError, GraphRepository
from app.models.contracts import MemoryCategory, ProposedFact, SourceIds
from app.services.memory_service import (
    delete_user_memory,
    list_user_memories,
    update_user_memory,
    upsert_memories,
)
from app.services.retrieval_service import retrieve_memories
from app.utils import new_id


@pytest.fixture(scope="module")
def live_repo() -> GraphRepository:
    host = os.getenv("FALKORDB_HOST", "localhost")
    port = int(os.getenv("FALKORDB_PORT", "6379"))
    password = os.getenv("FALKORDB_PASSWORD") or None
    graph_name = os.getenv("FALKORDB_TEST_GRAPH", "memorymate_live_test")

    repo = GraphRepository(
        host=host,
        port=port,
        password=password,
        graph_name=graph_name,
        socket_timeout=3.0,
    )
    try:
        repo.ping()
    except GraphDatabaseError as exc:
        pytest.skip(f"Live FalkorDB server unavailable at {host}:{port}: {exc}")
    repo.ensure_indexes()
    return repo


def test_live_falkordb_end_to_end_acceptance(live_repo: GraphRepository):
    user_1 = f"live-u1-{new_id('u')[-8:]}"
    user_2 = f"live-u2-{new_id('u')[-8:]}"
    created_ids: list[tuple[str, str]] = []

    try:
        summary = upsert_memories(
            user_1,
            [
                ProposedFact(
                    content="Currently learning Python",
                    category=MemoryCategory.skill,
                    subject="Python",
                    operation_hint="new",
                ),
                ProposedFact(
                    content="Wants to build an AI project by November",
                    category=MemoryCategory.goal,
                    subject="AI project",
                    operation_hint="new",
                ),
                ProposedFact(
                    content="Can study one hour each day",
                    category=MemoryCategory.commitment,
                    subject="daily study availability",
                    operation_hint="new",
                ),
            ],
            SourceIds(message_id=new_id("msg"), conversation_id=new_id("conv")),
            repository=live_repo,
        )
        assert summary.created == 3
        items, total = list_user_memories(user_1, repository=live_repo)
        assert total == 3
        created_ids.extend((user_1, m.memory_id) for m in items)

        retrieved = retrieve_memories(
            user_1,
            "What should I focus on this week to reach my goal?",
            limit=10,
            repository=live_repo,
        )
        assert {m.subject for m in retrieved} == {
            "AI project",
            "Python",
            "daily study availability",
        }

        corr = upsert_memories(
            user_1,
            [
                ProposedFact(
                    content="Can study two hours each day",
                    category=MemoryCategory.commitment,
                    subject="daily study availability",
                    operation_hint="correction",
                )
            ],
            SourceIds(message_id=new_id("msg"), conversation_id=new_id("conv")),
            repository=live_repo,
        )
        assert corr.superseded == 1 and corr.created == 1
        items_after, total_after = list_user_memories(user_1, repository=live_repo)
        assert total_after == 3
        created_ids.extend((user_1, m.memory_id) for m in items_after)
        comm = next(m for m in items_after if m.subject == "daily study availability")
        assert comm.content == "Can study two hours each day"
        assert comm.provenance.get("supersedes_memory_id") is not None

        assert (
            retrieve_memories(user_1, "What is my favorite language?", repository=live_repo)
            == []
        )

        assert live_repo.get(user_2, comm.memory_id) is None
        assert update_user_memory(user_2, comm.memory_id, content="x", repository=live_repo) is None
        assert delete_user_memory(user_2, comm.memory_id, repository=live_repo) is False
        assert delete_user_memory(user_1, comm.memory_id, repository=live_repo) is True
    finally:
        for uid, mid in set(created_ids):
            try:
                live_repo.delete(uid, mid)
            except Exception:  # noqa: BLE001
                pass