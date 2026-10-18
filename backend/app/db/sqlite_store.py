"""SQLite persistence for accounts, sessions, and conversation history."""

from __future__ import annotations

import sqlite3
import json
import threading
from pathlib import Path
from typing import Any

from app.utils import new_id, utc_now_iso


class SQLiteStore:
    """Small local relational store; FalkorDB remains authoritative for memories."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 10000")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL DEFAULT '',
                    mobile_number TEXT,
                    age INTEGER,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS conversations (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, conversation_id)
                );
                CREATE INDEX IF NOT EXISTS conversations_updated_idx
                    ON conversations(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id, conversation_id)
                        REFERENCES conversations(user_id, conversation_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_idx
                    ON messages(user_id, conversation_id, created_at);
                """
            )
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}
            if "metadata" not in columns:
                self._db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            user_columns = {row[1] for row in self._db.execute("PRAGMA table_info(users)")}
            if "full_name" not in user_columns:
                self._db.execute("ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
            if "mobile_number" not in user_columns:
                self._db.execute("ALTER TABLE users ADD COLUMN mobile_number TEXT")
            if "age" not in user_columns:
                self._db.execute("ALTER TABLE users ADD COLUMN age INTEGER")
            # Phone numbers are profile information, not account identifiers.
            # Remove the index created by earlier builds so shared numbers work.
            self._db.execute("DROP INDEX IF EXISTS users_mobile_number_unique")

    def create_user(
        self,
        email: str,
        password_hash: str,
        *,
        user_id: str | None = None,
        full_name: str = "",
        mobile_number: str | None = None,
        age: int | None = None,
    ) -> dict[str, Any] | None:
        user = {
            "user_id": user_id or new_id("usr"),
            "email": email,
            "full_name": full_name,
            "mobile_number": mobile_number,
            "age": age,
            "created_at": utc_now_iso(),
        }
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO users(user_id,email,full_name,mobile_number,age,password_hash,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (user["user_id"], email, full_name, mobile_number, age, password_hash, user["created_at"]),
                )
            except sqlite3.IntegrityError:
                return None
        return user

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT user_id,email,full_name,mobile_number,age,password_hash,created_at "
                "FROM users WHERE email=?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT user_id,email,full_name,mobile_number,age,created_at FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_session(self, token_hash: str, user_id: str, expires_at: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                (token_hash, user_id, expires_at, utc_now_iso()),
            )

    def session_user(self, token_hash: str, now: int) -> dict[str, Any] | None:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT u.user_id,u.email,u.full_name,u.mobile_number,u.age,u.created_at FROM sessions s "
                "JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash, now),
            ).fetchone()
            self._db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        return dict(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    # Persistent conversation history -------------------------------------
    def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM conversations WHERE user_id=? AND conversation_id=?",
                (user_id, conversation_id),
            ).fetchone() is not None

    def save_turn(
        self,
        user_id: str,
        conversation_id: str,
        user_text: str,
        answer: str,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        title = user_text.strip().replace("\n", " ")[:80] or "New conversation"
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversations(user_id,conversation_id,title,created_at,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(user_id,conversation_id) DO UPDATE SET updated_at=excluded.updated_at",
                (user_id, conversation_id, title, now, now),
            )
            self._db.executemany(
                "INSERT INTO messages(message_id,user_id,conversation_id,role,content,metadata,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                [
                    (new_id("msg"), user_id, conversation_id, "user", user_text, "{}", now),
                    (new_id("msg"), user_id, conversation_id, "assistant", answer,
                     json.dumps(assistant_metadata or {}, ensure_ascii=False), now),
                ],
            )

    def recent_messages(self, user_id: str, conversation_id: str, limit: int) -> list[dict[str, str]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role,content FROM messages WHERE user_id=? AND conversation_id=? "
                "ORDER BY created_at DESC,rowid DESC LIMIT ?",
                (user_id, conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def list_conversations(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT c.conversation_id,c.title,c.created_at,c.updated_at,COUNT(m.message_id) AS message_count "
                "FROM conversations c LEFT JOIN messages m ON m.user_id=c.user_id AND m.conversation_id=c.conversation_id "
                "WHERE c.user_id=? GROUP BY c.user_id,c.conversation_id "
                "ORDER BY c.updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            conversation = self._db.execute(
                "SELECT conversation_id,title,created_at,updated_at FROM conversations "
                "WHERE user_id=? AND conversation_id=?", (user_id, conversation_id)
            ).fetchone()
            if not conversation:
                return None
            messages = self._db.execute(
                "SELECT message_id,role,content,metadata,created_at FROM messages "
                "WHERE user_id=? AND conversation_id=? ORDER BY created_at,rowid",
                (user_id, conversation_id),
            ).fetchall()
        parsed_messages = []
        for row in messages:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item["metadata"] or "{}")
            except (TypeError, ValueError):
                item["metadata"] = {}
            parsed_messages.append(item)
        return {**dict(conversation), "messages": parsed_messages}

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        with self._lock, self._db:
            cursor = self._db.execute(
                "DELETE FROM conversations WHERE user_id=? AND conversation_id=?",
                (user_id, conversation_id),
            )
        return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()
