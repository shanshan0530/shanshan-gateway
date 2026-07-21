from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import Settings
from app import main


def configured_settings(**overrides):
    values = {
        "gateway_api_key": "gateway-secret",
        "upstream_api_key": "upstream-secret",
        "upstream_base_url": "https://relay.example/v1",
        "upstream_model": "claude-real-name",
        "public_model_name": "shanshan-claude",
        "request_timeout_seconds": 300,
        "max_request_bytes": 10 * 1024 * 1024,
    }
    values.update(overrides)
    return Settings(**values)


def test_health_is_ready_without_exposing_upstream_path_or_key(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.3.0",
        "missing_env": [],
        "upstream_url_valid": True,
        "upstream_host": "relay.example",
        "telegram": {"enabled": False, "authorized": False},
    }
    assert "upstream-secret" not in response.text


def test_models_requires_gateway_key(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    client = TestClient(main.app)
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer gateway-secret"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "shanshan-claude"


def test_chat_maps_model_and_preserves_openai_fields(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    captured = {}

    async def fake_forward(payload):
        captured.update(payload)
        return JSONResponse({"ok": True})

    monkeypatch.setattr(main, "forward_to_upstream", fake_forward)
    response = TestClient(main.app).post(
        "/v1/chat/completions",
        headers={"X-API-Key": "gateway-secret"},
        json={
            "model": "friendly-name",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "echo"}}],
        },
    )
    assert response.status_code == 200
    assert captured["model"] == "claude-real-name"
    assert captured["stream"] is True
    assert captured["tools"][0]["function"]["name"] == "echo"


def test_chat_rejects_missing_messages(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    response = TestClient(main.app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={"model": "friendly-name"},
    )
    assert response.status_code == 400


def test_telegram_push_requires_gateway_auth(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    client = TestClient(main.app)
    assert client.post("/api/telegram/push", json={"text": "hello"}).status_code == 401


def test_telegram_push_sends_to_private_user(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    sent = []

    async def fake_push(text):
        sent.append(text)

    monkeypatch.setattr(main.telegram_bridge, "push", fake_push)
    response = TestClient(main.app).post(
        "/api/telegram/push",
        headers={"Authorization": "Bearer gateway-secret"},
        json={"text": "主动消息测试"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert sent == ["主动消息测试"]
