"""FalkorDB client wrapper and GraphRepository implementation.

Provides the only module allowed to execute Cypher against FalkorDB
(PROJECT_CONTRACT.md section 8). All queries are parameterized and scoped by
``user_id``.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Mapping, Sequence

from app.config import Settings, get_settings
from app.db.graph_queries import (
    COUNT_ACTIVE_MEMORIES_QUERY,
    CREATE_MEMORY_QUERY,
    CREATE_RELATED_TO_QUERY,
    DELETE_MEMORY_QUERY,
    FIND_ACTIVE_BY_SUBJECT_QUERY,
    GET_MEMORY_QUERY,
    HEALTH_CHECK_QUERY,
    INDEX_QUERIES,
    LIST_ACTIVE_MEMORIES_QUERY,
    LIST_RELATIONSHIPS_QUERY,
    RELATED_MEMORIES_QUERY,
    SEARCH_MEMORIES_BY_TERM_QUERY,
    SEARCH_MEMORIES_BY_TERMS_QUERY,
    SUPERSEDE_MEMORY_QUERY,
    UPDATE_MEMORY_QUERY,
    build_memory_write_params,
    deserialize_provenance,
    validate_cypher_params,
)

logger = logging.getLogger(__name__)

_REQUIRED_MEMORY_FIELDS = (
    "memory_id",
    "user_id",
    "content",
    "category",
    "subject",
    "normalized_subject",
    "created_at",
    "updated_at",
    "status",
)

_default_repository: Any | None = None


class GraphDatabaseError(RuntimeError):
    """Raised when a FalkorDB operation or connection fails."""


class GraphRepository:
    """FalkorDB-backed repository implementing ``app.interfaces.GraphRepository``."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        graph_name: str = "memorymate",
        socket_timeout: float = 5.0,
        *,
        client: Any | None = None,
        graph: Any | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self._password = password or None
        self.graph_name = graph_name
        self.socket_timeout = float(socket_timeout)
        self._client = client
        self._graph = graph

    def _get_graph(self) -> Any:
        if self._graph is not None:
            return self._graph
        if self._client is None:
            try:
                from falkordb import FalkorDB  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise GraphDatabaseError("The FalkorDB Python client is not installed.") from exc

            kwargs: dict[str, Any] = {
                "host": self.host,
                "port": self.port,
                "socket_timeout": self.socket_timeout,
                "socket_connect_timeout": self.socket_timeout,
            }
            if self._password:
                kwargs["password"] = self._password

            try:
                accepted = inspect.signature(FalkorDB).parameters
                filtered = {
                    k: v
                    for k, v in kwargs.items()
                    if k in accepted or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in accepted.values()
                    )
                }
                self._client = FalkorDB(**filtered)
            except Exception as exc:  # noqa: BLE001
                raise GraphDatabaseError("Failed to initialize FalkorDB client.") from exc

        try:
            self._graph = self._client.select_graph(self.graph_name)
        except Exception as exc:  # noqa: BLE001
            raise GraphDatabaseError("Failed to select FalkorDB graph.") from exc
        return self._graph

    def _execute(
        self,
        query: str,
        params: Mapping[str, Any] | None = None,
        *,
        read_only: bool = False,
    ) -> Any:
        clean_params = validate_cypher_params(params)
        graph = self._get_graph()
        timeout_ms = max(int(self.socket_timeout * 1000), 100)
        method_name = "ro_query" if read_only and hasattr(graph, "ro_query") else "query"
        method = getattr(graph, method_name)

        try:
            sig = inspect.signature(method).parameters
            if "timeout" in sig:
                return method(query, clean_params, timeout=timeout_ms)
            return method(query, clean_params)
        except TypeError:
            if clean_params:
                return method(query, clean_params)
            return method(query)
        except Exception as exc:  # noqa: BLE001
            raise GraphDatabaseError(f"FalkorDB query failed ({type(exc).__name__}).") from exc

    @staticmethod
    def _rows(result: Any) -> list[list[Any]]:
        if result is None:
            return []
        rs = getattr(result, "result_set", None)
        if rs is None and isinstance(result, Mapping):
            rs = result.get("result_set", [])
        return list(rs) if rs else []

    @staticmethod
    def _extract_node_props(cell: Any) -> dict[str, Any]:
        if hasattr(cell, "properties") and isinstance(cell.properties, Mapping):
            return dict(cell.properties)
        if isinstance(cell, Mapping):
            if "properties" in cell and isinstance(cell["properties"], Mapping):
                return dict(cell["properties"])
            return dict(cell)
        raise GraphDatabaseError("Unexpected node representation in FalkorDB result set.")

    @classmethod
    def _decode_memory_node(cls, cell: Any) -> dict[str, Any]:
        props = cls._extract_node_props(cell)
        for field in _REQUIRED_MEMORY_FIELDS:
            if field not in props or props[field] is None or str(props[field]) == "":
                raise GraphDatabaseError(f"Stored Memory node is missing required property {field!r}.")

        src_msg = props.get("source_message_id")
        src_conv = props.get("source_conversation_id")
        return {
            "memory_id": str(props["memory_id"]),
            "user_id": str(props["user_id"]),
            "content": str(props["content"]),
            "category": str(props["category"]),
            "subject": str(props["subject"]),
            "normalized_subject": str(props["normalized_subject"]),
            "created_at": str(props["created_at"]),
            "updated_at": str(props["updated_at"]),
            "source_message_id": str(src_msg) if src_msg not in (None, "") else None,
            "source_conversation_id": str(src_conv) if src_conv not in (None, "") else None,
            "provenance": deserialize_provenance(props.get("provenance")),
            "status": str(props["status"]),
        }

    def ensure_indexes(self) -> None:
        """Create optional property indexes if not already present."""
        for idx_query in INDEX_QUERIES:
            try:
                self._execute(idx_query, read_only=False)
            except Exception:  # noqa: BLE001
                logger.debug("Index creation skipped or already present for query: %s", idx_query)

    def ping(self) -> bool:
        """Execute a lightweight read query and raise on failure."""
        res = self._execute(HEALTH_CHECK_QUERY, read_only=True)
        rows = self._rows(res)
        if not rows or not rows[0] or int(rows[0][0]) != 1:
            raise GraphDatabaseError("Unexpected health check response from FalkorDB.")
        return True

    def health(self) -> bool:
        """Lightweight read query; returns True when FalkorDB is reachable."""
        try:
            return self.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FalkorDB health check failed: %s", type(exc).__name__)
            return False

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Ensure User node and idempotently create/merge a Memory node."""
        params = build_memory_write_params(record)
        res = self._execute(CREATE_MEMORY_QUERY, params, read_only=False)
        rows = self._rows(res)
        if not rows or not rows[0]:
            raise GraphDatabaseError("Memory creation returned no record (possible memory_id conflict).")
        created = self._decode_memory_node(rows[0][0])
        if created["user_id"] != params["user_id"]:
            raise GraphDatabaseError("Memory ownership mismatch after create.")
        return created

    def get(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        """Return an owned Memory record (any status) or None."""
        if not user_id or not memory_id:
            return None
        res = self._execute(
            GET_MEMORY_QUERY,
            {"user_id": str(user_id), "memory_id": str(memory_id)},
            read_only=True,
        )
        rows = self._rows(res)
        if not rows or not rows[0] or rows[0][0] is None:
            return None
        decoded = self._decode_memory_node(rows[0][0])
        return decoded if decoded["user_id"] == user_id else None

    def list(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """Return active records for ``user_id`` (newest ``updated_at`` first) and total active count."""
        safe_limit = max(1, min(int(limit), 1000))
        safe_offset = max(0, int(offset))

        count_res = self._execute(
            COUNT_ACTIVE_MEMORIES_QUERY,
            {"user_id": str(user_id)},
            read_only=True,
        )
        count_rows = self._rows(count_res)
        total = int(count_rows[0][0]) if count_rows and count_rows[0] else 0
        if total == 0:
            return [], 0

        list_res = self._execute(
            LIST_ACTIVE_MEMORIES_QUERY,
            {"user_id": str(user_id), "limit": safe_limit, "offset": safe_offset},
            read_only=True,
        )
        items: list[dict[str, Any]] = []
        for row in self._rows(list_res):
            if not row or row[0] is None:
                continue
            rec = self._decode_memory_node(row[0])
            if rec["user_id"] == user_id and rec["status"] == "active":
                items.append(rec)
        return items, total

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
    ) -> dict[str, Any] | None:
        """Update an ACTIVE owned record; returns None if missing, non-owned, or superseded."""
        if not user_id or not memory_id:
            return None
        cat_val = category.value if hasattr(category, "value") else str(category)
        params = {
            "user_id": str(user_id),
            "memory_id": str(memory_id),
            "content": str(content),
            "category": cat_val,
            "subject": str(subject),
            "normalized_subject": str(normalized_subject),
            "updated_at": str(updated_at),
        }
        res = self._execute(UPDATE_MEMORY_QUERY, params, read_only=False)
        rows = self._rows(res)
        if not rows or not rows[0] or rows[0][0] is None:
            return None
        updated = self._decode_memory_node(rows[0][0])
        if updated["user_id"] != user_id or updated["status"] != "active":
            return None
        return updated

    def delete(self, user_id: str, memory_id: str) -> bool:
        """Delete an owned Memory record and its RELATED_TO edges; returns False if not found/owned."""
        if not user_id or not memory_id:
            return False
        res = self._execute(
            DELETE_MEMORY_QUERY,
            {"user_id": str(user_id), "memory_id": str(memory_id)},
            read_only=False,
        )
        rows = self._rows(res)
        deleted_count = int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0
        return deleted_count > 0

    def related(self, user_id: str, memory_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return 1-hop same-user active neighbor memories connected via RELATED_TO."""
        if not user_id or not memory_id:
            return []
        safe_limit = max(1, min(int(limit), 100))
        res = self._execute(
            RELATED_MEMORIES_QUERY,
            {"user_id": str(user_id), "memory_id": str(memory_id), "limit": safe_limit},
            read_only=True,
        )
        neighbors: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._rows(res):
            if not row or row[0] is None:
                continue
            rec = self._decode_memory_node(row[0])
            if rec["user_id"] != user_id or rec["status"] != "active" or rec["memory_id"] == memory_id:
                continue
            if rec["memory_id"] in seen:
                continue
            seen.add(rec["memory_id"])
            reason = row[1] if len(row) > 1 and row[1] else None
            if reason:
                rec["relationship"] = str(reason)
            neighbors.append(rec)
        return neighbors

    def find_by_subject(
        self,
        user_id: str,
        normalized_subject: str,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find active memories for ``user_id`` matching ``normalized_subject`` (and optional ``category``)."""
        cat_str = ""
        if category is not None:
            cat_str = category.value if hasattr(category, "value") else str(category)
        res = self._execute(
            FIND_ACTIVE_BY_SUBJECT_QUERY,
            {
                "user_id": str(user_id),
                "normalized_subject": str(normalized_subject),
                "category": cat_str,
                "limit": max(1, min(int(limit), 100)),
            },
            read_only=True,
        )
        matches: list[dict[str, Any]] = []
        for row in self._rows(res):
            if not row or row[0] is None:
                continue
            rec = self._decode_memory_node(row[0])
            if rec["user_id"] == user_id and rec["status"] == "active":
                matches.append(rec)
        return matches

    def supersede(
        self,
        user_id: str,
        old_memory_id: str,
        new_record: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Atomically mark ``old_memory_id`` as superseded and create ``new_record``."""
        record_copy = dict(new_record)
        prov = deserialize_provenance(record_copy.get("provenance"))
        prov["supersedes_memory_id"] = str(old_memory_id)
        record_copy["provenance"] = prov
        record_copy["user_id"] = str(user_id)
        record_copy["status"] = "active"

        params = build_memory_write_params(record_copy)
        params["old_memory_id"] = str(old_memory_id)

        res = self._execute(SUPERSEDE_MEMORY_QUERY, params, read_only=False)
        rows = self._rows(res)
        if not rows or not rows[0] or rows[0][0] is None:
            return None
        created = self._decode_memory_node(rows[0][0])
        return created if created["user_id"] == user_id else None

    def search_by_term(
        self, user_id: str, term: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search a user's active memories by a single keyword term."""
        cleaned = term.strip()
        if not user_id or not cleaned:
            return []
        res = self._execute(
            SEARCH_MEMORIES_BY_TERM_QUERY,
            {
                "user_id": str(user_id),
                "term": cleaned,
                "limit": max(1, min(int(limit), 100)),
            },
            read_only=True,
        )
        results: list[dict[str, Any]] = []
        for row in self._rows(res):
            if not row or row[0] is None:
                continue
            rec = self._decode_memory_node(row[0])
            if rec["user_id"] == user_id and rec["status"] == "active":
                results.append(rec)
        return results

    def search_by_terms(
        self, user_id: str, terms: Sequence[str], limit: int = 25
    ) -> list[dict[str, Any]]:
        """Search a user's active memories across a bounded list of keyword terms."""
        cleaned_terms = [t.strip() for t in terms if isinstance(t, str) and t.strip()][:10]
        if not user_id or not cleaned_terms:
            return []
        res = self._execute(
            SEARCH_MEMORIES_BY_TERMS_QUERY,
            {
                "user_id": str(user_id),
                "terms": cleaned_terms,
                "limit": max(1, min(int(limit), 100)),
            },
            read_only=True,
        )
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._rows(res):
            if not row or row[0] is None:
                continue
            rec = self._decode_memory_node(row[0])
            if rec["user_id"] == user_id and rec["status"] == "active" and rec["memory_id"] not in seen:
                seen.add(rec["memory_id"])
                results.append(rec)
        return results

    def create_relationship(
        self,
        user_id: str,
        source_memory_id: str,
        target_memory_id: str,
        reason: str = "related memory",
    ) -> bool:
        """Create/merge a RELATED_TO relationship between two active memories owned by ``user_id``."""
        if (
            not user_id
            or not source_memory_id
            or not target_memory_id
            or source_memory_id == target_memory_id
        ):
            return False
        res = self._execute(
            CREATE_RELATED_TO_QUERY,
            {
                "user_id": str(user_id),
                "source_id": str(source_memory_id),
                "target_id": str(target_memory_id),
                "reason": str(reason or "related memory")[:200],
            },
            read_only=False,
        )
        rows = self._rows(res)
        count = int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0
        return count > 0

    def list_relationships(self, user_id: str, limit: int = 200) -> list[dict[str, str]]:
        """Return RELATED_TO edges among ``user_id``'s active memories for ``GET /graph/{user_id}``."""
        if not user_id:
            return []
        safe_limit = max(1, min(int(limit), 1000))
        res = self._execute(
            LIST_RELATIONSHIPS_QUERY,
            {"user_id": str(user_id), "limit": safe_limit},
            read_only=True,
        )
        edges: list[dict[str, str]] = []
        for row in self._rows(res):
            if not row or len(row) < 2 or not row[0] or not row[1]:
                continue
            edge: dict[str, str] = {
                "source": str(row[0]),
                "target": str(row[1]),
            }
            if len(row) > 2 and row[2]:
                edge["reason"] = str(row[2])
            edges.append(edge)
        return edges


def set_default_repository(repository: Any | None) -> None:
    """Set or clear a default repository override (used by tests)."""
    global _default_repository
    _default_repository = repository


def get_repository(
    settings: Settings | None = None,
    *,
    verify: bool = True,
) -> GraphRepository:
    """Construct a ``GraphRepository`` from application settings."""
    if _default_repository is not None:
        return _default_repository

    if settings is None:
        frame = inspect.currentframe()
        try:
            caller = frame.f_back if frame is not None else None
            if caller is not None:
                caller_self = caller.f_locals.get("self")
                caller_settings = getattr(caller_self, "_settings", None)
                if isinstance(caller_settings, Settings):
                    settings = caller_settings
        finally:
            del frame

    s = settings or get_settings()
    password = s.falkordb_password.get_secret_value() if s.falkordb_password else None
    repo = GraphRepository(
        host=s.falkordb_host,
        port=s.falkordb_port,
        password=password,
        graph_name=s.falkordb_graph_name,
        socket_timeout=s.falkordb_socket_timeout_seconds,
    )
    if verify:
        repo.ping()
    return repo


def resolve_repository(repository: Any | None = None) -> Any:
    """Resolve the active ``GraphRepository`` for service-layer functions."""
    if repository is not None:
        return repository
    if _default_repository is not None:
        return _default_repository

    frame = inspect.currentframe()
    try:
        cur = frame.f_back if frame is not None else None
        for _ in range(5):
            if cur is None:
                break
            caller_self = cur.f_locals.get("self")
            reg = getattr(caller_self, "_registry", None)
            if reg is not None and hasattr(reg, "get_optional"):
                repo = reg.get_optional("repository")
                if repo is not None:
                    return repo
            cur = cur.f_back
    finally:
        del frame

    return get_repository(verify=False)