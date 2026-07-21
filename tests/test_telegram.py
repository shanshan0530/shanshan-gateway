from app.config import Settings
from app.telegram import TelegramBridge, _content_to_text, _split_telegram_text


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
