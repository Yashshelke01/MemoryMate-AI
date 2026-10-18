"""Memory persistence, normalization, duplicate detection, correction, and
relationship linking service (PROJECT_CONTRACT.md sections 2, 3, 5, 6, 8).

All database access is delegated to ``GraphRepository``; no Cypher queries
live in this module.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Mapping, Sequence

from app.db.falkordb_client import resolve_repository
from app.models.contracts import (
    MemoryCategory,
    MemoryOperationSummary,
    MemoryRecord,
    ProposedFact,
    SourceIds,
)
from app.utils import new_id, normalize_subject, utc_now_iso

_MEMORY_ID_NAMESPACE = uuid.UUID("7f8d3b0e-9c42-4c1a-9a3f-1e5b8d2c6a90")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")

_CORRECTION_CUE_RE = re.compile(
    r"\b(now|instead|actually|changed|change|updated|update|no longer|"
    r"used to|switched|switch|rather than|anymore|correct|correction)\b",
    re.IGNORECASE,
)

_SUPPORTING_CATEGORIES = frozenset(
    {
        MemoryCategory.skill.value,
        MemoryCategory.commitment.value,
        MemoryCategory.task.value,
        MemoryCategory.decision.value,
        MemoryCategory.preference.value,
    }
)
_ANCHOR_CATEGORIES = frozenset(
    {
        MemoryCategory.goal.value,
        MemoryCategory.project.value,
    }
)

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "currently",
        "day", "each", "every", "for", "from", "has", "have", "i", "in", "is",
        "it", "my", "of", "on", "one", "or", "that", "the", "this", "to",
        "want", "wants", "with", "would",
    }
)


def normalize_content(text: str) -> str:
    """Normalize memory content for deterministic duplicate comparison."""
    lowered = _NON_ALNUM_RE.sub(" ", text.strip().lower())
    return _WS_RE.sub(" ", lowered).strip()


def normalize_subject_key(subject: str) -> str:
    """Normalize a subject into a lowercase matching key."""
    cleaned = _NON_ALNUM_RE.sub(" ", normalize_subject(subject))
    return _WS_RE.sub(" ", cleaned).strip() or normalize_subject(subject)


def subject_tokens(text: str) -> set[str]:
    """Extract significant lowercase alphanumeric tokens from a subject or content string."""
    norm = normalize_content(text)
    return {t for t in norm.split() if len(t) >= 2 and t not in _STOPWORDS}


def stable_memory_id(
    user_id: str,
    source_message_id: str | None,
    category: str,
    normalized_subject: str,
    content: str,
) -> str:
    """Generate a deterministic ``mem_<uuid>`` ID for retry-safe writes."""
    if not source_message_id:
        return new_id("mem")
    seed = f"{user_id}|{source_message_id}|{category}|{normalized_subject}|{normalize_content(content)}"
    return f"mem_{uuid.uuid5(_MEMORY_ID_NAMESPACE, seed)}"


def has_correction_cues(fact: ProposedFact) -> bool:
    """Check whether a ProposedFact carries explicit correction cues."""
    if fact.operation_hint == "correction":
        return True
    combined = f"{fact.content} {fact.source_quote or ''}"
    return bool(_CORRECTION_CUE_RE.search(combined))


def _find_matching_active_memories(
    repo: Any,
    user_id: str,
    fact: ProposedFact,
) -> list[dict[str, Any]]:
    """Find active memories for ``user_id`` that match ``fact`` by subject and category."""
    cat_val = fact.category.value if hasattr(fact.category, "value") else str(fact.category)
    norm_subj = normalize_subject(fact.normalized_subject or fact.subject)
    norm_key = normalize_subject_key(norm_subj)

    candidates: list[dict[str, Any]] = []
    if hasattr(repo, "find_by_subject"):
        exact = repo.find_by_subject(user_id, norm_subj, category=cat_val)
        candidates.extend(exact)
        if not candidates and has_correction_cues(fact):
            candidates.extend(repo.find_by_subject(user_id, norm_subj, category=None))

    if not candidates:
        all_active, _ = repo.list(user_id, 200, 0)
        for rec in all_active:
            if rec.get("user_id") != user_id or rec.get("status") != "active":
                continue
            rec_cat = rec.get("category")
            rec_cat_val = rec_cat.value if hasattr(rec_cat, "value") else str(rec_cat)
            rec_subj = normalize_subject(str(rec.get("normalized_subject") or rec.get("subject") or ""))
            rec_key = normalize_subject_key(rec_subj)

            if rec_cat_val == cat_val and (rec_subj == norm_subj or rec_key == norm_key):
                candidates.append(dict(rec))
            elif (
                rec_cat_val == cat_val
                and has_correction_cues(fact)
                and subject_tokens(rec_subj)
                and subject_tokens(rec_subj) == subject_tokens(norm_subj)
            ):
                candidates.append(dict(rec))

    return candidates


def _build_memory_record_dict(
    user_id: str,
    fact: ProposedFact,
    source_ids: SourceIds,
    *,
    now_iso: str,
    supersedes_memory_id: str | None = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    cat_val = fact.category.value if hasattr(fact.category, "value") else str(fact.category)
    norm_subj = normalize_subject(fact.normalized_subject or fact.subject)
    mem_id = memory_id or stable_memory_id(
        user_id=user_id,
        source_message_id=source_ids.message_id,
        category=cat_val,
        normalized_subject=norm_subj,
        content=fact.content,
    )
    source_text = (fact.source_quote or fact.content)[:500]
    return {
        "memory_id": mem_id,
        "user_id": user_id,
        "content": fact.content.strip(),
        "category": cat_val,
        "subject": fact.subject.strip(),
        "normalized_subject": norm_subj,
        "created_at": now_iso,
        "updated_at": now_iso,
        "source_message_id": source_ids.message_id,
        "source_conversation_id": source_ids.conversation_id,
        "provenance": {
            "kind": "user_statement",
            "source_text": source_text,
            "supersedes_memory_id": supersedes_memory_id,
        },
        "status": "active",
    }


def _supersede_and_create(
    repo: Any,
    user_id: str,
    old_memory: Mapping[str, Any],
    new_record: dict[str, Any],
) -> dict[str, Any]:
    """Supersede ``old_memory`` and persist ``new_record``."""
    old_id = str(old_memory["memory_id"])
    new_record["provenance"]["supersedes_memory_id"] = old_id

    if hasattr(repo, "supersede"):
        created = repo.supersede(user_id, old_id, new_record)
        if created is not None:
            return dict(created)

    rows = getattr(repo, "rows", None)
    if isinstance(rows, dict) and old_id in rows and rows[old_id].get("user_id") == user_id:
        rows[old_id]["status"] = "superseded"
        rows[old_id]["updated_at"] = new_record["updated_at"]
    created = repo.create(new_record)
    return dict(created)


def _derive_relationship_reason(
    m1: Mapping[str, Any], m2: Mapping[str, Any]
) -> tuple[str, str, str] | None:
    """Determine if two active memories of the same user should be linked via RELATED_TO."""
    id1, id2 = str(m1["memory_id"]), str(m2["memory_id"])
    if id1 == id2 or m1.get("user_id") != m2.get("user_id"):
        return None
    if m1.get("status") != "active" or m2.get("status") != "active":
        return None

    cat1 = m1["category"].value if hasattr(m1["category"], "value") else str(m1["category"])
    cat2 = m2["category"].value if hasattr(m2["category"], "value") else str(m2["category"])
    subj1 = str(m1.get("subject") or "")
    subj2 = str(m2.get("subject") or "")

    if cat1 in _SUPPORTING_CATEGORIES and cat2 in _ANCHOR_CATEGORIES:
        reason = f"supports the {cat2} ({subj2}) by identifying the user's {cat1} ({subj1})"
        return (id1, id2, reason)
    if cat2 in _SUPPORTING_CATEGORIES and cat1 in _ANCHOR_CATEGORIES:
        reason = f"supports the {cat1} ({subj1}) by identifying the user's {cat2} ({subj2})"
        return (id2, id1, reason)

    if cat1 == MemoryCategory.project.value and cat2 == MemoryCategory.goal.value:
        return (id1, id2, f"connects project ({subj1}) to goal ({subj2})")
    if cat2 == MemoryCategory.project.value and cat1 == MemoryCategory.goal.value:
        return (id2, id1, f"connects project ({subj2}) to goal ({subj1})")

    tokens1 = subject_tokens(f"{subj1} {m1.get('content', '')}")
    tokens2 = subject_tokens(f"{subj2} {m2.get('content', '')}")
    shared = sorted(tokens1 & tokens2)
    if shared:
        src, tgt = (id1, id2) if id1 < id2 else (id2, id1)
        return (src, tgt, f"related by shared topic: {', '.join(shared[:3])}")

    return None


def _link_related_memories(
    repo: Any,
    user_id: str,
    newly_created: Sequence[Mapping[str, Any]],
) -> None:
    """Create bounded, meaningful RELATED_TO edges for newly saved memories."""
    if not newly_created:
        return
    try:
        active_memories, _ = repo.list(user_id, 50, 0)
    except Exception:  # noqa: BLE001
        return

    create_rel = getattr(repo, "create_relationship", None)
    rel_list = getattr(repo, "relationships", None)

    seen_pairs: set[tuple[str, str]] = set()
    for new_mem in newly_created:
        for other in active_memories:
            rel_info = _derive_relationship_reason(new_mem, other)
            if rel_info is None:
                continue
            src_id, tgt_id, reason = rel_info
            if (src_id, tgt_id) in seen_pairs:
                continue
            seen_pairs.add((src_id, tgt_id))
            if callable(create_rel):
                create_rel(user_id, src_id, tgt_id, reason=reason)
            elif isinstance(rel_list, list):
                if not any(
                    e.get("source") == src_id and e.get("target") == tgt_id for e in rel_list
                ):
                    rel_list.append({"source": src_id, "target": tgt_id, "reason": reason})


def upsert_memories(
    user_id: str,
    proposed_facts: Sequence[ProposedFact | Mapping[str, Any]],
    source_ids: SourceIds | Mapping[str, Any],
    *,
    repository: Any | None = None,
) -> MemoryOperationSummary:
    """Match, deduplicate, supersede, and persist extracted facts for ``user_id``."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")
    user_id = str(user_id).strip()

    validated_source = (
        source_ids
        if isinstance(source_ids, SourceIds)
        else SourceIds.model_validate(source_ids)
    )
    facts = [
        f if isinstance(f, ProposedFact) else ProposedFact.model_validate(f)
        for f in (proposed_facts or [])
    ]
    if not facts:
        return MemoryOperationSummary(created=0, updated=0, superseded=0, duplicates=0)

    repo = resolve_repository(repository)
    now_iso = utc_now_iso()

    created_count = 0
    updated_count = 0
    superseded_count = 0
    duplicate_count = 0
    persisted_records: list[dict[str, Any]] = []

    batch_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    batch_content_keys: set[tuple[str, str]] = set()
    active_records, _ = repo.list(user_id, 1000, 0)

    for fact in facts:
        cat_val = fact.category.value if hasattr(fact.category, "value") else str(fact.category)
        norm_subj = normalize_subject(fact.normalized_subject or fact.subject)
        norm_content = normalize_content(fact.content)
        batch_key = (cat_val, normalize_subject_key(norm_subj))
        content_key = (cat_val, norm_content)

        # An extractor can return the same source sentence more than once with
        # different subjects (for example, one friendship sentence as both
        # "Sarthak" and "Yash"). A category + exact normalized content is one
        # fact for a single message, regardless of the proposed subject.
        if content_key in batch_content_keys:
            duplicate_count += 1
            continue
        batch_content_keys.add(content_key)

        # Repair older duplicate graph nodes when the same fact is encountered
        # again. Keep the oldest record as the canonical memory and remove only
        # exact-content duplicates in the same category and user scope.
        exact_content_matches = []
        for record in active_records:
            record_category = record.get("category")
            if hasattr(record_category, "value"):
                record_category = record_category.value
            if (
                record.get("user_id") == user_id
                and record.get("status") == "active"
                and str(record_category) == cat_val
                and normalize_content(str(record.get("content") or "")) == norm_content
            ):
                exact_content_matches.append(dict(record))
        if exact_content_matches:
            exact_content_matches.sort(
                key=lambda record: (
                    str(record.get("created_at") or ""),
                    str(record.get("memory_id") or ""),
                )
            )
            for redundant in exact_content_matches[1:]:
                repo.delete(user_id, str(redundant["memory_id"]))
                active_records = [
                    record
                    for record in active_records
                    if str(record.get("memory_id")) != str(redundant["memory_id"])
                ]
            duplicate_count += 1
            continue

        if batch_key in batch_by_key:
            prev_in_batch = batch_by_key[batch_key]
            if normalize_content(prev_in_batch["content"]) == norm_content or fact.operation_hint == "repeat":
                duplicate_count += 1
                continue

        matches = _find_matching_active_memories(repo, user_id, fact)

        exact_dup = next(
            (
                m
                for m in matches
                if normalize_content(str(m.get("content") or "")) == norm_content
            ),
            None,
        )
        if exact_dup is not None or (matches and fact.operation_hint == "repeat"):
            duplicate_count += 1
            continue

        if matches and fact.operation_hint == "conflict":
            continue

        if matches:
            target_old = matches[0]
            new_rec = _build_memory_record_dict(
                user_id,
                fact,
                validated_source,
                now_iso=now_iso,
                supersedes_memory_id=str(target_old["memory_id"]),
            )
            if new_rec["memory_id"] == str(target_old["memory_id"]):
                new_rec["memory_id"] = new_id("mem")
            saved = _supersede_and_create(repo, user_id, target_old, new_rec)
            active_records = [
                record
                for record in active_records
                if str(record.get("memory_id")) != str(target_old["memory_id"])
            ]
            active_records.append(saved)
            superseded_count += 1
            created_count += 1
            batch_by_key[batch_key] = saved
            persisted_records.append(saved)
            continue

        new_rec = _build_memory_record_dict(
            user_id,
            fact,
            validated_source,
            now_iso=now_iso,
        )
        saved = dict(repo.create(new_rec))
        active_records.append(saved)
        created_count += 1
        batch_by_key[batch_key] = saved
        persisted_records.append(saved)

    if persisted_records:
        _link_related_memories(repo, user_id, persisted_records)

    return MemoryOperationSummary(
        created=created_count,
        updated=updated_count,
        superseded=superseded_count,
        duplicates=duplicate_count,
    )


