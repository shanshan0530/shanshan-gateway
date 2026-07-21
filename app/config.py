from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
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
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def telegram_authorized(self) -> bool:
        return bool(self.telegram_allowed_user_id)

    def missing_required(self) -> list[str]:
        values = {
            "GATEWAY_API_KEY": self.gateway_api_key,
            "UPSTREAM_API_KEY": self.upstream_api_key,
            "UPSTREAM_BASE_URL": self.upstream_base_url,
            "UPSTREAM_MODEL": self.upstream_model,
        }
        return [name for name, value in values.items() if not value]
