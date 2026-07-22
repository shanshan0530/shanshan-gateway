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
