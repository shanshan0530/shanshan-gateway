from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path("/app/ombre")
SOURCE = ROOT / "config.example.yaml"
TARGET = ROOT / "config.yaml"


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


with SOURCE.open("r", encoding="utf-8") as fh:
    config = yaml.safe_load(fh)

config["transport"] = "streamable-http"
config["buckets_dir"] = os.getenv("OMBRE_BUCKETS_DIR", "/app/data/buckets")
config["state_dir"] = os.getenv("OMBRE_STATE_DIR", "/app/data/state")

identity = config.setdefault("identity", {})
identity["ai_name"] = os.getenv("OMBRE_AI_NAME", identity.get("ai_name", "AI"))
identity["user_name"] = os.getenv("OMBRE_USER_NAME", identity.get("user_name", "User"))
identity["user_display_name"] = os.getenv(
    "OMBRE_USER_DISPLAY_NAME", identity.get("user_display_name", "用户")
)

gateway = config.setdefault("gateway", {})
gateway["host"] = "0.0.0.0"
gateway["port"] = 8010
gateway["default_session_id"] = os.getenv("OMBRE_DEFAULT_SESSION_ID", "main")

# First deployment stays conservative. Heavy background features can be enabled later.
config.setdefault("dream", {})["auto_enabled"] = env_bool("OMBRE_DREAM_AUTO_ENABLED", False)
config.setdefault("reflection", {})["auto_enabled"] = env_bool(
    "OMBRE_REFLECTION_AUTO_ENABLED", False
)
config.setdefault("portrait", {})["auto_enabled"] = env_bool(
    "OMBRE_PORTRAIT_AUTO_ENABLED", False
)
config.setdefault("reranker", {})["enabled"] = env_bool("OMBRE_RERANKER_ENABLED", False)
config.setdefault("reflection", {})["daily_chat_memory_mode"] = os.getenv(
    "OMBRE_DAILY_CHAT_MEMORY_MODE", "review"
)

for path in (Path(config["buckets_dir"]), Path(config["state_dir"])):
    path.mkdir(parents=True, exist_ok=True)

with TARGET.open("w", encoding="utf-8") as fh:
    yaml.safe_dump(config, fh, allow_unicode=True, sort_keys=False)

print(f"Generated {TARGET}")
