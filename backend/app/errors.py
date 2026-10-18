"""Stable error type and JSON shape: {"error": {"code", "message", "details"?}}."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}


# component name -> (error code, safe public message). Messages never include
# exception text, Cypher, credentials or provider details.
COMPONENT_ERRORS: dict[str, tuple[str, str]] = {
    "repository": ("database_unavailable", "The memory database is unavailable."),
    "extract_facts": ("extraction_unavailable", "Memory extraction is unavailable."),
    "upsert_memories": ("persistence_unavailable", "Saving memories failed."),
    "retrieve_memories": ("retrieval_unavailable", "Retrieving memories failed."),
    "build_context": ("generation_unavailable", "Answer generation is unavailable."),
    "generate_answer": ("generation_unavailable", "Answer generation is unavailable."),
}


def component_error(component: str, details: dict[str, Any] | None = None) -> AppError:
    code, message = COMPONENT_ERRORS.get(
        component, ("dependency_unavailable", "A required component is unavailable.")
    )
    return AppError(503, code, message, details)


def memory_not_found() -> AppError:
    # Identical for missing and non-owned records (no ownership leak).
    return AppError(404, "memory_not_found", "Memory not found.")
