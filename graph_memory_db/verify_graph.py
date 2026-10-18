#!/usr/bin/env python3
"""Graph verification script for MemoryMate AI (FalkorDB).

Usage (from the repository root):
  python graph_memory_db/verify_graph.py
  python graph_memory_db/verify_graph.py --host localhost --port 6379 --graph memorymate_verify
  python graph_memory_db/verify_graph.py --print-commands
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.db.falkordb_client import GraphDatabaseError, GraphRepository  # noqa: E402
from app.models.contracts import MemoryCategory, ProposedFact, SourceIds  # noqa: E402
from app.services.memory_service import (  # noqa: E402
    delete_user_memory,
    list_user_memories,
    update_user_memory,
    upsert_memories,
)
from app.services.retrieval_service import build_context, retrieve_memories  # noqa: E402
from app.utils import new_id  # noqa: E402


def print_inspection_commands(host: str, port: int, graph_name: str, user_id: str) -> None:
    """Print exact redis-cli / FalkorDB commands for inspecting stored graph records."""
    print("=== FalkorDB Graph Inspection Commands ===")
    print(f"# 1. List all graphs in FalkorDB ({host}:{port})")
    print(f"redis-cli -h {host} -p {port} GRAPH.LIST\n")

    print("# 2. Inspect User nodes and their active HAS_MEMORY edges")
    print(
        f"redis-cli -h {host} -p {port} GRAPH.RO_QUERY {graph_name} "
        f"\"MATCH (u:User {{user_id: '{user_id}'}})-[:HAS_MEMORY]->(m:Memory) "
        f"WHERE m.status = 'active' "
        f"RETURN u.user_id, m.memory_id, m.category, m.subject, m.content, m.updated_at "
        f"ORDER BY m.updated_at DESC\"\n"
    )

    print("# 3. Inspect superseded Memory history and provenance chain")
    print(
        f"redis-cli -h {host} -p {port} GRAPH.RO_QUERY {graph_name} "
        f"\"MATCH (u:User {{user_id: '{user_id}'}})-[:HAS_MEMORY]->(m:Memory) "
        f"RETURN m.memory_id, m.status, m.subject, m.content, m.provenance "
        f"ORDER BY m.created_at ASC\"\n"
    )

    print("# 4. Inspect RELATED_TO edges between active memories for the user")
    print(
        f"redis-cli -h {host} -p {port} GRAPH.RO_QUERY {graph_name} "
        f"\"MATCH (u:User {{user_id: '{user_id}'}})-[:HAS_MEMORY]->(m1:Memory)"
        f"-[r:RELATED_TO]->(m2:Memory)<-[:HAS_MEMORY]-(u) "
        f"WHERE m1.status = 'active' AND m2.status = 'active' "
        f"RETURN m1.memory_id AS source, m1.subject AS source_subject, "
        f"r.reason AS reason, m2.memory_id AS target, m2.subject AS target_subject\"\n"
    )

    print("# 5. Count nodes by label and status")
    print(
        f"redis-cli -h {host} -p {port} GRAPH.RO_QUERY {graph_name} "
        f"\"MATCH (n) RETURN labels(n) AS labels, n.status AS status, count(n) AS total\""
    )


def run_live_verification(
    host: str,
    port: int,
    password: str | None,
    graph_name: str,
    cleanup: bool = True,
) -> int:
    """Execute end-to-end verification against a live FalkorDB instance."""
    print(f"[verify_graph] Connecting to FalkorDB at {host}:{port} (graph={graph_name!r})...")
    repo = GraphRepository(
        host=host,
        port=port,
        password=password,
        graph_name=graph_name,
        socket_timeout=5.0,
    )

    try:
        repo.ping()
    except GraphDatabaseError as exc:
        print(f"[verify_graph] BLOCKED: FalkorDB is unavailable ({exc}).", file=sys.stderr)
        print(
            "[verify_graph] Start FalkorDB first, e.g.:\n"
            "  docker run -p 6379:6379 -p 3000:3000 --rm falkordb/falkordb:latest\n"
            "and ensure the Python client is installed (`pip install FalkorDB==1.8.0`).",
            file=sys.stderr,
        )
        return 2

    print("[verify_graph] Health check OK (`RETURN 1 AS ok` -> 1).")
    repo.ensure_indexes()

    user_1 = f"verify-user-1-{new_id('u')[-8:]}"
    user_2 = f"verify-user-2-{new_id('u')[-8:]}"
    created_ids_u1: list[str] = []
    created_ids_u2: list[str] = []

    try:
        initial_facts = [
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
        conv_1 = new_id("conv")
        msg_1 = new_id("msg")
        summary_1 = upsert_memories(
            user_1,
            initial_facts,
            SourceIds(message_id=msg_1, conversation_id=conv_1),
            repository=repo,
        )
        assert summary_1.created == 3, f"Expected 3 created, got {summary_1}"
        print(f"[verify_graph] Step 1 OK: Created {summary_1.created} initial active memories.")

        active_u1, total_u1 = list_user_memories(user_1, limit=50, offset=0, repository=repo)
        assert total_u1 == 3 and len(active_u1) == 3
        created_ids_u1.extend(m.memory_id for m in active_u1)

        dup_summary = upsert_memories(
            user_1,
            [initial_facts[0]],
            SourceIds(message_id=new_id("msg"), conversation_id=conv_1),
            repository=repo,
        )
        assert dup_summary.created == 0 and dup_summary.duplicates == 1
        print("[verify_graph] Step 2 OK: Duplicate submission skipped without creating duplicate record.")

        retrieved = retrieve_memories(
            user_1,
            "What should I focus on this week to reach my goal?",
            limit=10,
            repository=repo,
        )
        retrieved_subjects = {m.subject for m in retrieved}
        assert "AI project" in retrieved_subjects, f"Goal missing from {retrieved_subjects}"
        assert "Python" in retrieved_subjects, f"1-hop related skill missing from {retrieved_subjects}"
        ctx = build_context("What should I focus on this week to reach my goal?", retrieved)
        assert len(ctx.memories) == len(retrieved)
        print(
            f"[verify_graph] Step 3 OK: Cross-session retrieval returned {len(retrieved)} "
            f"connected memories ({sorted(retrieved_subjects)})."
        )

        correction_fact = ProposedFact(
            content="Can study two hours each day",
            category=MemoryCategory.commitment,
            subject="daily study availability",
            normalized_subject="daily study availability",
            source_quote="I now have two hours available each day.",
            operation_hint="correction",
        )
        corr_summary = upsert_memories(
            user_1,
            [correction_fact],
            SourceIds(message_id=new_id("msg"), conversation_id=new_id("conv")),
            repository=repo,
        )
        assert corr_summary.superseded == 1 and corr_summary.created == 1
        active_after, total_after = list_user_memories(user_1, limit=50, offset=0, repository=repo)
        assert total_after == 3
        created_ids_u1.extend(m.memory_id for m in active_after if m.memory_id not in created_ids_u1)
        commitment_mem = next(m for m in active_after if m.subject == "daily study availability")
        assert commitment_mem.content == "Can study two hours each day"
        assert commitment_mem.provenance.get("supersedes_memory_id") is not None
        print(
            f"[verify_graph] Step 4 OK: Correction superseded {commitment_mem.provenance['supersedes_memory_id']} "
            f"with new active memory {commitment_mem.memory_id}."
        )

        patched = update_user_memory(
            user_1,
            commitment_mem.memory_id,
            content="Can study two and a half hours each day",
            repository=repo,
        )
        assert patched is not None and patched.content == "Can study two and a half hours each day"
        print("[verify_graph] Step 5 OK: Direct PATCH updated content while preserving provenance.")

        unknown = retrieve_memories(
            user_1,
            "What is my favorite language?",
            limit=10,
            repository=repo,
        )
        assert unknown == [], f"Expected empty list for unstored preference, got {unknown}"
        print("[verify_graph] Step 6 OK: Unstored favorite language query returned [].")

        u2_summary = upsert_memories(
            user_2,
            [
                ProposedFact(
                    content="Prefers dark mode in IDEs",
                    category=MemoryCategory.preference,
                    subject="IDE theme",
                    normalized_subject="ide theme",
                    operation_hint="new",
                )
            ],
            SourceIds(message_id=new_id("msg"), conversation_id=new_id("conv")),
            repository=repo,
        )
        assert u2_summary.created == 1
        u2_items, _ = list_user_memories(user_2, repository=repo)
        created_ids_u2.extend(m.memory_id for m in u2_items)

        assert repo.get(user_2, commitment_mem.memory_id) is None
        assert update_user_memory(user_2, commitment_mem.memory_id, content="hack", repository=repo) is None
        assert delete_user_memory(user_2, commitment_mem.memory_id, repository=repo) is False
        print("[verify_graph] Step 7 OK: User isolation enforced across get/list/update/delete/retrieve.")

        rels = repo.list_relationships(user_1, limit=100)
        assert len(rels) >= 1
        deleted_ok = delete_user_memory(user_1, commitment_mem.memory_id, repository=repo)
        assert deleted_ok is True
        remaining, rem_total = list_user_memories(user_1, repository=repo)
        assert rem_total == 2 and all(m.memory_id != commitment_mem.memory_id for m in remaining)
        print("[verify_graph] Step 8 OK: Safe delete removed memory and its edges without affecting other records.")

        print(
            "\n[verify_graph] SUCCESS: All live FalkorDB graph verification checks passed!\n"
            + json.dumps(
                {
                    "status": "passed",
                    "host": host,
                    "port": port,
                    "graph_name": graph_name,
                    "verified_users": [user_1, user_2],
                },
                indent=2,
            )
        )
        return 0
    finally:
        if cleanup:
            for mid in set(created_ids_u1):
                try:
                    repo.delete(user_1, mid)
                except Exception:  # noqa: BLE001
                    pass
            for mid in set(created_ids_u2):
                try:
                    repo.delete(user_2, mid)
                except Exception:  # noqa: BLE001
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MemoryMate AI FalkorDB graph layer.")
    parser.add_argument("--host", default=os.getenv("FALKORDB_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FALKORDB_PORT", "6379")))
    parser.add_argument("--password", default=os.getenv("FALKORDB_PASSWORD") or None)
    parser.add_argument("--graph", default=os.getenv("FALKORDB_GRAPH_NAME", "memorymate"))
    parser.add_argument("--user", default=os.getenv("DEMO_USER_ID", "demo-user-1"))
    parser.add_argument("--no-cleanup", action="store_true", help="Keep verification records in graph")
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print redis-cli / FalkorDB inspection commands and exit",
    )
    args = parser.parse_args(argv)

    if args.print_commands:
        print_inspection_commands(args.host, args.port, args.graph, args.user)
        return 0

    return run_live_verification(
        host=args.host,
        port=args.port,
        password=args.password,
        graph_name=args.graph,
        cleanup=not args.no_cleanup,
    )


if __name__ == "__main__":
    raise SystemExit(main())
