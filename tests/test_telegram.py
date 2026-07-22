import asyncio
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.supabase import HeartbeatSignal
from app.telegram import (
    TelegramBridge,
    _content_to_text,
    _is_quiet_hour,
    _split_telegram_text,
)


def test_content_to_text_supports_openai_text_parts():
    assert _content_to_text([{"type": "text", "text": "第一段"}, {"text": "第二段"}]) == "第一段\n第二段"


def test_split_telegram_text_preserves_all_content():
    text = "第一行\n" + ("小狐狸" * 2000)
    parts = _split_telegram_text(text, limit=500)
    assert len(parts) > 1
    assert all(len(part) <= 500 for part in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_bridge_reads_persisted_history_after_recreation(tmp_path):
    settings = Settings(
        gateway_api_key="gateway",
        upstream_api_key="upstream",
        upstream_base_url="https://relay.example/v1",
        upstream_model="model",
        public_model_name="public",
        request_timeout_seconds=300,
        max_request_bytes=1024,
        telegram_db_path=str(tmp_path / "telegram.sqlite3"),
    )
    first = TelegramBridge(settings)
    first._remember("123", "user", "记住这一句")

    reopened = TelegramBridge(settings)
    assert reopened._recent_history("123") == [
        {"role": "user", "content": "记住这一句"}
    ]


def heartbeat_settings(tmp_path, **overrides):
    values = {
        "gateway_api_key": "gateway",
        "upstream_api_key": "upstream",
        "upstream_base_url": "https://relay.example/v1",
        "upstream_model": "model",
        "public_model_name": "public",
        "request_timeout_seconds": 300,
        "max_request_bytes": 1024,
        "telegram_bot_token": "bot-token",
        "telegram_allowed_user_id": "123",
        "telegram_system_prompt": "你是景行。",
        "telegram_db_path": str(tmp_path / "telegram.sqlite3"),
        "supabase_url": "https://memory.example",
        "supabase_key": "publishable-key",
        "orangechat_assistant_id": "assistant-id",
        "eventide_assistant_id": "景行",
    }
    values.update(overrides)
    return Settings(**values)


def test_quiet_hours_support_normal_and_wrapped_ranges():
    assert _is_quiet_hour(6, 6, 9)
    assert not _is_quiet_hour(9, 6, 9)
    assert _is_quiet_hour(23, 22, 7)
    assert _is_quiet_hour(3, 22, 7)
    assert not _is_quiet_hour(12, 22, 7)


def test_heartbeat_sends_after_silence_and_persists_count(tmp_path):
    bridge = TelegramBridge(heartbeat_settings(tmp_path))
    now = datetime(2026, 7, 23, 5, 0, tzinfo=timezone.utc)  # 13:00 Taipei
    sent = []
    stored = []

    async def latest_user_activity():
        return now - timedelta(hours=2)

    async def heartbeat_signal():
        return HeartbeatSignal(False, False)

    async def complete(chat_id):
        assert chat_id == "123"
        return "主动来找你。"

    async def push(text):
        sent.append(text)

    async def store_message(**kwargs):
        stored.append(kwargs)
        return True

    bridge._supabase.latest_user_activity = latest_user_activity
    bridge._supabase.heartbeat_signal = heartbeat_signal
    bridge._supabase.store_message = store_message
    bridge._complete_heartbeat = complete
    bridge.push = push

    assert asyncio.run(bridge._heartbeat_once(now=now)) is True
    assert sent == ["主动来找你。"]
    assert stored[0]["conversation_id"] == "tg:123"
    state = bridge._heartbeat_state("123")
    assert state.daily_count == 1
    assert state.last_sent_at == now
    assert bridge._recent_history("123")[-1] == {
        "role": "assistant",
        "content": "主动来找你。",
    }


def test_heartbeat_respects_recent_activity_and_quiet_hours(tmp_path):
    now = datetime(2026, 7, 22, 22, 30, tzinfo=timezone.utc)  # 06:30 Taipei
    bridge = TelegramBridge(heartbeat_settings(tmp_path))

    async def latest_user_activity():
        return now - timedelta(hours=3)

    async def must_not_complete(chat_id):
        raise AssertionError("quiet hours must skip generation")

    bridge._supabase.latest_user_activity = latest_user_activity
    bridge._complete_heartbeat = must_not_complete
    assert asyncio.run(bridge._heartbeat_once(now=now)) is False

    active_now = datetime(2026, 7, 23, 5, 0, tzinfo=timezone.utc)

    async def recent_activity():
        return active_now - timedelta(minutes=30)

    bridge._supabase.latest_user_activity = recent_activity
    assert asyncio.run(bridge._heartbeat_once(now=active_now)) is False
