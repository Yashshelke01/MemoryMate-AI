"""Extract explicit, durable facts from one user message."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.models.contracts import ProposedFact
from app.services._llm_provider import request_structured

_FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": ["goal", "skill", "project", "task", "preference", "commitment", "decision", "other"]},
                    "subject": {"type": "string"},
                    "source_quote": {"type": "string"},
                    "operation_hint": {"type": "string", "enum": ["new", "repeat", "correction", "conflict"]},
                },
                "required": ["content", "category", "subject", "source_quote", "operation_hint"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}

_EXTRACTION_SYSTEM = """You extract only useful, explicit, durable personal facts from the user's message.
Return facts only for information likely to help in future conversations: skills being learned, goals, ongoing projects, actionable tasks, stable preferences, commitments/availability, deadlines, important decisions, and explicit stable context about named people in the user's life (such as a friend, roommate, or family member). A direct statement like "My friend is Yash. He is a great cricketer." is useful context and should be saved as one fact with category other and subject Yash. Ignore greetings, opinions with no durable relevance, hypotheticals, and passing details. Do not convert a sentence into a memory merely because it is personal.
Never infer or complete missing details. For maximum auditability, content must be an exact contiguous quote copied from the message, and source_quote must equal content. Subject must also be an exact phrase from the message (for example, a named skill or project). Use the fixed category enum. Use new unless the same fact is explicitly repeated within this message; do not claim knowledge of prior messages, because duplicate detection happens in the persistence layer. Mark correction when the speaker explicitly corrects/replaces earlier information; mark conflict only when they state incompatible information without resolving it. A mentioned future date/deadline is retained only when explicit. Return an empty facts array when nothing durable and supported is present."""


_PERSON_RELATION_PATTERNS = (
    re.compile(
        r"\b(?P<name>[\w][\w'-]*(?:\s+and\s+[\w][\w'-]*){1,2})\s+are\s+my\s+"
        r"(?:friends|roommates|teammates|brothers|sisters|cousins|colleagues|mentors)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy\s+(?:friend|roommate|teammate|brother|sister|cousin|parent|"
        r"mother|father|colleague|mentor)\s+is\s+(?P<name>[\w][\w'-]*"
        r"(?:\s+[\w][\w'-]*){0,2})(?=[,.;!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<name>[\w][\w'-]*(?:\s+[\w][\w'-]*){0,2})\s+is\s+my\s+(?:friend|roommate|"
        r"teammate|brother|sister|cousin|parent|mother|father|colleague|mentor)\b",
        re.IGNORECASE,
    ),
)


def _explicit_person_context(message: str) -> list[ProposedFact]:
    """Save a clearly stated user-person relationship without a provider guess."""
    text = message.strip()
    if not text or len(text) > 500:
        return []
    for pattern in _PERSON_RELATION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = match.group("name").strip(".,!?;:")
        if name.casefold() in {"a", "an", "the", "someone", "somebody"}:
            continue
        return [
            ProposedFact(
                content=text,
                category="other",
                subject=name,
                source_quote=text,
                operation_hint="new",
            )
        ]
    return []


def _validate_result(raw: Any, message: str) -> list[ProposedFact]:
    if not isinstance(raw, dict) or set(raw) != {"facts"} or not isinstance(raw["facts"], list):
        raise ValueError("Extractor output must be an object containing a facts list")
    if len(raw["facts"]) > get_settings().max_facts_per_message:
        raise ValueError("Extractor output exceeds the configured fact limit")

    facts: list[ProposedFact] = []
    message_folded = message.casefold()
    for item in raw["facts"]:
        try:
            fact = ProposedFact.model_validate(item)
        except ValidationError as exc:
            raise ValueError("Extractor returned an invalid fact") from exc
        quote = (fact.source_quote or "").strip()
        if (
            not quote
            or quote.casefold() not in message_folded
            or fact.content != quote
            or fact.subject.casefold() not in message_folded
        ):
            # A paraphrase is not auditable evidence; reject the whole model
            # result so no partial set can be accidentally persisted.
            raise ValueError("Extractor source quote is not present in the user message")
        fact.source_quote = quote
        facts.append(fact)
    return facts


def extract_facts(message: str, user_id: str, conversation_id: str) -> list[ProposedFact]:
    """Return schema-validated facts; identifiers are accepted for interface compatibility.

    Identity and conversation IDs are deliberately not sent to the provider.
    """
    del user_id, conversation_id
    message = message.strip()
    if not message:
        return []
    settings = get_settings()
    if len(message) > settings.max_message_chars:
        raise ValueError("Message exceeds configured maximum length")
    person_context = _explicit_person_context(message)
    if person_context:
        return person_context
    user_payload = json.dumps({"message": message}, ensure_ascii=False)
    result = request_structured(
        system=_EXTRACTION_SYSTEM,
        user=user_payload,
        schema_name="memory_facts",
        schema=_FACT_SCHEMA,
        max_tokens=1800,
    )
    return _validate_result(result, message)
