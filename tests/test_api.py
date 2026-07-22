import asyncio

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway_memory import GatewayMemoryRequest
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
        "version": "0.7.0",
        "missing_env": [],
        "upstream_url_valid": True,
        "upstream_host": "relay.example",
        "telegram": {"enabled": False, "authorized": False},
        "ombre_recall": {"enabled": False, "ready": False},
        "supabase": {
            "ready": False,
            "continuity": False,
            "eventide_context": False,
        },
        "gateway_memory": {
            "available": False,
            "mode_header": "X-Memory-Mode: full",
            "base_url_path": "/memory/v1",
            "auto_summary": False,
            "summary_message_threshold": 24,
        },
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

    async def fake_forward(payload, **kwargs):
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


def test_chat_injects_eventide_context_before_upstream(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    captured = {}

    async def fake_eventide_context():
        return '<ephemeral_state kind="eventide">状态底色</ephemeral_state>'

    async def fake_forward(payload, **kwargs):
        captured.update(payload)
        return JSONResponse({"ok": True})

    monkeypatch.setattr(main.supabase_bridge, "eventide_context", fake_eventide_context)
    monkeypatch.setattr(main, "forward_to_upstream", fake_forward)
    response = TestClient(main.app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={
            "model": "friendly-name",
            "messages": [
                {"role": "system", "content": "角色设定"},
                {"role": "user", "content": "hello"},
            ],
        },
    )

    assert response.status_code == 200
    assert [message["role"] for message in captured["messages"]] == [
        "system",
        "system",
        "user",
    ]
    assert "状态底色" in captured["messages"][1]["content"]


def test_full_memory_mode_archives_user_and_injects_all_contexts(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    stored = []
    captured = {}

    async def fake_store_message(**kwargs):
        stored.append(kwargs)
        return True

    async def fake_continuity_context(**kwargs):
        return "SUPABASE-CONTINUITY"

    async def fake_eventide_context():
        return "EVENTIDE-STATE"

    async def fake_recall(query):
        assert query == "想起我们昨天聊的事"
        return "OMBRE-RECALL"

    async def fake_forward(payload, **kwargs):
        captured["payload"] = payload
        captured["memory_request"] = kwargs.get("memory_request")
        return JSONResponse({"ok": True})

    monkeypatch.setattr(main.supabase_bridge, "store_message", fake_store_message)
    monkeypatch.setattr(
        main.supabase_bridge, "continuity_context", fake_continuity_context
    )
    monkeypatch.setattr(main.supabase_bridge, "eventide_context", fake_eventide_context)
    monkeypatch.setattr(main.ombre_recall, "recall", fake_recall)
    monkeypatch.setattr(main, "forward_to_upstream", fake_forward)

    response = TestClient(main.app).post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer gateway-secret",
            "X-Memory-Mode": "full",
            "X-Client-Name": "orange-island",
            "X-Conversation-ID": "thread-123",
        },
        json={
            "model": "friendly-name",
            "messages": [
                {"role": "system", "content": "角色设定"},
                {"role": "user", "content": "想起我们昨天聊的事"},
            ],
        },
    )

    assert response.status_code == 200
    assert stored[0]["role"] == "user"
    assert stored[0]["content"] == "想起我们昨天聊的事"
    assert stored[0]["conversation_id"].startswith("gw:orange-island:")
    assert len(stored[0]["fingerprint"]) == 64
    contents = [message["content"] for message in captured["payload"]["messages"]]
    assert contents == [
        "角色设定",
        "SUPABASE-CONTINUITY",
        main.format_memory_context("OMBRE-RECALL"),
        "EVENTIDE-STATE",
        "想起我们昨天聊的事",
    ]
    assert captured["memory_request"].enabled


def test_memory_base_url_enables_full_mode_without_custom_headers(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    stored = []
    captured = {}

    async def fake_store_message(**kwargs):
        stored.append(kwargs)
        return True

    async def fake_context(**kwargs):
        return ""

    async def fake_recall(query):
        return ""

    async def fake_forward(payload, **kwargs):
        captured["memory_request"] = kwargs.get("memory_request")
        return JSONResponse({"ok": True})

    monkeypatch.setattr(main.supabase_bridge, "store_message", fake_store_message)
    monkeypatch.setattr(main.supabase_bridge, "continuity_context", fake_context)
    monkeypatch.setattr(main.supabase_bridge, "eventide_context", fake_context)
    monkeypatch.setattr(main.ombre_recall, "recall", fake_recall)
    monkeypatch.setattr(main, "forward_to_upstream", fake_forward)

    response = TestClient(main.app).post(
        "/memory/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={
            "model": "friendly-name",
            "messages": [{"role": "user", "content": "新家也要记得我"}],
        },
    )

    assert response.status_code == 200
    assert stored[0]["role"] == "user"
    assert stored[0]["conversation_id"].startswith("gw:orange-island:")
    assert captured["memory_request"].enabled
    assert captured["memory_request"].client_name == "orange-island"


def test_memory_base_url_lists_models(monkeypatch):
    monkeypatch.setattr(main, "settings", configured_settings())
    response = TestClient(main.app).get(
        "/memory/v1/models",
        headers={"Authorization": "Bearer gateway-secret"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "shanshan-claude"


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


def test_stream_completion_is_archived_after_normal_finish(monkeypatch):
    stored = []

    class FakeResponse:
        async def aiter_raw(self):
            yield 'data: {"choices":[{"delta":{"content":"回来"}}]}\n'.encode()
            yield 'data: {"choices":[{"delta":{"content":"了。"}}]}\n\n'.encode()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            return None

    class FakeClient:
        async def aclose(self):
            return None

    async def fake_store_message(**kwargs):
        stored.append(kwargs)
        return True

    request = GatewayMemoryRequest.from_payload(
        {"messages": [{"role": "user", "content": "我回来啦"}]},
        {"x-memory-mode": "full", "x-client-name": "new-app"},
    )
    monkeypatch.setattr(main.supabase_bridge, "store_message", fake_store_message)

    async def consume():
        return [
            chunk
            async for chunk in main._stream_and_close(
                FakeResponse(), FakeClient(), request
            )
        ]

    chunks = asyncio.run(consume())
    assert b"".join(chunks).endswith(b"data: [DONE]\n\n")
    assert stored[0]["role"] == "assistant"
    assert stored[0]["content"] == "回来了。"
    assert stored[0]["conversation_id"].startswith("gw:new-app:")
    assert len(stored[0]["fingerprint"]) == 64
