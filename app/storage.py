from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


class ConversationStore:
    """Durable, private short-term Telegram conversation history."""

    def __init__(self, db_path: str, max_messages_per_chat: int = 500):
        self.db_path = db_path
        self.max_messages_per_chat = max(1, max_messages_per_chat)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telegram_messages_chat
                ON telegram_messages(chat_id, id DESC)
                """
            )

    def recent(self, chat_id: str, limit: int) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM telegram_messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def append(self, chat_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("unsupported conversation role")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_messages(chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chat_id,
                    role,
                    content,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            connection.execute(
                """
                DELETE FROM telegram_messages
                WHERE chat_id = ?
                  AND id NOT IN (
                      SELECT id FROM telegram_messages
                      WHERE chat_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (chat_id, chat_id, self.max_messages_per_chat),
            )

    def clear(self, chat_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM telegram_messages WHERE chat_id = ?", (chat_id,)
            )
