# MemoryMate AI — Frontend (HTML5 / CSS3 / Vanilla JS)

Clean, responsive web interface for the MemoryMate AI FastAPI backend and FalkorDB graph memory layer (`PROJECT_CONTRACT.md` Sections 4, 7, and 8).

## File Structure

| File | Responsibility |
|---|---|
| `frontend/index.html` | Semantic HTML5 workspace layout (header health bar, chat pane, evidence inspector, saved-memory manager, SVG graph panel, and accessible edit modal) |
| `frontend/css/styles.css` | Restrained productivity design system, semantic category badges, keyboard focus styles (`:focus-visible`), and desktop/mobile responsive breakpoints |
| `frontend/js/api.js` | Credentialed fetch client for account sessions, chat, private memories, graph, and conversation history |
| `frontend/js/chat.js` | Chat controller, persistent conversation reopening, safe rendering, and the **"Memories used for this answer"** panel |
| `frontend/js/memories.js` | Authoritative saved-memory list (`GET /memories/{user_id}`), category filter pills (`goal`, `skill`, `project`, `task`, `preference`, `commitment`, `decision`, `other`), search, modal editing (`PATCH`), inline confirmed deletion (`DELETE`), and SVG graph visualization (`GET /graph/{user_id}`) |
| `frontend/js/app.js` | Sign-up/sign-in gate, account session, conversation history picker, health polling, API base URL, and mobile navigation |

## How to Serve the Frontend

The backend's default `CORS_ORIGINS` (`backend/app/config.py`) explicitly allows `http://localhost:8080`, `http://127.0.0.1:8080`, `http://localhost:5500`, `http://127.0.0.1:5500`, `http://localhost:3000`, and `http://127.0.0.1:3000`.

### 1. Start the FastAPI backend (Terminal 1)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2. Serve the static frontend (Terminal 2)

From the repository root:

```bash
python3 -m http.server 8080 --directory frontend
```

Or from inside the `frontend/` directory:

```bash
cd frontend
python3 -m http.server 8080
```

Then open **http://localhost:8080** (or **http://127.0.0.1:8080**) in your browser.

### Account sessions

- The app first checks for a valid HTTP-only session, then shows sign in or account creation.
- Account creation collects full name, email, country calling code plus mobile number, age (13–120), and password. Email is unique and is the only sign-in identifier; mobile numbers are profile information and can be shared across accounts.
- Each authenticated account has a backend-issued opaque user ID. The browser cannot choose which account owns a request.
- Conversation history is loaded from the authenticated account and can be reopened from the conversation picker. Memory records remain in FalkorDB and are scoped to that same account ID.
- For local development, use the same host name for the frontend and API (for example both `localhost`) so the browser sends the session cookie consistently.

## Contract Guarantees Implemented

- **Authoritative Graph Persistence**: Saved memories are never stored in `localStorage` or `sessionStorage`. Every list view, edit, and deletion reflects confirmed backend state from FalkorDB.
- **No Unconfirmed Claims**: Memory operation counts (`created`, `updated`, `superseded`) and edit/delete confirmations are displayed only after the backend responds with `200 OK` (or via `error.details.memory_operations` if LLM generation fails after persistence).
- **Verifiable Grounding Evidence**: The **"Memories used for this answer"** panel renders the exact `memories_used` records returned by `POST /chat`, with an explicit empty state when `memories_used` is `[]`.
- **XSS-Safe Rendering**: All user messages, assistant answers, memory subjects/contents, provenance fields, graph labels, and error messages are rendered using `textContent` and DOM element creation APIs.
