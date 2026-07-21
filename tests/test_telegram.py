from app.telegram import _content_to_text, _split_telegram_text


def test_content_to_text_supports_openai_text_parts():
    assert _content_to_text([{"type": "text", "text": "第一段"}, {"text": "第二段"}]) == "第一段\n第二段"


def test_split_telegram_text_preserves_all_content():
    text = "第一行\n" + ("小狐狸" * 2000)
    parts = _split_telegram_text(text, limit=500)
    assert len(parts) > 1
    assert all(len(part) <= 500 for part in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
