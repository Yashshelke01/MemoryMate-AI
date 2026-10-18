"""Dependency wiring for modules developed separately from the API layer.

The registry resolves each collaborator lazily (so the API can start, and
report honestly, even when a module or FalkorDB is not ready) and retries a
failed resolution on the next request. Tests inject fakes via ``overrides``.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
from typing import Any, Callable

from app.config import Settings
from app.errors import component_error

logger = logging.getLogger(__name__)

# component -> ordered (module, attribute) candidates
_FUNCTION_SOURCES: dict[str, list[tuple[str, str]]] = {
    "extract_facts": [("app.services.memory_extractor", "extract_facts")],
    "upsert_memories": [("app.services.memory_service", "upsert_memories")],
    "retrieve_memories": [("app.services.retrieval_service", "retrieve_memories")],
    "build_context": [
        ("app.services.retrieval_service", "build_context"),
        ("app.services.llm_service", "build_context"),
    ],
    "generate_answer": [("app.services.llm_service", "generate_answer")],
}

OPTIONAL = {"llm_is_configured"}


class ServiceRegistry:
    def __init__(self, settings: Settings, overrides: dict[str, Any] | None = None) -> None:
        self._settings = settings
        self._cache: dict[str, Any] = dict(overrides or {})
        self._lock = threading.Lock()

    # -- public ---------------------------------------------------------------
    def get(self, name: str) -> Any:
        """Return the component or raise a 503 AppError."""
        obj = self.get_optional(name)
        if obj is None:
            raise component_error(name)
        return obj

    def get_optional(self, name: str) -> Any | None:
        if name in self._cache:
            return self._cache[name]
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            try:
                obj = self._load(name)
            except Exception as exc:  # noqa: BLE001 - reported, never exposed to clients
                logger.warning("Component %r unavailable: %s", name, type(exc).__name__)
                return None
            if obj is not None:
                self._cache[name] = obj
            return obj

    # -- loaders --------------------------------------------------------------
    def _load(self, name: str) -> Any | None:
        if name == "repository":
            return self._load_repository()
        if name == "llm_is_configured":
            try:
                mod = importlib.import_module("app.services.llm_service")
            except ModuleNotFoundError:
                return None
            fn = getattr(mod, "is_configured", None)
            return fn if callable(fn) else None
        for module_name, attr in _FUNCTION_SOURCES.get(name, []):
            try:
                mod = importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name == module_name:  # module itself not written yet
                    continue
                raise
            fn = getattr(mod, attr, None)
            if callable(fn):
                return fn
        return None

    def _load_repository(self) -> Any | None:
        try:
            mod = importlib.import_module("app.db.falkordb_client")
        except ModuleNotFoundError as exc:
            if exc.name == "app.db.falkordb_client":
                return None
            raise
        factory: Callable[..., Any] | None = getattr(mod, "get_repository", None)
        if callable(factory):
            return factory()
        cls = getattr(mod, "GraphRepository", None)
        if cls is None:
            return None
        s = self._settings
        candidate = {
            "host": s.falkordb_host,
            "port": s.falkordb_port,
            "password": s.falkordb_password.get_secret_value() if s.falkordb_password else None,
            "graph_name": s.falkordb_graph_name,
            "socket_timeout": s.falkordb_socket_timeout_seconds,
        }
        accepted = inspect.signature(cls).parameters
        return cls(**{k: v for k, v in candidate.items() if k in accepted})