def get_user_memory(
    user_id: str, memory_id: str, *, repository: Any | None = None
) -> MemoryRecord | None:
    """Retrieve a single user-owned memory record by ID."""
    repo = resolve_repository(repository)
    raw = repo.get(user_id, memory_id)
    if raw is None:
        return None
    rec = MemoryRecord.model_validate(raw)
    return rec if rec.user_id == user_id else None


def list_user_memories(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    *,
    repository: Any | None = None,
) -> tuple[list[MemoryRecord], int]:
    """List active memories for ``user_id`` ordered by ``updated_at DESC``."""
    repo = resolve_repository(repository)
    raw_items, total = repo.list(user_id, limit, offset)
    records = [
        MemoryRecord.model_validate(r)
        for r in raw_items
        if r.get("user_id") == user_id and r.get("status") == "active"
    ]
    return records, int(total)


def update_user_memory(
    user_id: str,
    memory_id: str,
    *,
    content: str | None = None,
    category: str | MemoryCategory | None = None,
    subject: str | None = None,
    repository: Any | None = None,
) -> MemoryRecord | None:
    """Update an active user-owned memory in-place (preserving created_at and provenance)."""
    repo = resolve_repository(repository)
    existing_raw = repo.get(user_id, memory_id)
    if existing_raw is None:
        return None
    existing = MemoryRecord.model_validate(existing_raw)
    if existing.user_id != user_id or existing.status != "active":
        return None

    new_content = content.strip() if content is not None else existing.content
    new_cat = category if category is not None else existing.category
    new_cat_val = new_cat.value if hasattr(new_cat, "value") else str(new_cat)
    new_subject = subject.strip() if subject is not None else existing.subject
    new_norm_subject = normalize_subject(new_subject)

    updated_raw = repo.update(
        user_id,
        memory_id,
        content=new_content,
        category=new_cat_val,
        subject=new_subject,
        normalized_subject=new_norm_subject,
        updated_at=utc_now_iso(),
    )
    if updated_raw is None:
        return None
    return MemoryRecord.model_validate(updated_raw)


def delete_user_memory(
    user_id: str, memory_id: str, *, repository: Any | None = None
) -> bool:
    """Safely delete a user-owned memory and its RELATED_TO edges."""
    repo = resolve_repository(repository)
    return bool(repo.delete(user_id, memory_id))
