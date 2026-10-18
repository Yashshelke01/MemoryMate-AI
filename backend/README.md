# MemoryMate AI — Backend (FastAPI)

FastAPI API layer and chat orchestration, integrated with the FalkorDB repository and memory/retrieval services in `app/db/` and `app/services/`. Extraction and grounded generation are implemented in `app/services/`. The API loads collaborators through the shared interfaces in `app/interfaces.py` and reports dependency failures without claiming persistence or grounding succeeded.

## Run

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env     # PowerShell; then set provider credentials
uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

## Test

```bash
cd backend
python -m pytest
```

`tests/test_chat.py`, `tests/test_memories.py`, and related API tests use test-only fakes. `tests/test_graph_layer.py` uses a stateful mocked FalkorDB query engine and does not prove server compatibility. `tests/test_falkordb_live.py` is the real-server acceptance suite; it skips when FalkorDB is unavailable. LLM tests mock provider responses; a real provider call requires configured credentials and is not made by the unit suite.

To run the live graph checks, start a FalkorDB server (for example, `docker run --name memorymate-falkordb -p 6379:6379 -p 3000:3000 -d falkordb/falkordb:latest`), then run `python -m pytest -rs tests/test_falkordb_live.py` from `backend/`. The standalone verifier is `python graph_memory_db/verify_graph.py` from the repository root. Both use an isolated graph and clean up their test memories by default.

## Endpoints (shapes per PROJECT_CONTRACT.md section 4)

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/signup` | Create an account with full name, email, international mobile number, age (13–120), and password; starts an HTTP-only session. |
| POST | `/auth/login`, `/auth/logout` | Start or end the account session; login accepts email plus password. |
| GET | `/auth/me` | Return the signed-in account profile. |
| GET | `/health` | `falkordb`: `ok`/`unavailable`; `llm`: `configured`/`not_configured`. No generation call. |
| POST | `/chat` | Requires a session; the owner ID is derived server-side. Extract → persist → retrieve → ground → answer. |
| GET | `/memories/{user_id}?limit=50&offset=0` | Requires a session matching the path ID; active records only. |
| PATCH | `/memories/{memory_id}` | Requires a session; body contains only fields to edit. |
| DELETE | `/memories/{memory_id}` | Requires a session; empty JSON body. |
| GET | `/graph/{user_id}` | Requires a matching session and returns only that account's graph. |
| GET | `/conversations`, `/conversations/{conversation_id}` | List and reopen the signed-in user's saved chats. |
| DELETE | `/conversations/{conversation_id}` | Delete only the signed-in user's conversation and transcript. |

Errors are always `{"error": {"code", "message", "details"?}}`: `401` missing/expired session, `422` validation, `409` duplicate signup, `404` missing or non-owned memory/conversation, `503` dependency/step failure or timeout, `500` unexpected. No stack traces, Cypher, credentials or provider messages are returned.

Behaviours worth knowing:
- Extraction, persistence, retrieval or generation failure → `503`; nothing is reported as saved/grounded. If generation fails after saving, `error.details.memory_operations` says what was saved.
- A timeout (`CHAT_TIMEOUT_SECONDS`) is `503 timeout`; for writes the outcome is then unknown.
- Retrieved records are re-checked server-side (same user, `active`, de-duplicated, max 10) before reaching the LLM or the evidence list.
- Writes are serialized per user within one process to stop duplicate submissions racing the duplicate check (does not protect multiple server processes).
- Conversation transcripts, recent turns, memory-operation summaries, and grounding evidence are stored in SQLite and scoped by authenticated account. FalkorDB remains authoritative for memory records.

## Accounts, sessions, and user-scoped data

Accounts are stored in `SQLITE_DB_PATH` (default `./memorymate.sqlite3`, relative to the backend working directory). Passwords are hashed with PBKDF2-HMAC-SHA256; the browser receives a random `HttpOnly`, `SameSite=Lax` session cookie. Session token hashes and expiration are stored in SQLite. The frontend never selects an account ID; protected API routes derive it from the session. For HTTPS deployments set `SESSION_COOKIE_SECURE=true` and serve the frontend/API over HTTPS. Local HTTP development keeps it false.

Signup requires a full name, unique email, international phone number in E.164 format (for example `+919876543210`), age from 13 through 120, and password. Phone numbers are profile information and may be shared by multiple accounts; sign-in is email-only. Existing SQLite databases are migrated on startup with nullable profile fields, so existing accounts remain able to sign in using email.

FalkorDB remains the source of truth for memories. New accounts receive new opaque IDs, so existing demo memories under `demo-user-1` are not assigned to any new account automatically. Do not add a public demo-ID allow-list as a replacement for authentication.

This first account implementation does not include email verification, password reset, multi-factor authentication, or distributed rate limiting. Before public deployment, add those controls and review session/CSRF policy and operational backups.

## LLM provider configuration

The AI modules use `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, and
`LLM_TIMEOUT_SECONDS` from the backend environment. Supported provider values
are `anthropic`, `openai`, and `openai_compatible`; choose a model name enabled
for the selected provider. `LLM_BASE_URL` is optional and overrides the API
base URL for a private gateway or compatible service. Leave it empty to use
the provider's official API. The API key remains server-side and is never
returned by `/health` or any browser response. Both extraction and answer
generation request schema-constrained JSON and validate it before use.

## Module interfaces

The graph repository is the only module that executes Cypher; values are parameterized and operations are user-scoped. `app/db/falkordb_client.py` exposes `get_repository()` and implements the protocol in `app/interfaces.py`.
`app/services/memory_service.py` performs duplicate/correction matching and persistence through the repository. `app/services/retrieval_service.py` builds bounded user-scoped retrieval results and context. `app/services/memory_extractor.py` validates directly supported facts. `app/services/llm_service.py` generates grounded answers and keeps evidence serialization in the backend.

Shared types live in `app/models/contracts.py`. Settings (including FalkorDB/LLM) come from `app.config.get_settings()`.

## Not done / open items

- The live FalkorDB and real-provider LLM checks require those external services and credentials to be available.
- Request body size is bounded only by field limits (no ASGI body-size middleware).
- Correction superseding and replacement creation are issued as one graph query; behavior still needs verification against the selected FalkorDB server version.
