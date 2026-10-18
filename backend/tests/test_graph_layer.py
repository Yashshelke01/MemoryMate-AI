"""MOCKED unit and API integration tests for the MemoryMate AI graph layer.

NOTE ON TEST SCOPE:
These tests use a stateful mock FalkorDB graph engine (``MockFalkorGraph``) that
emulates FalkorDB ``Node`` and ``QueryResult`` objects and verifies the exact
parameterized Cypher queries and parameters emitted by ``GraphRepository``.
They do NOT claim live FalkorDB server execution; live server tests live in
``tests/test_falkordb_live.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.falkordb_client import (
    GraphDatabaseError,
    GraphRepository,
    set_default_repository,
)
from app.db.graph_queries import (
    CREATE_MEMORY_QUERY,
    DELETE_MEMORY_QUERY,
    HEALTH_CHECK_QUERY,
    LIST_ACTIVE_MEMORIES_QUERY,
    RELATED_MEMORIES_QUERY,
    SUPERSEDE_MEMORY_QUERY,
    UPDATE_MEMORY_QUERY,
    deserialize_provenance,
    serialize_provenance,
    validate_cypher_params,
)
from app.interfaces import GraphRepository as GraphRepositoryProtocol
from app.main import create_app
from app.models.contracts import (
    MemoryCategory,
    ProposedFact,
    SourceIds,
)
from app.services.memory_service import (
    get_user_memory,
    list_user_memories,
    upsert_memories,
)
from app.services.retrieval_service import (
    build_context,
    retrieve_memories,
)
from app.utils import utc_now_iso
from tests.conftest import DEMO, OTHER
from tests.fakes import make_record


@dataclass
class MockFalkorNode:
    """Emulates ``falkordb.node.Node`` returned in ``QueryResult.result_set``."""

    id: int
    labels: list[str]
    properties: dict[str, Any]


@dataclass
class MockQueryResult:
    """Emulates ``falkordb.query_result.QueryResult``."""

    result_set: list[list[Any]] = field(default_factory=list)


class MockFalkorGraph:
    """Stateful mock of ``falkordb.Graph`` that validates parameterized Cypher
    calls and executes the canonical MemoryMate graph operations in-memory.
    """

    def __init__(self) -> None:
        self.users: set[str] = set()
        self.memories: dict[str, dict[str, Any]] = {}
        self.has_memory: set[tuple[str, str]] = set()
        self.related_to: dict[tuple[str, str], str] = {}
        self.executed_queries: list[tuple[str, dict[str, Any], bool]] = []
        self.fail_with: Exception | None = None
        self.healthy: bool = True
        self._next_node_id = 1

    def _node(self, props: Mapping[str, Any]) -> MockFalkorNode:
        nid = self._next_node_id
        self._next_node_id += 1
        return MockFalkorNode(id=nid, labels=["Memory"], properties=dict(props))

    def ro_query(
        self, query: str, params: dict[str, Any] | None = None, timeout: int | None = None
    ) -> MockQueryResult:
        return self._dispatch(query, params or {}, read_only=True)

    def query(
        self, query: str, params: dict[str, Any] | None = None, timeout: int | None = None
    ) -> MockQueryResult:
        return self._dispatch(query, params or {}, read_only=False)

    def _dispatch(
        self, query: str, params: dict[str, Any], *, read_only: bool
    ) -> MockQueryResult:
        if self.fail_with is not None:
            raise self.fail_with

        for k, v in params.items():
            assert v is not None, f"Parameter {k!r} must not be None in FalkorDB"
            assert not isinstance(v, Mapping), f"Parameter {k!r} must not be a dict in FalkorDB"

        self.executed_queries.append((query, dict(params), read_only))
        q = query.strip()

        if q == HEALTH_CHECK_QUERY:
            return MockQueryResult([[1 if self.healthy else 0]])

        if q.startswith("CREATE INDEX"):
            return MockQueryResult([])

        if q == CREATE_MEMORY_QUERY:
            user_id = params["user_id"]
            mem_id = params["memory_id"]
            self.users.add(user_id)
            if mem_id not in self.memories:
                self.memories[mem_id] = dict(params)
            existing = self.memories[mem_id]
            if existing["user_id"] != user_id:
                return MockQueryResult([])
            self.has_memory.add((user_id, mem_id))
            return MockQueryResult([[self._node(existing)]])

        if "MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})" in q:
            user_id = params["user_id"]
            mem_id = params["memory_id"]
            rec = self.memories.get(mem_id)
            owned = (
                rec is not None
                and (user_id, mem_id) in self.has_memory
                and rec.get("user_id") == user_id
            )

            if q.endswith("RETURN m\nLIMIT 1"):
                return MockQueryResult([[self._node(rec)]]) if owned else MockQueryResult([])

            if q == UPDATE_MEMORY_QUERY:
                if not owned or rec.get("status") != "active":
                    return MockQueryResult([])
                rec["content"] = params["content"]
                rec["category"] = params["category"]
                rec["subject"] = params["subject"]
                rec["normalized_subject"] = params["normalized_subject"]
                rec["updated_at"] = params["updated_at"]
                return MockQueryResult([[self._node(rec)]])

            if q == DELETE_MEMORY_QUERY:
                if not owned:
                    return MockQueryResult([[0]])
                del self.memories[mem_id]
                self.has_memory.discard((user_id, mem_id))
                self.related_to = {
                    pair: reason
                    for pair, reason in self.related_to.items()
                    if mem_id not in pair
                }
                return MockQueryResult([[1]])

            if q == RELATED_MEMORIES_QUERY:
                if not owned or rec.get("status") != "active":
                    return MockQueryResult([])
                limit = int(params["limit"])
                neighbors: list[tuple[dict[str, Any], str]] = []
                for (src, tgt), reason in self.related_to.items():
                    other_id = tgt if src == mem_id else (src if tgt == mem_id else None)
                    if not other_id or other_id == mem_id:
                        continue
                    other = self.memories.get(other_id)
                    if (
                        other
                        and (user_id, other_id) in self.has_memory
                        and other.get("user_id") == user_id
                        and other.get("status") == "active"
                    ):
                        neighbors.append((other, reason))
                neighbors.sort(
                    key=lambda item: (item[0]["updated_at"], item[0]["memory_id"]),
                    reverse=True,
                )
                return MockQueryResult(
                    [[self._node(n), reason] for n, reason in neighbors[:limit]]
                )

        if q == SUPERSEDE_MEMORY_QUERY:
            user_id = params["user_id"]
            old_id = params["old_memory_id"]
            old_rec = self.memories.get(old_id)
            if (
                old_rec is None
                or (user_id, old_id) not in self.has_memory
                or old_rec.get("user_id") != user_id
                or old_rec.get("status") != "active"
            ):
                return MockQueryResult([])
            old_rec["status"] = "superseded"
            old_rec["updated_at"] = params["updated_at"]

            new_id_val = params["memory_id"]
            new_props = {k: v for k, v in params.items() if k != "old_memory_id"}
            new_props["status"] = "active"
            self.memories[new_id_val] = new_props
            self.has_memory.add((user_id, new_id_val))
            return MockQueryResult([[self._node(new_props), self._node(old_rec)]])

        if "RETURN count(m) AS total" in q:
            user_id = params["user_id"]
            active = [
                m
                for mid, m in self.memories.items()
                if (user_id, mid) in self.has_memory
                and m.get("user_id") == user_id
                and m.get("status") == "active"
            ]
            return MockQueryResult([[len(active)]])

        if q == LIST_ACTIVE_MEMORIES_QUERY:
            user_id = params["user_id"]
            offset = int(params["offset"])
            limit = int(params["limit"])
            active = [
                m
                for mid, m in self.memories.items()
                if (user_id, mid) in self.has_memory
                and m.get("user_id") == user_id
                and m.get("status") == "active"
            ]
            active.sort(key=lambda m: m["memory_id"])
            active.sort(key=lambda m: m["updated_at"], reverse=True)
            sliced = active[offset : offset + limit]
            return MockQueryResult([[self._node(m)] for m in sliced])

        if "AND m.normalized_subject = $normalized_subject" in q:
            user_id = params["user_id"]
            norm_subj = params["normalized_subject"]
            cat = params["category"]
            limit = int(params["limit"])
            matches = [
                m
                for mid, m in self.memories.items()
                if (user_id, mid) in self.has_memory
                and m.get("user_id") == user_id
                and m.get("status") == "active"
                and m.get("normalized_subject") == norm_subj
                and (not cat or m.get("category") == cat)
            ]
            matches.sort(key=lambda m: m["updated_at"], reverse=True)
            return MockQueryResult([[self._node(m)] for m in matches[:limit]])

        if "CONTAINS toLower(" in q:
            user_id = params["user_id"]
            limit = int(params["limit"])
            terms = (
                [t.lower() for t in params["terms"]]
                if "terms" in params
                else [str(params["term"]).lower()]
            )
            hits: list[dict[str, Any]] = []
            seen: set[str] = set()
            for mid, m in self.memories.items():
                if (
                    (user_id, mid) not in self.has_memory
                    or m.get("user_id") != user_id
                    or m.get("status") != "active"
                ):
                    continue
                c_low = m["content"].lower()
                s_low = m["subject"].lower()
                ns_low = m["normalized_subject"].lower()
                cat_low = m["category"].lower()
                if any(
                    t in c_low or t in s_low or t in ns_low or t == cat_low
                    for t in terms
                ):
                    if mid not in seen:
                        seen.add(mid)
                        hits.append(m)
            hits.sort(key=lambda m: m["updated_at"], reverse=True)
            return MockQueryResult([[self._node(m)] for m in hits[:limit]])

        if "MERGE (m1)-[r:RELATED_TO]->(m2)" in q:
            user_id = params["user_id"]
            src = params["source_id"]
            tgt = params["target_id"]
            reason = params["reason"]
            m1 = self.memories.get(src)
            m2 = self.memories.get(tgt)
            if (
                not m1
                or not m2
                or src == tgt
                or (user_id, src) not in self.has_memory
                or (user_id, tgt) not in self.has_memory
                or m1.get("user_id") != user_id
                or m2.get("user_id") != user_id
                or m1.get("status") != "active"
                or m2.get("status") != "active"
            ):
                return MockQueryResult([[0]])
            self.related_to[(src, tgt)] = reason
            return MockQueryResult([[1]])

        if "RETURN m1.memory_id AS source, m2.memory_id AS target" in q:
            user_id = params["user_id"]
            limit = int(params["limit"])
            rows: list[list[str]] = []
            for (src, tgt), reason in sorted(self.related_to.items()):
                m1 = self.memories.get(src)
                m2 = self.memories.get(tgt)
                if (
                    m1
                    and m2
                    and (user_id, src) in self.has_memory
                    and (user_id, tgt) in self.has_memory
                    and m1.get("user_id") == user_id
                    and m2.get("user_id") == user_id
                    and m1.get("status") == "active"
                    and m2.get("status") == "active"
                ):
                    rows.append([src, tgt, reason])
            return MockQueryResult(rows[:limit])

        raise AssertionError(f"Unrecognized Cypher query in MockFalkorGraph: {query}")


@pytest.fixture
def mock_graph() -> MockFalkorGraph:
    return MockFalkorGraph()


@pytest.fixture
def graph_repo(mock_graph: MockFalkorGraph) -> GraphRepository:
    repo = GraphRepository(graph_name="memorymate_test", graph=mock_graph)
    yield repo
    set_default_repository(None)


def test_graph_repository_implements_protocol(graph_repo: GraphRepository):
    assert isinstance(graph_repo, GraphRepositoryProtocol)


def test_provenance_and_param_serialization_safety():
    prov = {"kind": "user_statement", "source_text": "I learn Python", "supersedes_memory_id": None}
    encoded = serialize_provenance(prov)
    assert isinstance(encoded, str)
    decoded = deserialize_provenance(encoded)
    assert decoded == prov

    with pytest.raises(ValueError):
        validate_cypher_params({"bad-name!": "x"})
    with pytest.raises(ValueError):
        validate_cypher_params({"nested": {"a": 1}})
    with pytest.raises(ValueError):
        validate_cypher_params({"null_val": None})


def test_health_check_and_failure_handling(
    graph_repo: GraphRepository, mock_graph: MockFalkorGraph
):
    assert graph_repo.health() is True
    assert mock_graph.executed_queries[-1] == (HEALTH_CHECK_QUERY, {}, False)
    mock_graph.healthy = False
    assert graph_repo.health() is False
    mock_graph.healthy = True
    mock_graph.fail_with = RuntimeError("connection refused")
    assert graph_repo.health() is False


def test_create_get_list_and_idempotency(
    graph_repo: GraphRepository, mock_graph: MockFalkorGraph
):
    now = utc_now_iso()
    rec = {
        "memory_id": "mem_11111111-1111-1111-1111-111111111111",
        "user_id": DEMO,
        "content": "Currently learning Python",
        "category": "skill",
        "subject": "Python",
        "normalized_subject": "python",
        "created_at": now,
        "updated_at": now,
        "source_message_id": "msg_1",
        "source_conversation_id": "conv_1",
        "provenance": {"kind": "user_statement", "source_text": "I'm learning Python."},
        "status": "active",
    }
    created = graph_repo.create(rec)
    assert created["memory_id"] == rec["memory_id"]
    assert created["provenance"]["kind"] == "user_statement"
    raw_stored = mock_graph.memories[rec["memory_id"]]["provenance"]
    assert isinstance(raw_stored, str) and json.loads(raw_stored)["kind"] == "user_statement"

    retry = graph_repo.create(rec)
    assert retry["memory_id"] == rec["memory_id"]
    assert len(mock_graph.memories) == 1

    conflict_rec = {**rec, "user_id": OTHER}
    with pytest.raises(GraphDatabaseError):
        graph_repo.create(conflict_rec)

    assert graph_repo.get(DEMO, rec["memory_id"]) is not None
    assert graph_repo.get(OTHER, rec["memory_id"]) is None
    items, total = graph_repo.list(DEMO, limit=10, offset=0)
    assert total == 1 and len(items) == 1
    other_items, other_total = graph_repo.list(OTHER, limit=10, offset=0)
    assert other_total == 0 and other_items == []


def test_update_and_safe_delete_user_isolation(
    graph_repo: GraphRepository, mock_graph: MockFalkorGraph
):
    now = "2026-10-17T10:00:00Z"
    rec1 = {
        "memory_id": "mem_a",
        "user_id": DEMO,
        "content": "Can study one hour each day",
        "category": "commitment",
        "subject": "daily study availability",
        "normalized_subject": "daily study availability",
        "created_at": now,
        "updated_at": now,
        "source_message_id": "msg_a",
        "source_conversation_id": "conv_a",
        "provenance": {"kind": "user_statement", "source_text": "1 hour"},
        "status": "active",
    }
    rec2 = {
        **rec1,
        "memory_id": "mem_b",
        "content": "Wants to build an AI project",
        "category": "goal",
        "subject": "AI project",
        "normalized_subject": "ai project",
    }
    graph_repo.create(rec1)
    graph_repo.create(rec2)
    assert graph_repo.create_relationship(DEMO, "mem_a", "mem_b", reason="supports goal") is True

    assert (
        graph_repo.update(
            OTHER,
            "mem_a",
            content="hacked",
            category="commitment",
            subject="daily study availability",
            normalized_subject="daily study availability",
            updated_at="2026-10-17T11:00:00Z",
        )
        is None
    )
    assert graph_repo.delete(OTHER, "mem_a") is False

    updated = graph_repo.update(
        DEMO,
        "mem_a",
        content="Can study two hours each day",
        category="commitment",
        subject="daily study availability",
        normalized_subject="daily study availability",
        updated_at="2026-10-17T11:00:00Z",
    )
    assert updated is not None
    assert updated["content"] == "Can study two hours each day"
    assert updated["created_at"] == now
    assert updated["provenance"]["source_text"] == "1 hour"

    assert graph_repo.delete(DEMO, "mem_a") is True
    assert graph_repo.get(DEMO, "mem_a") is None
    assert graph_repo.get(DEMO, "mem_b") is not None
    assert graph_repo.list_relationships(DEMO) == []
    assert DEMO in mock_graph.users


def test_upsert_duplicate_correction_and_conflict(
    graph_repo: GraphRepository, mock_graph: MockFalkorGraph
):
    src1 = SourceIds(message_id="msg_101", conversation_id="conv_101")
    facts = [
        ProposedFact(
            content="Currently learning Python",
            category=MemoryCategory.skill,
            subject="Python",
            normalized_subject="python",
            source_quote="I'm learning Python.",
            operation_hint="new",
        ),
        ProposedFact(
            content="Wants to build an AI project by November",
            category=MemoryCategory.goal,
            subject="AI project",
            normalized_subject="ai project",
            source_quote="I want to build an AI project by November.",
            operation_hint="new",
        ),
        ProposedFact(
            content="Can study one hour each day",
            category=MemoryCategory.commitment,
            subject="daily study availability",
            normalized_subject="daily study availability",
            source_quote="I can study one hour every day.",
            operation_hint="new",
        ),
    ]

    summary1 = upsert_memories(DEMO, facts, src1, repository=graph_repo)
    assert summary1.created == 3
    assert summary1.superseded == 0
    assert summary1.duplicates == 0

    rels = graph_repo.list_relationships(DEMO)
    assert len(rels) >= 2

    dup_summary = upsert_memories(
        DEMO,
        [facts[0]],
        SourceIds(message_id="msg_102", conversation_id="conv_101"),
        repository=graph_repo,
    )
    assert dup_summary.created == 0
    assert dup_summary.duplicates == 1

    conflict_fact = ProposedFact(
        content="Maybe can study five hours on weekends",
        category=MemoryCategory.commitment,
        subject="daily study availability",
        normalized_subject="daily study availability",
        operation_hint="conflict",
    )
    conflict_summary = upsert_memories(
        DEMO,
        [conflict_fact],
        SourceIds(message_id="msg_103", conversation_id="conv_101"),
        repository=graph_repo,
    )
    assert conflict_summary.created == 0 and conflict_summary.superseded == 0
    active_before, _ = list_user_memories(DEMO, repository=graph_repo)
    comm_before = next(m for m in active_before if m.subject == "daily study availability")
    assert comm_before.content == "Can study one hour each day"

    correction_fact = ProposedFact(
        content="Can study two hours each day",
        category=MemoryCategory.commitment,
        subject="daily study availability",
        normalized_subject="daily study availability",
        source_quote="I now have two hours available each day.",
        operation_hint="correction",
    )
    corr_summary = upsert_memories(
        DEMO,
        [correction_fact],
        SourceIds(message_id="msg_104", conversation_id="conv_102"),
        repository=graph_repo,
    )
    assert corr_summary.superseded == 1
    assert corr_summary.created == 1

    old_stored = get_user_memory(DEMO, comm_before.memory_id, repository=graph_repo)
    assert old_stored is not None and old_stored.status == "superseded"

    active_after, total_after = list_user_memories(DEMO, repository=graph_repo)
    assert total_after == 3
    comm_after = next(m for m in active_after if m.subject == "daily study availability")
    assert comm_after.content == "Can study two hours each day"
    assert comm_after.provenance["supersedes_memory_id"] == comm_before.memory_id


def test_same_message_duplicate_quote_with_different_subjects_is_saved_once(
    graph_repo: GraphRepository,
):
    quote = "Sarthak and Yash are my friends."
    facts = [
        ProposedFact(content=quote, category=MemoryCategory.other, subject="Sarthak", source_quote=quote),
        ProposedFact(content=quote, category=MemoryCategory.other, subject="Yash", source_quote=quote),
    ]

    summary = upsert_memories(
        DEMO,
        facts,
        SourceIds(message_id="msg_duplicate_people", conversation_id="conv_duplicate_people"),
        repository=graph_repo,
    )

    active, total = list_user_memories(DEMO, repository=graph_repo)
    assert summary.created == 1
    assert summary.duplicates == 1
    assert total == len(active) == 1
    assert active[0].content == quote


def test_upsert_cleans_older_active_duplicate_content_with_different_subjects(
    graph_repo: GraphRepository,
):
    quote = "Sarthak and Yash are my friends."
    first = make_record(user_id=DEMO, content=quote, category="other", subject="Sarthak", memory_id="mem_older-friend-1")
    second = make_record(user_id=DEMO, content=quote, category="other", subject="Yash", memory_id="mem_older-friend-2")
    graph_repo.create(first)
    graph_repo.create(second)

    summary = upsert_memories(
        DEMO,
        [ProposedFact(content=quote, category=MemoryCategory.other, subject="Sarthak", source_quote=quote)],
        SourceIds(message_id="msg_duplicate_cleanup", conversation_id="conv_duplicate_cleanup"),
        repository=graph_repo,
    )

    active, total = list_user_memories(DEMO, repository=graph_repo)
    assert summary.created == 0
    assert summary.duplicates == 1
    assert total == len(active) == 1
    assert active[0].memory_id == first["memory_id"]


def test_retrieval_cross_session_expansion_and_unknown_preference(
    graph_repo: GraphRepository,
):
    upsert_memories(
        DEMO,
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
                content="Can study two hours each day",
                category=MemoryCategory.commitment,
                subject="daily study availability",
                operation_hint="new",
            ),
        ],
        SourceIds(message_id="msg_1", conversation_id="conv_session_1"),
        repository=graph_repo,
    )

    results = retrieve_memories(
        DEMO,
        "What should I focus on this week to reach my goal?",
        limit=10,
        repository=graph_repo,
    )
    subjects = {m.subject for m in results}
    assert subjects == {"AI project", "Python", "daily study availability"}
    assert all(m.user_id == DEMO and m.status == "active" for m in results)
    assert all(m.relationship for m in results)

    ctx = build_context("What should I focus on this week to reach my goal?", results)
    assert len(ctx.memories) == 3
    assert "STORED_USER_MEMORIES" in ctx.rendered

    unknown = retrieve_memories(
        DEMO,
        "What is my favorite language?",
        limit=10,
        repository=graph_repo,
    )
    assert unknown == []
    empty_ctx = build_context("What is my favorite language?", unknown)
    assert empty_ctx.memories == []
    assert "NONE" in empty_ctx.rendered

    assert (
        retrieve_memories(
            OTHER,
            "What should I focus on this week to reach my goal?",
            limit=10,
            repository=graph_repo,
        )
        == []
    )


def test_fastapi_end_to_end_with_graph_layer(graph_repo: GraphRepository):
    extracted_queue: list[list[dict[str, Any]]] = []

    def fake_extract(message: str, user_id: str, conversation_id: str):
        return extracted_queue.pop(0) if extracted_queue else []

    def fake_generate(question: str, grounding_context, recent_turns):
        if not grounding_context.memories:
            return "I don't have that stored in your memories yet."
        return "Grounded answer using: " + ", ".join(m.subject for m in grounding_context.memories)

    settings = Settings(
        _env_file=None,
        sqlite_db_path=":memory:",
        chat_timeout_seconds=5,
    )
    app = create_app(
        settings,
        overrides={
            "repository": graph_repo,
            "extract_facts": fake_extract,
            "upsert_memories": upsert_memories,
            "retrieve_memories": retrieve_memories,
            "build_context": build_context,
            "generate_answer": fake_generate,
            "llm_is_configured": lambda: True,
        },
    )
    client = TestClient(app, raise_server_exceptions=False)
    from app.services.auth_service import hash_password
    password = "MemoryMate-test-password-1"
    app.state.sqlite_store.create_user("graph-test@example.test", hash_password(password), user_id=DEMO)
    client.post("/auth/login", json={"email": "graph-test@example.test", "password": password})

    assert client.get("/health").json() == {
        "status": "ok",
        "dependencies": {"falkordb": "ok", "llm": "configured"},
    }

    extracted_queue.append(
        [
            {
                "content": "Currently learning Python",
                "category": "skill",
                "subject": "Python",
                "normalized_subject": "python",
                "source_quote": "I'm learning Python.",
                "operation_hint": "new",
            },
            {
                "content": "Wants to build an AI project by November",
                "category": "goal",
                "subject": "AI project",
                "normalized_subject": "ai project",
                "source_quote": "I want to build an AI project by November.",
                "operation_hint": "new",
            },
            {
                "content": "Can study one hour each day",
                "category": "commitment",
                "subject": "daily study availability",
                "normalized_subject": "daily study availability",
                "source_quote": "I can study one hour every day.",
                "operation_hint": "new",
            },
        ]
    )
    r1 = client.post(
        "/chat",
        json={
            "message": "I'm learning Python. I want to build an AI project by November. I can study one hour every day.",
        },
    )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["memory_operations"] == {"created": 3, "updated": 0, "superseded": 0}

    extracted_queue.append([])
    r2 = client.post(
        "/chat",
        json={
            "message": "What should I focus on this week to reach my goal?",
            "conversation_id": None,
        },
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["conversation_id"] != b1["conversation_id"]
    used_subjects = {m["subject"] for m in b2["memories_used"]}
    assert used_subjects == {"AI project", "Python", "daily study availability"}

    g = client.get(f"/graph/{DEMO}").json()
    assert len(g["nodes"]) == 4
    edge_types = {e["type"] for e in g["edges"]}
    assert "HAS_MEMORY" in edge_types and "RELATED_TO" in edge_types
