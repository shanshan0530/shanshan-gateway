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
        )

    def missing_required(self) -> list[str]:
        values = {
            "GATEWAY_API_KEY": self.gateway_api_key,
            "UPSTREAM_API_KEY": self.upstream_api_key,
            "UPSTREAM_BASE_URL": self.upstream_base_url,
            "UPSTREAM_MODEL": self.upstream_model,
        }
        return [name for name, value in values.items() if not value]
