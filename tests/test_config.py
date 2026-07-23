from app.config import Settings


def test_missing_required_lists_every_empty_value(monkeypatch):
    for name in ("GATEWAY_API_KEY", "UPSTREAM_API_KEY", "UPSTREAM_BASE_URL", "UPSTREAM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env().missing_required() == [
        "GATEWAY_API_KEY",
        "UPSTREAM_API_KEY",
        "UPSTREAM_BASE_URL",
        "UPSTREAM_MODEL",
    ]


def test_public_model_has_friendly_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_MODEL_NAME", raising=False)
    assert Settings.from_env().public_model_name == "shanshan-claude"


def test_ombre_recall_needs_switch_url_and_token(monkeypatch):
    monkeypatch.setenv("OMBRE_RECALL_ENABLED", "true")
    monkeypatch.setenv("OMBRE_MCP_URL", "https://memory.example/mcp")
    monkeypatch.delenv("OMBRE_MCP_TOKEN", raising=False)
    assert not Settings.from_env().ombre_recall_ready

    monkeypatch.setenv("OMBRE_MCP_TOKEN", "private-token")
    assert Settings.from_env().ombre_recall_ready


def test_ombre_recall_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OMBRE_RECALL_ENABLED", raising=False)
    monkeypatch.setenv("OMBRE_MCP_URL", "https://memory.example/mcp")
    monkeypatch.setenv("OMBRE_MCP_TOKEN", "private-token")
    assert not Settings.from_env().ombre_recall_ready


def test_supabase_features_need_url_key_and_assistant_ids(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://memory.example")
    monkeypatch.setenv("SUPABASE_KEY", "publishable-key")
    monkeypatch.delenv("ORANGECHAT_ASSISTANT_ID", raising=False)
    settings = Settings.from_env()
    assert not settings.supabase_ready
    assert not settings.supabase_continuity_ready
    assert settings.eventide_context_ready

    monkeypatch.setenv("ORANGECHAT_ASSISTANT_ID", "assistant-uuid")
    settings = Settings.from_env()
    assert settings.supabase_ready
    assert settings.supabase_continuity_ready


def test_supabase_features_can_be_disabled_independently(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://memory.example")
    monkeypatch.setenv("SUPABASE_KEY", "publishable-key")
    monkeypatch.setenv("ORANGECHAT_ASSISTANT_ID", "assistant-uuid")
    monkeypatch.setenv("SUPABASE_CONTINUITY_ENABLED", "false")
    monkeypatch.setenv("EVENTIDE_CONTEXT_ENABLED", "false")
    settings = Settings.from_env()
    assert settings.supabase_ready
    assert not settings.supabase_continuity_ready
    assert not settings.eventide_context_ready


def test_gateway_auto_summary_needs_supabase_and_upstream(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://memory.example")
    monkeypatch.setenv("SUPABASE_KEY", "publishable-key")
    monkeypatch.setenv("ORANGECHAT_ASSISTANT_ID", "assistant-uuid")
    monkeypatch.setenv("UPSTREAM_API_KEY", "upstream-key")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "claude-model")
    monkeypatch.delenv("GATEWAY_AUTO_SUMMARY_ENABLED", raising=False)

    settings = Settings.from_env()
    assert settings.gateway_auto_summary_ready
    assert settings.gateway_summary_message_threshold == 24

    monkeypatch.setenv("GATEWAY_AUTO_SUMMARY_ENABLED", "false")
    assert not Settings.from_env().gateway_auto_summary_ready


def test_telegram_heartbeat_uses_sticky_defaults_and_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    monkeypatch.setenv("TELEGRAM_SYSTEM_PROMPT", "你是景行。")
    monkeypatch.setenv("UPSTREAM_API_KEY", "upstream-key")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "claude-model")
    monkeypatch.delenv("TELEGRAM_HEARTBEAT_ENABLED", raising=False)

    settings = Settings.from_env()
    assert settings.telegram_heartbeat_ready
    assert settings.telegram_heartbeat_silence_minutes == 60
    assert settings.telegram_heartbeat_cooldown_minutes == 90
    assert settings.telegram_heartbeat_strong_cooldown_minutes == 45
    assert settings.telegram_heartbeat_daily_limit == 10
    assert settings.telegram_heartbeat_quiet_start_hour == 6
    assert settings.telegram_heartbeat_quiet_end_hour == 9

    monkeypatch.setenv("TELEGRAM_HEARTBEAT_ENABLED", "false")
    assert not Settings.from_env().telegram_heartbeat_ready


def test_sleep_and_morning_health_defaults_are_bounded(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    monkeypatch.setenv("TELEGRAM_SYSTEM_PROMPT", "你是景行。")
    monkeypatch.setenv("UPSTREAM_API_KEY", "upstream-key")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "claude-model")
    monkeypatch.delenv("SLEEP_REMINDER_ENABLED", raising=False)
    monkeypatch.delenv("HEALTH_CONTEXT_ENABLED", raising=False)

    settings = Settings.from_env()
    assert settings.sleep_guidance_ready
    assert settings.telegram_sleep_reminder_ready
    assert settings.sleep_reminder_start_hour == 1
    assert settings.sleep_reminder_end_hour == 6
    assert settings.sleep_reminder_recent_activity_minutes == 30
    assert settings.sleep_reminder_followup_minutes == 60
    assert settings.sleep_reminder_max_per_night == 2
    assert settings.health_context_morning_start_hour == 6
    assert settings.health_context_morning_end_hour == 12
    assert settings.health_context_max_age_minutes == 45

    monkeypatch.setenv("SLEEP_REMINDER_ENABLED", "false")
    settings = Settings.from_env()
    assert not settings.sleep_guidance_ready
    assert not settings.telegram_sleep_reminder_ready


def test_device_perception_defaults_to_safe_shadow_mode(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://memory.example")
    monkeypatch.setenv("SUPABASE_KEY", "publishable-key")
    monkeypatch.setenv("ORANGECHAT_ASSISTANT_ID", "assistant-uuid")
    monkeypatch.delenv("DEVICE_PERCEPTION_ENABLED", raising=False)

    settings = Settings.from_env()
    assert settings.device_perception_ready
    assert settings.device_perception_timezone == "Asia/Taipei"
    assert settings.device_perception_check_seconds == 900
    assert settings.device_perception_cooldown_minutes == 180

    monkeypatch.setenv("DEVICE_PERCEPTION_ENABLED", "false")
    settings = Settings.from_env()
    assert not settings.device_perception_ready
    assert settings.health_context_ready
