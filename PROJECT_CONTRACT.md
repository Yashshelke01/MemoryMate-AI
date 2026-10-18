# MemoryMate AI — Implementation Blueprint

This blueprint converts the pasted master specification into shared contracts for a four-person beginner team. It defines the MVP boundaries, data model, API payloads, graph-query responsibilities, module ownership, and acceptance checks. Account and conversation-history requirements were added after the initial MVP contract; the current API details are documented in the backend and frontend READMEs.

## 1. Minimum viable architecture

Build one FastAPI application, one vanilla HTML/CSS/JavaScript frontend, and one authoritative FalkorDB graph. Keep components as Python modules in the same application; do not add microservices, a vector database, or a complex agent framework.

```text
Browser
  └── HTML/CSS/vanilla JS ── JSON/HTTP ── FastAPI
                                         ├── chat orchestration
                                         ├── memory extraction and normalization
                                         ├── retrieval and context building
                                         ├── configurable LLM provider
                                         └── FalkorDB repository ── graph queries
```

**Core flow:** validate request → extract and normalize facts → match existing facts and corrections → persist to FalkorDB → retrieve bounded, user-scoped memories → generate a grounded answer → return evidence and operation counts.

FalkorDB remains the source of truth for saved memories and graph relationships. The frontend may retain the visible current chat in page state, but browser storage must not serve as memory persistence.

## 2. Graph schema and exact memory record

### Canonical MVP schema

Use only two node labels initially:

- `User {user_id}`
- `Memory {memory_id, user_id, content, category, subject, normalized_subject, created_at, updated_at, source_message_id, source_conversation_id, provenance, status}`

Use these relationships:

- `(u:User)-[:HAS_MEMORY]->(m:Memory)` — each active memory belongs to exactly one user.
- `(m1:Memory)-[:RELATED_TO]->(m2:Memory)` — optional, only for an explicitly useful relationship between two memories belonging to the same user.

Store goals, skills, projects, tasks, commitments, preferences, decisions, and other types as `Memory.category` values. Do not add `Goal`, `Skill`, `Project`, or `Task` nodes in the MVP; they add integration work without being necessary for persistent retrieval. If a later graph visualization or retrieval need justifies entity nodes, extend the schema deliberately.

### Memory record contract

```json
{
  "memory_id": "mem_<uuid>",
  "user_id": "demo-user-1",
  "content": "Can study one hour each day",
  "category": "commitment",
  "subject": "daily study availability",
  "normalized_subject": "daily study availability",
  "created_at": "2026-10-17T12:00:00Z",
  "updated_at": "2026-10-17T12:00:00Z",
  "source_message_id": "msg_<uuid>",
  "source_conversation_id": "conv_<uuid>",
  "provenance": {
    "kind": "user_statement",
    "source_text": "I can study one hour every day.",
    "supersedes_memory_id": null
  },
  "status": "active"
}
```

- Generate IDs server-side. Use UUID-based IDs with stable string prefixes such as `mem_`, `msg_`, and `conv_`.
- `user_id` is derived server-side from the authenticated account session. The request body and browser settings cannot choose a memory owner. Historical `demo-user-1` values below are illustrative API examples only.
- `content` is a concise fact supported by the user’s words. Never store model inference as a user statement.
- `category` is a fixed enum for the MVP: `goal`, `skill`, `project`, `task`, `preference`, `commitment`, `decision`, `other`.
- `subject` is a readable entity or topic; `normalized_subject` is a lowercased, whitespace-normalized matching key.
- Use UTC ISO-8601 timestamps. Update `updated_at` when content changes.
- `provenance.kind` is `user_statement` for directly stated information. Keep source text short and only as needed to audit the extraction. Corrections set `supersedes_memory_id` to the prior record ID.
- `status` is `active` or `superseded`. A superseded record stays linked only if that history is useful; retrieval and evidence return active records only.

### Uniqueness and graph consistency

Use `memory_id` for idempotent creation via `MERGE`, and enforce relationship creation with `MERGE`. Avoid depending on database uniqueness constraints until support and syntax are verified for the selected FalkorDB version. The graph repository should first check whether a memory ID exists and use a stable ID for retry-safe writes.

## 3. FalkorDB query responsibilities

