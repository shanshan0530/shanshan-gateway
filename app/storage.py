from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class HeartbeatState:
    enabled: bool
    last_sent_at: datetime | None
    daily_date: str
    daily_count: int


@dataclass(frozen=True)
class SleepReminderState:
    last_sent_at: datetime | None
    night_key: str
    reminder_count: int


@dataclass(frozen=True)
class PerceptionShadowState:
    last_row_id: int
    last_checked_at: datetime | None
    total_scans: int
    total_detected_events: int
    total_eligible_events: int
    event_counts: dict[str, int]


class ConversationStore:
    """Durable private gateway state stored on the existing SQLite volume."""

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
                CREATE TABLE IF NOT EXISTS gateway_perception_state (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    last_row_id INTEGER NOT NULL DEFAULT 0,
                    last_checked_at TEXT,
                    total_scans INTEGER NOT NULL DEFAULT 0,
                    total_detected_events INTEGER NOT NULL DEFAULT 0,
                    total_eligible_events INTEGER NOT NULL DEFAULT 0,
                    event_counts TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_perception_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_eligible_at TEXT,
                    seen_count INTEGER NOT NULL DEFAULT 1
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
                CREATE TABLE IF NOT EXISTS telegram_sleep_reminder_state (
                    chat_id TEXT PRIMARY KEY,
                    last_sent_at TEXT,
                    night_key TEXT NOT NULL DEFAULT '',
                    reminder_count INTEGER NOT NULL DEFAULT 0
                        CHECK(reminder_count >= 0)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telegram_messages_chat
                ON telegram_messages(chat_id, id DESC)
                """
            )

    def perception_shadow_state(self) -> PerceptionShadowState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_row_id, last_checked_at, total_scans,
                       total_detected_events, total_eligible_events, event_counts
                FROM gateway_perception_state
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return PerceptionShadowState(0, None, 0, 0, 0, {})
        return _perception_state_from_row(row)

    def record_perception_scan(
        self,
        *,
        latest_row_id: int,
        events: Iterable[tuple[str, str]],
        checked_at: datetime,
        cooldown_minutes: int,
    ) -> tuple[PerceptionShadowState, tuple[str, ...], bool]:
        checked_utc = checked_at.astimezone(timezone.utc)
        checked_text = checked_utc.isoformat(timespec="seconds")
        cooldown_seconds = max(1, cooldown_minutes) * 60
        event_items = tuple(
            (str(kind)[:80], str(fingerprint)[:128])
            for kind, fingerprint in events
            if kind and fingerprint
        )
        eligible_kinds: list[str] = []

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_row_id, last_checked_at, total_scans,
                       total_detected_events, total_eligible_events, event_counts
                FROM gateway_perception_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            state = (
                _perception_state_from_row(row)
                if row is not None
                else PerceptionShadowState(0, None, 0, 0, 0, {})
            )
            if latest_row_id <= state.last_row_id:
                return state, (), False

            counts = dict(state.event_counts)
            for kind, fingerprint in event_items:
                counts[kind] = counts.get(kind, 0) + 1
                fingerprint_row = connection.execute(
                    """
                    SELECT last_eligible_at, seen_count
                    FROM gateway_perception_fingerprints
                    WHERE fingerprint = ?
                    """,
                    (fingerprint,),
                ).fetchone()
                last_eligible = _parse_datetime(
                    fingerprint_row["last_eligible_at"] if fingerprint_row else None
                )
                is_eligible = (
                    last_eligible is None
                    or (checked_utc - last_eligible).total_seconds() >= cooldown_seconds
                )
                if is_eligible:
                    eligible_kinds.append(kind)
                connection.execute(
                    """
                    INSERT INTO gateway_perception_fingerprints(
                        fingerprint, kind, last_seen_at, last_eligible_at, seen_count
                    ) VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        kind = excluded.kind,
                        last_seen_at = excluded.last_seen_at,
                        last_eligible_at = CASE
                            WHEN excluded.last_eligible_at IS NOT NULL
                            THEN excluded.last_eligible_at
                            ELSE gateway_perception_fingerprints.last_eligible_at
                        END,
                        seen_count = gateway_perception_fingerprints.seen_count + 1
                    """,
                    (
                        fingerprint,
                        kind,
                        checked_text,
                        checked_text if is_eligible else None,
                    ),
                )

            next_state = PerceptionShadowState(
                last_row_id=max(0, int(latest_row_id)),
                last_checked_at=checked_utc,
                total_scans=state.total_scans + 1,
                total_detected_events=state.total_detected_events + len(event_items),
                total_eligible_events=(
                    state.total_eligible_events + len(eligible_kinds)
                ),
                event_counts=counts,
            )
            connection.execute(
                """
                INSERT INTO gateway_perception_state(
                    singleton_id, last_row_id, last_checked_at, total_scans,
                    total_detected_events, total_eligible_events, event_counts
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    last_row_id = excluded.last_row_id,
                    last_checked_at = excluded.last_checked_at,
                    total_scans = excluded.total_scans,
                    total_detected_events = excluded.total_detected_events,
                    total_eligible_events = excluded.total_eligible_events,
                    event_counts = excluded.event_counts
                """,
                (
                    next_state.last_row_id,
                    checked_text,
                    next_state.total_scans,
                    next_state.total_detected_events,
                    next_state.total_eligible_events,
                    json.dumps(counts, ensure_ascii=False, sort_keys=True),
                ),
            )
            retention_cutoff = datetime.fromtimestamp(
                checked_utc.timestamp() - 7 * 86400,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
            connection.execute(
                """
                DELETE FROM gateway_perception_fingerprints
                WHERE last_seen_at < ?
                """,
                (retention_cutoff,),
            )
        return next_state, tuple(eligible_kinds), True

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

    def sleep_reminder_state(self, chat_id: str) -> SleepReminderState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_sent_at, night_key, reminder_count
                FROM telegram_sleep_reminder_state
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return SleepReminderState(None, "", 0)
        return SleepReminderState(
            last_sent_at=_parse_datetime(row["last_sent_at"]),
            night_key=str(row["night_key"] or ""),
            reminder_count=max(0, int(row["reminder_count"] or 0)),
        )

    def record_sleep_reminder_sent(
        self,
        chat_id: str,
        *,
        sent_at: datetime,
        night_key: str,
    ) -> SleepReminderState:
        sent_utc = sent_at.astimezone(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT night_key, reminder_count
                FROM telegram_sleep_reminder_state
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
            previous_key = str(row["night_key"] or "") if row else ""
            previous_count = int(row["reminder_count"] or 0) if row else 0
            count = previous_count + 1 if previous_key == night_key else 1
            connection.execute(
                """
                INSERT INTO telegram_sleep_reminder_state(
                    chat_id, last_sent_at, night_key, reminder_count
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    last_sent_at = excluded.last_sent_at,
                    night_key = excluded.night_key,
                    reminder_count = excluded.reminder_count
                """,
                (
                    chat_id,
                    sent_utc.isoformat(timespec="seconds"),
                    night_key,
                    count,
                ),
            )
        return SleepReminderState(sent_utc, night_key, count)

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


def _perception_state_from_row(row: sqlite3.Row) -> PerceptionShadowState:
    try:
        decoded = json.loads(str(row["event_counts"] or "{}"))
    except (json.JSONDecodeError, TypeError):
        decoded = {}
    counts = (
        {
            str(key): max(0, int(value))
            for key, value in decoded.items()
            if isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
        }
        if isinstance(decoded, dict)
        else {}
    )
    return PerceptionShadowState(
        last_row_id=max(0, int(row["last_row_id"] or 0)),
        last_checked_at=_parse_datetime(row["last_checked_at"]),
        total_scans=max(0, int(row["total_scans"] or 0)),
        total_detected_events=max(0, int(row["total_detected_events"] or 0)),
        total_eligible_events=max(0, int(row["total_eligible_events"] or 0)),
        event_counts=counts,
    )
