from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class HeartbeatState:
    enabled: bool
    last_sent_at: datetime | None
    daily_date: str
    daily_count: int


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
                CREATE TABLE IF NOT EXISTS telegram_heartbeat_state (
                    chat_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                    last_sent_at TEXT,
                    daily_date TEXT NOT NULL DEFAULT '',
                    daily_count INTEGER NOT NULL DEFAULT 0 CHECK(daily_count >= 0)
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

    def last_message_at(self, chat_id: str, role: str) -> datetime | None:
        if role not in {"user", "assistant"}:
            raise ValueError("unsupported conversation role")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT created_at
                FROM telegram_messages
                WHERE chat_id = ? AND role = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, role),
            ).fetchone()
        return _parse_datetime(row["created_at"] if row else None)

    def heartbeat_state(
        self,
        chat_id: str,
        *,
        default_enabled: bool,
    ) -> HeartbeatState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT enabled, last_sent_at, daily_date, daily_count
                FROM telegram_heartbeat_state
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return HeartbeatState(default_enabled, None, "", 0)
        return HeartbeatState(
            enabled=bool(row["enabled"]),
            last_sent_at=_parse_datetime(row["last_sent_at"]),
            daily_date=str(row["daily_date"] or ""),
            daily_count=max(0, int(row["daily_count"] or 0)),
        )

    def set_heartbeat_enabled(self, chat_id: str, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_heartbeat_state(chat_id, enabled)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET enabled = excluded.enabled
                """,
                (chat_id, int(enabled)),
            )

    def record_heartbeat_sent(
        self,
        chat_id: str,
        *,
        sent_at: datetime,
        local_date: str,
        default_enabled: bool,
    ) -> HeartbeatState:
        sent_utc = sent_at.astimezone(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT enabled, daily_date, daily_count
                FROM telegram_heartbeat_state
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
            enabled = bool(row["enabled"]) if row else default_enabled
            previous_date = str(row["daily_date"] or "") if row else ""
            previous_count = int(row["daily_count"] or 0) if row else 0
            count = previous_count + 1 if previous_date == local_date else 1
            connection.execute(
                """
                INSERT INTO telegram_heartbeat_state(
                    chat_id, enabled, last_sent_at, daily_date, daily_count
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    last_sent_at = excluded.last_sent_at,
                    daily_date = excluded.daily_date,
                    daily_count = excluded.daily_count
                """,
                (
                    chat_id,
                    int(enabled),
                    sent_utc.isoformat(timespec="seconds"),
                    local_date,
                    count,
                ),
            )
        return HeartbeatState(enabled, sent_utc, local_date, count)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
