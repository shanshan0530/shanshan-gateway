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
