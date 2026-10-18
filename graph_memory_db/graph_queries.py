"""Parameterized OpenCypher queries for the MemoryMate AI FalkorDB graph layer.

All queries follow PROJECT_CONTRACT.md sections 2, 3, and 6:
- Two node labels: ``User {user_id}`` and ``Memory {...}``.
- Two relationship types:
  - ``(u:User)-[:HAS_MEMORY]->(m:Memory)``
  - ``(m1:Memory)-[:RELATED_TO {reason}]->(m2:Memory)``
- Every value is passed as a ``$parameter``; user input is never interpolated
  into Cypher text.
- Because FalkorDB node properties must be scalar/array values and cannot be
  maps or ``null`` (https://docs.falkordb.com/datatypes), ``provenance`` is
  stored as a JSON string and optional string fields (``source_message_id``,
  ``source_conversation_id``) are stored as ``""`` when absent.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Health & optional indexing queries
# ---------------------------------------------------------------------------

HEALTH_CHECK_QUERY = "RETURN 1 AS ok"

INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX FOR (u:User) ON (u.user_id)",
    "CREATE INDEX FOR (m:Memory) ON (m.memory_id)",
    "CREATE INDEX FOR (m:Memory) ON (m.user_id)",
    "CREATE INDEX FOR (m:Memory) ON (m.normalized_subject)",
)

# ---------------------------------------------------------------------------
# User & Memory CRUD queries (all user-scoped and parameterized)
# ---------------------------------------------------------------------------

# Separate MERGE clauses prevent duplicate endpoint nodes when a path is partially
# matched (https://docs.falkordb.com/cypher/merge).
# The WHERE clause ensures a memory_id owned by another user is never linked.
CREATE_MEMORY_QUERY = """
MERGE (u:User {user_id: $user_id})
MERGE (m:Memory {memory_id: $memory_id})
ON CREATE SET
  m.user_id = $user_id,
  m.content = $content,
  m.category = $category,
  m.subject = $subject,
  m.normalized_subject = $normalized_subject,
  m.created_at = $created_at,
  m.updated_at = $updated_at,
  m.source_message_id = $source_message_id,
  m.source_conversation_id = $source_conversation_id,
  m.provenance = $provenance,
  m.status = $status
WITH u, m
WHERE m.user_id = $user_id
MERGE (u)-[:HAS_MEMORY]->(m)
RETURN m
""".strip()

GET_MEMORY_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
WHERE m.user_id = $user_id
RETURN m
LIMIT 1
""".strip()

COUNT_ACTIVE_MEMORIES_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.user_id = $user_id AND m.status = 'active'
RETURN count(m) AS total
""".strip()

LIST_ACTIVE_MEMORIES_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.user_id = $user_id AND m.status = 'active'
RETURN m
ORDER BY m.updated_at DESC, m.memory_id ASC
SKIP $offset
LIMIT $limit
""".strip()

FIND_ACTIVE_BY_SUBJECT_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.user_id = $user_id
  AND m.status = 'active'
  AND m.normalized_subject = $normalized_subject
  AND ($category = '' OR m.category = $category)
RETURN m
ORDER BY m.updated_at DESC, m.memory_id ASC
LIMIT $limit
""".strip()

UPDATE_MEMORY_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
WHERE m.user_id = $user_id AND m.status = 'active'
SET m.content = $content,
    m.category = $category,
    m.subject = $subject,
    m.normalized_subject = $normalized_subject,
    m.updated_at = $updated_at
RETURN m
""".strip()

# Conversational correction: atomically marks the old owned active memory as
# 'superseded' and creates the replacement active memory with provenance linking
# supersedes_memory_id in a single GRAPH.QUERY execution.
SUPERSEDE_MEMORY_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(old:Memory {memory_id: $old_memory_id})
WHERE old.user_id = $user_id AND old.status = 'active'
SET old.status = 'superseded',
    old.updated_at = $updated_at
MERGE (new_m:Memory {memory_id: $memory_id})
ON CREATE SET
  new_m.user_id = $user_id,
  new_m.content = $content,
  new_m.category = $category,
  new_m.subject = $subject,
  new_m.normalized_subject = $normalized_subject,
  new_m.created_at = $created_at,
  new_m.updated_at = $updated_at,
  new_m.source_message_id = $source_message_id,
  new_m.source_conversation_id = $source_conversation_id,
  new_m.provenance = $provenance,
  new_m.status = 'active'
WITH u, old, new_m
WHERE new_m.user_id = $user_id
MERGE (u)-[:HAS_MEMORY]->(new_m)
RETURN new_m, old
""".strip()

# Safe delete: deletes only the user-owned memory node and its RELATED_TO edges.
# Never deletes the User node or any other user's memories.
DELETE_MEMORY_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
WHERE m.user_id = $user_id
OPTIONAL MATCH (m)-[r:RELATED_TO]-()
DELETE r
WITH DISTINCT m
DETACH DELETE m
RETURN count(m) AS deleted
""".strip()

# ---------------------------------------------------------------------------
# Retrieval & bounded relationship queries
# ---------------------------------------------------------------------------

# Single-term parameterized keyword search (PROJECT_CONTRACT.md section 3).
SEARCH_MEMORIES_BY_TERM_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.user_id = $user_id
  AND m.status = 'active'
  AND (
    toLower(m.content) CONTAINS toLower($term)
    OR toLower(m.subject) CONTAINS toLower($term)
    OR m.normalized_subject CONTAINS toLower($term)
    OR toLower(m.category) = toLower($term)
  )