The official FalkorDB documentation describes property graphs, OpenCypher, the Python client’s `FalkorDB(host=..., port=...).select_graph(...)` and `graph.query(...)` interface, and parameterized queries in its examples. The Python client documentation and server behavior must still be checked against the version the team installs. The documentation’s simple Python example shows unparameterized `query()`; confirm the Python client’s exact parameter-passing signature before relying on it. Never interpolate user-provided text into Cypher. [FalkorDB official documentation](https://docs.falkordb.com/), [Python client package and examples](https://pypi.org/project/FalkorDB/)

The following are **query shapes**. Before implementation, confirm the syntax and parameter API for the pinned client/server versions. Parameters shown as `$name` are intentional; do not replace them with string formatting.

### Ensure user node and create memory

```cypher
MERGE (u:User {user_id: $user_id})
WITH u
CREATE (m:Memory {
  memory_id: $memory_id,
  user_id: $user_id,
  content: $content,
  category: $category,
  subject: $subject,
  normalized_subject: $normalized_subject,
  created_at: $created_at,
  updated_at: $updated_at,
  source_message_id: $source_message_id,
  source_conversation_id: $source_conversation_id,
  provenance: $provenance,
  status: 'active'
})
CREATE (u)-[:HAS_MEMORY]->(m)
RETURN m
```

The service must ensure it does not create a second memory for a retry. Before creation, look up the same `memory_id`; or use an appropriately verified `MERGE` form keyed by `memory_id`, then set properties only in the create path.

### Retrieve a user’s memories

```cypher
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.status = 'active'
RETURN m
ORDER BY m.updated_at DESC
LIMIT $limit
```

### Keyword retrieval and bounded relationship expansion

First retrieve candidate memories scoped by user. The retrieval service can split the question into a bounded list of terms and issue one parameterized query per term or combine verified query clauses. Confirm the installed FalkorDB version supports the chosen text matching behavior.

```cypher
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.status = 'active'
  AND (m.content CONTAINS $term OR m.subject CONTAINS $term)
RETURN m
LIMIT $limit
```

If related-memory expansion is implemented, restrict it to one hop and ensure expanded memories are owned by the same user:

```cypher
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.memory_id = $memory_id AND m.status = 'active'
OPTIONAL MATCH (m)-[:RELATED_TO]-(related:Memory)
WHERE related.user_id = $user_id AND related.status = 'active'
RETURN m, related
LIMIT $limit
```

The application ranks and deduplicates returned candidates using transparent rules: keyword overlap, category/subject match, and recency. Never return unbounded graph results or send the full graph to the LLM.

### Update and correction

The update endpoint changes the selected record only after matching both memory ID and owning user. For a correction found during extraction, mark the old memory superseded and create the corrected record with provenance linking it to the old ID. Both operations should complete or fail as one logical operation; verify transaction support before assuming atomicity. If the installed interface does not offer a verified transaction mechanism, document the partial-failure risk and use a safe, ordered correction approach.

```cypher
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
WHERE m.status = 'active'
SET m.content = $content,
    m.category = $category,
    m.subject = $subject,
    m.normalized_subject = $normalized_subject,
    m.updated_at = $updated_at
RETURN m
```

For API `PATCH`, the team must choose one rule and keep it consistent: this blueprint recommends editing the existing record, preserving `created_at` and provenance, and updating `updated_at`. For a conversational correction, supersede the old record and create a new one so the source statement and correction remain auditable.

### Safe delete

```cypher
MATCH (u:User {user_id: $user_id})-[:HAS_MEMORY]->(m:Memory {memory_id: $memory_id})
OPTIONAL MATCH (m)-[r:RELATED_TO]-()
DELETE r
DETACH DELETE m
RETURN count(m) AS deleted
```

A missing match returns zero and becomes `404`. Delete only the user-owned memory node and its memory-to-memory edges. Do not delete the `User` node or unrelated nodes. Avoid shared entity nodes in the MVP so deleting one user’s fact cannot remove another user’s data.

### Graph response and health check

`GET /graph/{user_id}` reads the user’s active memories and optional same-user `RELATED_TO` edges, then serializes them as frontend-friendly nodes and edges. The health check executes a lightweight read query against the selected graph and reports whether FalkorDB is reachable.

## 4. API contracts

All requests and responses are JSON. Define Pydantic models, bounded input lengths, explicit enums, predictable errors, and narrow CORS settings. The examples below are normative response shapes.

### `GET /health`

```json
{
  "status": "ok",
  "dependencies": {
    "falkordb": "ok",
    "llm": "configured"
  }
}
```

Use `falkordb: "unavailable"` if its connectivity check fails. For LLM, report configuration or a safe lightweight status; do not make a billable generation call on every health request.

### `POST /chat`

Request:

```json
{
  "message": "What should I focus on this week to reach my goal?",
  "conversation_id": null
}
```

Response:

```json
{
  "conversation_id": "conv_<uuid>",
  "answer": "Based on your stored goal and study commitment, you could make progress on one small Python project feature each day.",
  "memories_used": [
    {
      "memory_id": "mem_<uuid>",
      "content": "Currently learning Python",
      "type": "skill",
      "subject": "Python",
      "updated_at": "2026-10-17T12:00:00Z",
      "relationship": "supports the goal by identifying the current skill"
    }
  ],
  "memory_operations": {
    "created": 0,
    "updated": 0,
    "superseded": 0
  }
}
```

`conversation_id` is optional on input; if omitted or null, create one. If supplied, use it only as conversation context; it is not a user identity or authorization token. `memories_used` contains only actual active database records selected into the LLM context. If no memories are selected, return `[]` and the answer must acknowledge the missing stored information. On extraction or persistence failure, do not report a successful save. On retrieval failure, do not claim the answer is graph-grounded.

### `GET /memories/{user_id}?limit=50&offset=0`

```json
{
  "items": [
    {
      "memory_id": "mem_<uuid>",
      "user_id": "demo-user-1",
      "content": "Can study one hour each day",
      "category": "commitment",
      "subject": "daily study availability",
      "created_at": "2026-10-17T12:00:00Z",
      "updated_at": "2026-10-17T12:00:00Z",
      "provenance": {
        "kind": "user_statement",
        "source_message_id": "msg_<uuid>",
        "supersedes_memory_id": null
      }
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

### `PATCH /memories/{memory_id}`

Request:

```json
{
  "content": "Can study two hours each day",
  "category": "commitment",
  "subject": "daily study availability"
}
```

Response:

```json
{
  "memory": {
    "memory_id": "mem_<uuid>",
    "user_id": "demo-user-1",
    "content": "Can study two hours each day",
    "category": "commitment",
    "subject": "daily study availability",
    "updated_at": "2026-10-17T13:00:00Z"
  }
}
```

### `DELETE /memories/{memory_id}`

Request:

```json
{
}
```

Response:

```json
{
  "deleted": true,
  "memory_id": "mem_<uuid>"
}
```

Return `404` for nonexistent or non-owned records, without revealing whether another user owns the ID.

### `GET /graph/{user_id}`

```json
{
  "nodes": [
    {
      "id": "mem_<uuid>",
      "label": "Currently learning Python",
      "type": "skill"
    }
  ],
  "edges": [
    {
      "source": "user:demo-user-1",
      "target": "mem_<uuid>",
      "type": "HAS_MEMORY"
    }
  ]
}
```

### Status and error conventions

- `400` malformed or semantically invalid request; `422` Pydantic validation failure; `404` missing or non-owned memory; `503` unavailable required dependency; `500` unexpected server failure.
- Return a stable error object, for example `{"error":{"code":"memory_not_found","message":"Memory not found."}}`.
- Never send stack traces, database credentials, raw Cypher errors, or provider secrets to the browser.

## 5. Extraction, duplicate detection, correction, retrieval, and answering

### Extraction result contract

The extraction module accepts the user message plus identifiers and returns zero or more proposed facts:

```json
{
  "facts": [
    {
      "content": "Currently learning Python",
      "category": "skill",
      "subject": "Python",
      "normalized_subject": "python",
      "source_quote": "I'm learning Python.",
      "operation_hint": "new"
    }
  ]
}
```

`operation_hint` is advisory (`new`, `repeat`, `correction`, `conflict`); the memory service makes the final decision. Validate categories and required fields, enforce a maximum fact count and content length, and reject malformed LLM output. If extraction fails, continue only if the requested behavior can be completed honestly; do not fabricate extracted facts or claim they were saved.

### Matching policy

For each proposed fact, compare active memories for that user by `category` and `normalized_subject`.

- Same normalized subject and same meaning: count as duplicate; do not create another record.
- Same subject and explicit correction/change: supersede the previous active record, then create the corrected record with `supersedes_memory_id`.
- Same subject but genuine ambiguity/conflict: do not silently overwrite; preserve the existing value and ask for clarification or store a distinct fact only when clearly appropriate.
- Different subject: create a new memory even if the wording is similar.

Do not make every database operation invoke an LLM. Extraction can classify correction intent once; deterministic matching handles the normal cases.

### Retrieval and answer generation

Retrieve after processing the current message so the response may use any newly saved facts. Scope every candidate to the current user, cap results (for example, 10 memories), and use a bounded relationship expansion (maximum one hop). Build context solely from returned active records and relevant relationship labels.

Send the LLM: system grounding rules, current question, bounded relevant context, and only the minimum recent conversation context needed for follow-up resolution. Treat retrieved content as untrusted data, not instructions. Require the answer to distinguish stored facts from suggestions, acknowledge unknown personal facts, and resolve conflicting memories conservatively.

The evidence list is created from the exact memory objects included in that generation request. Never ask the LLM to invent or return evidence IDs. The backend serializes the memory objects itself into `memories_used`.

## 6. User isolation and deletion

All user-facing API operations require an authenticated session. The API derives `user_id` from the verified server-side session; it must not accept browser-supplied identity as authorization. Account IDs are opaque, server-generated values. Every memory query and mutation remains scoped to that ID. Existing demo records are not automatically assigned to a newly created account.

Every list, retrieval, update, and delete query must constrain `user_id`. The update/delete path must match the ownership edge or both `user_id` and `memory_id`. Return the same not-found response for missing and non-owned records. No shared entity nodes are needed for MVP; thus deletion affects only a memory and its graph edges.

## 7. Frontend-to-backend contract

- `POST /chat` sends the input message and optional conversation ID; it renders the returned answer, operation counts, and exact `memories_used`.
- `GET /memories/{user_id}` populates the saved memory list.
- `PATCH` and `DELETE` refresh the list only after server confirmation.
- `GET /health` drives a small connection status indicator.
- Render all user and model text with safe text APIs such as `textContent`; do not use unsafe HTML insertion.
- Disable duplicate send while a request is pending; support Enter to send and Shift+Enter for newline.
- Show an explicit empty evidence state when `memories_used` is empty.
- A “New chat” action clears visible conversation state and starts without replaying old messages. Saved memories remain in FalkorDB.
- Sign-up and sign-in create an HTTP-only session; the frontend uses that session for all protected requests and never selects an identity.
- Conversation turns and their evidence metadata persist in SQLite and are scoped to the authenticated account. FalkorDB remains authoritative for saved memories.

## 8. Independent modules and four-person ownership

| Owner | Files / module boundary | Must provide |
|---|---|---|
| 1 — Backend/integration | `backend/app/main.py`, `api/routes/`, `models/`, `services/conversation_service.py`, `config.py` | FastAPI app, Pydantic contracts, orchestration, dependency wiring |
| 2 — FalkorDB/graph | `db/falkordb_client.py`, `db/graph_queries.py`, `services/memory_service.py`, `services/retrieval_service.py` | Real graph persistence, scoped CRUD, duplicate/correction matching, retrieval |
| 3 — Frontend | `frontend/index.html`, `css/styles.css`, `js/api.js`, `js/chat.js`, `js/memories.js`, `js/app.js` | Chat and memory UI, safe rendering, API consumption |
| 4 — AI/testing/docs | `services/llm_service.py`, `services/memory_extractor.py`, `tests/`, `README.md`, `.env.example` | Extraction/generation adapter, validation, mocks and acceptance tests, setup and demo docs |

Member 4 coordinates LLM and test interfaces; Member 1 owns final integration. Avoid overlapping edits to shared files. Agree on contracts below before parallel implementation.

### Module interfaces

- `extract_facts(message, user_id, conversation_id) -> list[ProposedFact]`
- `upsert_memories(user_id, proposed_facts, source_ids) -> MemoryOperationSummary`
- `retrieve_memories(user_id, question, limit=10) -> list[RetrievedMemory]`
- `build_context(question, memories) -> GroundingContext`
- `generate_answer(question, grounding_context, recent_turns) -> str`
- `process_chat(request) -> ChatResponse`
- `GraphRepository.create/update/get/list/delete/related/health` performs all FalkorDB access; service and API layers must not run Cypher directly.

## 9. Integration order and acceptance checks

### Integration order

1. Agree on the memory record, enum values, API models, and function interfaces in this blueprint.
2. Member 2 proves connection to a real FalkorDB graph and validates create/list/update/delete query shapes with the pinned client/server.
3. Member 1 wires FastAPI models and health endpoint to the repository.
4. Member 4 delivers extraction and grounded generation behind stable service interfaces; mock the provider for unit tests.
5. Member 3 builds against the fixed JSON contracts, using a local mock only during UI development.
6. Integrate `POST /chat`, then corrections, deletion, graph display, and polish.
7. Run the end-to-end checks against actual FalkorDB; separately report mocked and live integration results.

### Acceptance checks

- Saving “I’m learning Python. I want to build an AI project by November. I can study one hour every day” creates actual active graph memories, scoped to the demo user.
- The graph can be inspected through a real FalkorDB query; UI state alone is not proof.
- After starting a new conversation or refreshing the page, a question about the goal retrieves relevant stored records.
- The generated answer receives those records as context; the response’s evidence matches the records actually retrieved.
- “I now have two hours available each day” makes the new value authoritative; the old value is not returned as active support.
- Asking for a never-stored favorite language yields an honest unknown response and no fabricated evidence.
- Deleting a memory removes it from subsequent retrieval and evidence.
- A second test identity cannot list, retrieve, edit, or delete the first user’s records.
- Duplicate submission does not create duplicate active facts.
- Dependency errors are surfaced honestly; no fallback may claim graph retrieval or persistence succeeded when it did not.

## 10. Postpone if time is limited

Defer semantic/vector retrieval, advanced ranking, confidence scoring, multi-factor authentication, password recovery, email verification, multi-agent systems, and decorative UI work until the core flows are reliable. The current account implementation supplies local email/password sign-in and persistent per-user chat history; it does not include the deferred account recovery and deployment hardening features.

## 11. FalkorDB details to verify before coding

The official documentation supports FalkorDB as an OpenCypher property graph and shows the Python client’s graph selection and query flow. Verify these details against the chosen server image and pinned client before implementation:

- Python client version, connection/authentication options, and exact parameter-binding signature.
- Whether the chosen version accepts `CONTAINS`, `MERGE`, `DETACH DELETE`, `OPTIONAL MATCH`, and the property types used above.
- Whether map/dictionary provenance properties are supported as node properties; if not, serialize provenance as JSON text.
- Uniqueness constraint syntax and availability; the MVP should work without it.
- Transaction support and failure semantics for a correction that supersedes one record and creates another.
- `LIMIT` parameter support and result decoding format.
- Docker image tag, exposed ports, and persistence volume configuration for the demo environment.

Do not infer feature support from general Cypher compatibility alone; validate by running the intended queries against the actual server.

# SHARED IMPLEMENTATION CONTRACT

**Memory:** `Memory` node with `memory_id`, `user_id`, `content`, `category`, `subject`, `normalized_subject`, `created_at`, `updated_at`, `source_message_id`, `source_conversation_id`, `provenance`, and `status`; owned by `(User)-[:HAS_MEMORY]->(Memory)`. Categories: `goal`, `skill`, `project`, `task`, `preference`, `commitment`, `decision`, `other`. Active records only are retrieved.

**Endpoints:** `POST /auth/signup` accepts `{full_name,email,mobile_number,age,password}` (email is unique; mobile is E.164 profile information and may be shared; age is 13–120); `POST /auth/login` accepts `{email,password}`; `/auth/logout`; `GET /auth/me`; `GET /health`; authenticated `POST /chat` with `{message, conversation_id?}` returning `{conversation_id, answer, memories_used[], memory_operations:{created,updated,superseded}}`; authenticated memories/graph routes; and authenticated `GET /conversations`, `GET /conversations/{conversation_id}`, `DELETE /conversations/{conversation_id}`. User ownership is derived from the session, never from request-supplied user IDs. Conversation transcripts and evidence metadata persist in SQLite; memories and graph relationships remain in FalkorDB.

**Ownership:** Member 1 owns FastAPI contracts/orchestration; Member 2 owns FalkorDB schema, queries, persistence, matching, and retrieval; Member 3 owns the vanilla JS frontend; Member 4 owns LLM extraction/generation, tests, and setup docs. Repository interface is the only module allowed to execute Cypher.

**Integration rules:** Parameterize all values; scope every operation to the server-resolved user; bound retrieval to 10 records and one relationship hop; pass only selected graph results to generation; serialize evidence from those same results. Correct conversational facts by superseding and linking provenance; delete only the owned memory and its memory relationships. Verify all FalkorDB syntax/client behavior against the pinned versions. Implementation and verification status are reported separately; do not infer real FalkorDB or live LLM success from mocked tests.
