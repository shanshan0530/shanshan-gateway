import asyncio

import httpx

from app.config import Settings
from app.summarizer import GatewayAutoSummarizer, _bounded_transcript
from app.supabase import SummaryBatch


def summary_settings(**overrides):
    values = {
        "gateway_api_key": "gateway-secret",
        "upstream_api_key": "upstream-secret",
        "upstream_base_url": "https://relay.example/v1",
        "upstream_model": "claude-model",
        "public_model_name": "friendly",
        "request_timeout_seconds": 300,
        "max_request_bytes": 10 * 1024 * 1024,
        "supabase_url": "https://memory.example",
        "supabase_key": "publishable-key",
        "orangechat_assistant_id": "orange-uuid",
        "gateway_summary_message_threshold": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_bounded_transcript_keeps_roles_and_limits_content():
    transcript = _bounded_transcript(
        (
            {"role": "system", "content": "不应包含"},
            {"role": "user", "content": "甲" * 20},
            {"role": "assistant", "content": "乙" * 20},
        ),
        max_chars=28,
        per_message_chars=10,
    )
    assert "system" not in transcript
    assert transcript.startswith("[user] " + "甲" * 10)
    assert len(transcript) <= 28


def test_auto_summarizer_generates_and_stores_complete_batch():
    batch = SummaryBatch(
        conversation_id="gw:orange-island:abc",
        expected_last_message_id=0,
        last_message_id=2,
        messages=(
            {"id": 1, "role": "user", "content": "今天接通了新 App"},
            {"id": 2, "role": "assistant", "content": "我还记得你"},
        ),
    )

    class FakeSupabase:
        def __init__(self):
            self.stored = []

        async def summary_batch(self, *, conversation_id):
            assert conversation_id == batch.conversation_id
            return batch

        async def store_memory_summary(self, **kwargs):
            self.stored.append(kwargs)
            return True

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "新 App 已接通跨端记忆。"}}
                ]
            },
        )

    supabase = FakeSupabase()
    summarizer = GatewayAutoSummarizer(
        summary_settings(),
        supabase,
        transport=httpx.MockTransport(handler),
    )
    assert asyncio.run(summarizer.maybe_summarize(batch.conversation_id)) is True
    assert supabase.stored[0]["batch"] == batch
    assert supabase.stored[0]["content"] == "新 App 已接通跨端记忆。"


def test_auto_summarizer_ignores_non_gateway_conversations():
    class NeverCalledSupabase:
        async def summary_batch(self, **kwargs):
            raise AssertionError("must not read OrangeChat-native conversations")

    summarizer = GatewayAutoSummarizer(
        summary_settings(),
        NeverCalledSupabase(),
    )
    assert asyncio.run(summarizer.maybe_summarize("orangechat-native")) is False
