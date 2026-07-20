import pytest

from app.proxy import chat_completions_url, prepare_payload, public_error_message


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://relay.example", "https://relay.example/v1/chat/completions"),
        ("https://relay.example/", "https://relay.example/v1/chat/completions"),
        ("https://relay.example/v1", "https://relay.example/v1/chat/completions"),
        (
            "https://relay.example/v1/chat/completions",
            "https://relay.example/v1/chat/completions",
        ),
        (
            "https://relay.example/openai/v1",
            "https://relay.example/openai/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url(base, expected):
    assert chat_completions_url(base) == expected


@pytest.mark.parametrize("bad", ["", "relay.example", "ftp://relay.example"])
def test_chat_completions_url_rejects_invalid_base(bad):
    with pytest.raises(ValueError):
        chat_completions_url(bad)


def test_prepare_payload_maps_model_without_mutating_input():
    original = {
        "model": "friendly-name",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "tools": [{"type": "function", "function": {"name": "echo"}}],
    }
    prepared = prepare_payload(original, "claude-sonnet-real-name")
    assert prepared["model"] == "claude-sonnet-real-name"
    assert prepared["messages"] == original["messages"]
    assert prepared["tools"] == original["tools"]
    assert original["model"] == "friendly-name"


def test_public_error_message_is_bounded():
    assert public_error_message(500, b"x" * 3000) == "x" * 2000 + "…"
