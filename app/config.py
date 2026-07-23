from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _hour_env(name: str, default: int) -> int:
    try:
        return min(23, max(0, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gateway_api_key: str
    upstream_api_key: str
    upstream_base_url: str
    upstream_model: str
    public_model_name: str
    request_timeout_seconds: int
    max_request_bytes: int
    telegram_bot_token: str = ""
    telegram_allowed_user_id: str = ""
    telegram_system_prompt: str = ""
    telegram_history_messages: int = 24
    telegram_poll_timeout_seconds: int = 30
    telegram_db_path: str = "/app/data/telegram.sqlite3"
    telegram_max_stored_messages: int = 500
    telegram_multipart_enabled: bool = True
    telegram_multipart_max_parts: int = 3
    telegram_multipart_delay_ms: int = 700
    telegram_heartbeat_enabled: bool = True
    telegram_heartbeat_check_seconds: int = 900
    telegram_heartbeat_silence_minutes: int = 60
    telegram_heartbeat_cooldown_minutes: int = 90
    telegram_heartbeat_strong_cooldown_minutes: int = 45
    telegram_heartbeat_daily_limit: int = 10
    telegram_heartbeat_quiet_start_hour: int = 6
    telegram_heartbeat_quiet_end_hour: int = 9
    telegram_heartbeat_timezone: str = "Asia/Taipei"
    sleep_reminder_enabled: bool = True
    sleep_reminder_start_hour: int = 1
    sleep_reminder_end_hour: int = 6
    sleep_reminder_recent_activity_minutes: int = 30
    sleep_reminder_followup_minutes: int = 60
    sleep_reminder_max_per_night: int = 2
    ombre_recall_enabled: bool = False
    ombre_mcp_url: str = ""
    ombre_mcp_token: str = ""
    ombre_recall_max_results: int = 3
    ombre_recall_max_tokens: int = 1600
    ombre_recall_timeout_seconds: int = 20
    ombre_recall_max_chars: int = 7000
    ombre_recall_min_query_chars: int = 4
    supabase_url: str = ""
    supabase_key: str = ""
    orangechat_assistant_id: str = ""
    eventide_assistant_id: str = "景行"
    supabase_continuity_enabled: bool = True
    eventide_context_enabled: bool = True
    supabase_timeout_seconds: int = 8
    supabase_summary_limit: int = 3
    supabase_recent_message_limit: int = 8
    gateway_auto_summary_enabled: bool = True
    gateway_summary_message_threshold: int = 24
    gateway_summary_max_tokens: int = 1200
    gateway_summary_timeout_seconds: int = 60
    device_perception_enabled: bool = True
    device_perception_timezone: str = "Asia/Taipei"
    device_perception_check_seconds: int = 900
    device_perception_cooldown_minutes: int = 180
    device_perception_db_path: str = "/app/data/telegram.sqlite3"
    health_context_enabled: bool = True
    health_context_morning_start_hour: int = 6
    health_context_morning_end_hour: int = 12
    health_context_max_age_minutes: int = 45

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gateway_api_key=os.getenv("GATEWAY_API_KEY", "").strip(),
            upstream_api_key=os.getenv("UPSTREAM_API_KEY", "").strip(),
            upstream_base_url=os.getenv("UPSTREAM_BASE_URL", "").strip(),
            upstream_model=os.getenv("UPSTREAM_MODEL", "").strip(),
            public_model_name=os.getenv("PUBLIC_MODEL_NAME", "shanshan-claude").strip()
            or "shanshan-claude",
            request_timeout_seconds=_positive_int("REQUEST_TIMEOUT_SECONDS", 300),
            max_request_bytes=_positive_int("MAX_REQUEST_BYTES", 10 * 1024 * 1024),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_allowed_user_id=os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip(),
            telegram_system_prompt=os.getenv("TELEGRAM_SYSTEM_PROMPT", "").strip(),
            telegram_history_messages=_positive_int("TELEGRAM_HISTORY_MESSAGES", 24),
            telegram_poll_timeout_seconds=_positive_int("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
            telegram_db_path=os.getenv(
                "TELEGRAM_DB_PATH", "/app/data/telegram.sqlite3"
            ).strip()
            or "/app/data/telegram.sqlite3",
            telegram_max_stored_messages=_positive_int(
                "TELEGRAM_MAX_STORED_MESSAGES", 500
            ),
            telegram_multipart_enabled=_bool_env(
                "TELEGRAM_MULTIPART_ENABLED", True
            ),
            telegram_multipart_max_parts=_positive_int(
                "TELEGRAM_MULTIPART_MAX_PARTS", 3
            ),
            telegram_multipart_delay_ms=_nonnegative_int(
                "TELEGRAM_MULTIPART_DELAY_MS", 700
            ),
            telegram_heartbeat_enabled=_bool_env(
                "TELEGRAM_HEARTBEAT_ENABLED", True
            ),
            telegram_heartbeat_check_seconds=_positive_int(
                "TELEGRAM_HEARTBEAT_CHECK_SECONDS", 900
            ),
            telegram_heartbeat_silence_minutes=_positive_int(
                "TELEGRAM_HEARTBEAT_SILENCE_MINUTES", 60
            ),
            telegram_heartbeat_cooldown_minutes=_positive_int(
                "TELEGRAM_HEARTBEAT_COOLDOWN_MINUTES", 90
            ),
            telegram_heartbeat_strong_cooldown_minutes=_positive_int(
                "TELEGRAM_HEARTBEAT_STRONG_COOLDOWN_MINUTES", 45
            ),
            telegram_heartbeat_daily_limit=_positive_int(
                "TELEGRAM_HEARTBEAT_DAILY_LIMIT", 10
            ),
            telegram_heartbeat_quiet_start_hour=_hour_env(
                "TELEGRAM_HEARTBEAT_QUIET_START_HOUR", 6
            ),
            telegram_heartbeat_quiet_end_hour=_hour_env(
                "TELEGRAM_HEARTBEAT_QUIET_END_HOUR", 9
            ),
            telegram_heartbeat_timezone=os.getenv(
                "TELEGRAM_HEARTBEAT_TIMEZONE", "Asia/Taipei"
            ).strip()
            or "Asia/Taipei",
            sleep_reminder_enabled=_bool_env(
                "SLEEP_REMINDER_ENABLED", True
            ),
            sleep_reminder_start_hour=_hour_env(
                "SLEEP_REMINDER_START_HOUR", 1
            ),
            sleep_reminder_end_hour=_hour_env(
                "SLEEP_REMINDER_END_HOUR", 6
            ),
            sleep_reminder_recent_activity_minutes=_positive_int(
                "SLEEP_REMINDER_RECENT_ACTIVITY_MINUTES", 30
            ),
            sleep_reminder_followup_minutes=_positive_int(
                "SLEEP_REMINDER_FOLLOWUP_MINUTES", 60
            ),
            sleep_reminder_max_per_night=_positive_int(
                "SLEEP_REMINDER_MAX_PER_NIGHT", 2
            ),
            ombre_recall_enabled=_bool_env("OMBRE_RECALL_ENABLED", False),
            ombre_mcp_url=os.getenv("OMBRE_MCP_URL", "").strip(),
            ombre_mcp_token=os.getenv("OMBRE_MCP_TOKEN", "").strip(),
            ombre_recall_max_results=_positive_int("OMBRE_RECALL_MAX_RESULTS", 3),
            ombre_recall_max_tokens=_positive_int("OMBRE_RECALL_MAX_TOKENS", 1600),
            ombre_recall_timeout_seconds=_positive_int(
                "OMBRE_RECALL_TIMEOUT_SECONDS", 20
            ),
            ombre_recall_max_chars=_positive_int("OMBRE_RECALL_MAX_CHARS", 7000),
            ombre_recall_min_query_chars=_positive_int(
                "OMBRE_RECALL_MIN_QUERY_CHARS", 4
            ),
            supabase_url=os.getenv("SUPABASE_URL", "").strip(),
            supabase_key=os.getenv("SUPABASE_KEY", "").strip(),
            orangechat_assistant_id=os.getenv("ORANGECHAT_ASSISTANT_ID", "").strip(),
            eventide_assistant_id=os.getenv("EVENTIDE_ASSISTANT_ID", "景行").strip()
            or "景行",
            supabase_continuity_enabled=_bool_env("SUPABASE_CONTINUITY_ENABLED", True),
            eventide_context_enabled=_bool_env("EVENTIDE_CONTEXT_ENABLED", True),
            supabase_timeout_seconds=_positive_int("SUPABASE_TIMEOUT_SECONDS", 8),
            supabase_summary_limit=_positive_int("SUPABASE_SUMMARY_LIMIT", 3),
            supabase_recent_message_limit=_positive_int(
                "SUPABASE_RECENT_MESSAGE_LIMIT", 8
            ),
            gateway_auto_summary_enabled=_bool_env(
                "GATEWAY_AUTO_SUMMARY_ENABLED", True
            ),
            gateway_summary_message_threshold=_positive_int(
                "GATEWAY_SUMMARY_MESSAGE_THRESHOLD", 24
            ),
            gateway_summary_max_tokens=_positive_int(
                "GATEWAY_SUMMARY_MAX_TOKENS", 1200
            ),
            gateway_summary_timeout_seconds=_positive_int(
                "GATEWAY_SUMMARY_TIMEOUT_SECONDS", 60
            ),
            device_perception_enabled=_bool_env(
                "DEVICE_PERCEPTION_ENABLED", True
            ),
            device_perception_timezone=os.getenv(
                "DEVICE_PERCEPTION_TIMEZONE", "Asia/Taipei"
            ).strip()
            or "Asia/Taipei",
            device_perception_check_seconds=_positive_int(
                "DEVICE_PERCEPTION_CHECK_SECONDS", 900
            ),
            device_perception_cooldown_minutes=_positive_int(
                "DEVICE_PERCEPTION_COOLDOWN_MINUTES", 180
            ),
            device_perception_db_path=os.getenv(
                "DEVICE_PERCEPTION_DB_PATH",
                os.getenv("TELEGRAM_DB_PATH", "/app/data/telegram.sqlite3"),
            ).strip()
            or "/app/data/telegram.sqlite3",
            health_context_enabled=_bool_env("HEALTH_CONTEXT_ENABLED", True),
            health_context_morning_start_hour=_hour_env(
                "HEALTH_CONTEXT_MORNING_START_HOUR", 6
            ),
            health_context_morning_end_hour=_hour_env(
                "HEALTH_CONTEXT_MORNING_END_HOUR", 12
            ),
            health_context_max_age_minutes=_positive_int(
                "HEALTH_CONTEXT_MAX_AGE_MINUTES", 45
            ),
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def telegram_authorized(self) -> bool:
        return bool(self.telegram_allowed_user_id)

    @property
    def telegram_heartbeat_ready(self) -> bool:
        return bool(
            self.telegram_heartbeat_enabled
            and self.telegram_enabled
            and self.telegram_authorized
            and self.telegram_system_prompt
            and self.upstream_api_key
            and self.upstream_base_url
            and self.upstream_model
        )

    @property
    def telegram_sleep_reminder_ready(self) -> bool:
        return self.sleep_guidance_ready and self.telegram_heartbeat_ready

    @property
    def sleep_guidance_ready(self) -> bool:
        return bool(
            self.sleep_reminder_enabled
            and self.upstream_api_key
            and self.upstream_base_url
            and self.upstream_model
        )

    @property
    def ombre_recall_ready(self) -> bool:
        return bool(
            self.ombre_recall_enabled
            and self.ombre_mcp_url
            and self.ombre_mcp_token
        )

    @property
    def supabase_ready(self) -> bool:
        return bool(
            self.supabase_url.startswith("https://")
            and self.supabase_key
            and self.orangechat_assistant_id
        )

    @property
    def supabase_continuity_ready(self) -> bool:
        return self.supabase_continuity_enabled and self.supabase_ready

    @property
    def eventide_context_ready(self) -> bool:
        return bool(
            self.eventide_context_enabled
            and self.supabase_url.startswith("https://")
            and self.supabase_key
            and self.eventide_assistant_id
        )

    @property
    def gateway_auto_summary_ready(self) -> bool:
        return bool(
            self.gateway_auto_summary_enabled
            and self.supabase_continuity_ready
            and self.upstream_api_key
            and self.upstream_base_url
            and self.upstream_model
        )

    @property
    def device_perception_ready(self) -> bool:
        return self.device_perception_enabled and self.supabase_ready

    @property
    def health_context_ready(self) -> bool:
        return self.health_context_enabled and self.supabase_ready

    def missing_required(self) -> list[str]:
        values = {
            "GATEWAY_API_KEY": self.gateway_api_key,
            "UPSTREAM_API_KEY": self.upstream_api_key,
            "UPSTREAM_BASE_URL": self.upstream_base_url,
            "UPSTREAM_MODEL": self.upstream_model,
        }
        return [name for name, value in values.items() if not value]