RETURN m
ORDER BY m.updated_at DESC, m.memory_id ASC
LIMIT $limit
""".strip()

# Multi-term parameterized keyword search using UNWIND over a bounded list.
SEARCH_MEMORIES_BY_TERMS_QUERY = """
UNWIND $terms AS term
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.user_id = $user_id
  AND m.status = 'active'
  AND (
    toLower(m.content) CONTAINS toLower(term)
    OR toLower(m.subject) CONTAINS toLower(term)
    OR m.normalized_subject CONTAINS toLower(term)
    OR toLower(m.category) = toLower(term)
  )
RETURN DISTINCT m
ORDER BY m.updated_at DESC, m.memory_id ASC
LIMIT $limit
""".strip()

# Bounded 1-hop relationship expansion restricted to active memories owned by
# the exact same user (PROJECT_CONTRACT.md section 3).
RELATED_MEMORIES_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
WHERE m.user_id = $user_id AND m.status = 'active'
MATCH (m)-[r:RELATED_TO]-(related:Memory)<-[:HAS_MEMORY]-(u)
WHERE related.user_id = $user_id
  AND related.status = 'active'
  AND related.memory_id <> m.memory_id
RETURN DISTINCT related, r.reason AS relationship
ORDER BY related.updated_at DESC, related.memory_id ASC
LIMIT $limit
""".strip()

# Create/merge an explicit RELATED_TO edge between two active memories owned
# by the same user.
CREATE_RELATED_TO_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m1:Memory {memory_id: $source_id})
MATCH (u)-[:HAS_MEMORY]->(m2:Memory {memory_id: $target_id})
WHERE m1.user_id = $user_id
  AND m2.user_id = $user_id
  AND m1.status = 'active'
  AND m2.status = 'active'
  AND m1.memory_id <> m2.memory_id
MERGE (m1)-[r:RELATED_TO]->(m2)
SET r.reason = $reason
RETURN count(r) AS created
""".strip()

# Retrieve RELATED_TO edges among active memories belonging to a single user
# for GET /graph/{user_id}.
LIST_RELATIONSHIPS_QUERY = """
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m1:Memory)-[r:RELATED_TO]->(m2:Memory)<-[:HAS_MEMORY]-(u)
WHERE m1.user_id = $user_id
  AND m2.user_id = $user_id
  AND m1.status = 'active'
  AND m2.status = 'active'
RETURN m1.memory_id AS source, m2.memory_id AS target, r.reason AS reason
ORDER BY m1.memory_id ASC, m2.memory_id ASC
LIMIT $limit
""".strip()


# ---------------------------------------------------------------------------
# Parameter & provenance serialization helpers
# ---------------------------------------------------------------------------


def serialize_provenance(provenance: Mapping[str, Any] | str | None) -> str:
    """Serialize provenance to a canonical JSON string for FalkorDB storage."""
    if isinstance(provenance, str):
        try:
            parsed = json.loads(provenance)
            if isinstance(parsed, dict):
                provenance = parsed
            else:
                provenance = {}
        except ValueError:
            provenance = {}
    elif isinstance(provenance, Mapping):
        provenance = dict(provenance)
    else:
        provenance = {}

    normalized = {
        "kind": str(provenance.get("kind") or "user_statement"),
        "source_text": provenance.get("source_text"),
        "supersedes_memory_id": provenance.get("supersedes_memory_id"),
    }
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def deserialize_provenance(raw: Any) -> dict[str, Any]:
    """Deserialize provenance from FalkorDB JSON text or dict into a dict."""
    if isinstance(raw, Mapping):
        data = dict(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            data = {}
    else:
        data = {}

    return {
        "kind": str(data.get("kind") or "user_statement"),
        "source_text": data.get("source_text"),
        "supersedes_memory_id": data.get("supersedes_memory_id"),
    }


def build_memory_write_params(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build scalar-only Cypher parameters for creating a Memory node."""
    category = record["category"]
    if hasattr(category, "value"):
        category = category.value
    status = str(record.get("status") or "active")
    if status not in ("active", "superseded"):
        raise ValueError(f"Invalid memory status: {status!r}")

    return {
        "memory_id": str(record["memory_id"]),
        "user_id": str(record["user_id"]),
        "content": str(record["content"]),
        "category": str(category),
        "subject": str(record["subject"]),
        "normalized_subject": str(record.get("normalized_subject") or str(record["subject"]).strip().lower()),
        "created_at": str(record["created_at"]),
        "updated_at": str(record["updated_at"]),
        "source_message_id": str(record.get("source_message_id") or ""),
        "source_conversation_id": str(record.get("source_conversation_id") or ""),
        "provenance": serialize_provenance(record.get("provenance")),
        "status": status,
    }


def validate_cypher_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate that all parameter keys and values are safe scalar/list types."""
    if not params:
        return {}
    clean: dict[str, Any] = {}
    for key, val in params.items():
        if not isinstance(key, str) or not _PARAM_NAME_RE.match(key):
            raise ValueError(f"Invalid Cypher parameter name: {key!r}")
        if isinstance(val, (str, int, float, bool)):
            clean[key] = val
        elif isinstance(val, Sequence) and not isinstance(val, (bytes, bytearray)):
            items = list(val)
            if not all(isinstance(x, (str, int, float, bool)) for x in items):
                raise ValueError(f"Parameter {key!r} list contains non-scalar elements")
            clean[key] = items
        else:
            raise ValueError(
                f"Unsupported Cypher parameter type for {key!r}: {type(val).__name__}"
            )
    return clean