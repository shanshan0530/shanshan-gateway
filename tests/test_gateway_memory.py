from app.gateway_memory import (
    GatewayMemoryRequest,
    OpenAIStreamTextCollector,
    extract_response_text,
)


def test_full_mode_builds_stable_conversation_across_turns():
    first = GatewayMemoryRequest.from_payload(
        {
            "messages": [
                {"role": "system", "content": "角色"},
                {"role": "user", "content": "你好"},
            ]
        },
        {"x-memory-mode": "full", "x-client-name": "Orange Island"},
    )
    later = GatewayMemoryRequest.from_payload(
        {
            "messages": [
                {"role": "system", "content": "角色"},
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好。"},
                {"role": "user", "content": "我回来啦"},
            ]
        },
        {"x-memory-mode": "full", "x-client-name": "Orange Island"},
    )

    assert first.enabled
    assert first.client_name == "orange-island"
    assert first.conversation_id == later.conversation_id
    assert later.user_text == "我回来啦"
    assert first.transcript_fingerprint != later.transcript_fingerprint


def test_explicit_conversation_id_is_hashed_not_stored_verbatim():
    request = GatewayMemoryRequest.from_payload(
        {"messages": [{"role": "user", "content": "hello"}]},
        {
            "x-memory-mode": "full",
            "x-client-name": "new-app",
            "x-conversation-id": "private-thread-name",
        },
    )
    assert request.conversation_id.startswith("gw:new-app:")
    assert "private-thread-name" not in request.conversation_id


def test_memory_mode_is_opt_in():
    request = GatewayMemoryRequest.from_payload(
        {"messages": [{"role": "user", "content": "hello"}]},
        {"x-client-name": "orangechat"},
    )
    assert not request.enabled


def test_stream_collector_handles_split_sse_chunks():
    collector = OpenAIStreamTextCollector()
    collector.feed('data: {"choices":[{"delta":{"content":"你'.encode())
    collector.feed('好"}}]}\n\n'.encode())
    collector.feed(
        'data: {"choices":[{"delta":{"content":"，珊珊"}}]}\n'.encode()
    )
    collector.feed(b"data: [DONE]\n\n")
    assert collector.finish() == "你好，珊珊"


def test_extract_non_streaming_openai_response_text():
    raw = (
        b'{"choices":[{"message":{"role":"assistant","content":'
        b'[{"type":"text","text":"first"},{"type":"text","text":" second"}]}}]}'
    )
    assert extract_response_text(raw) == "first second"


def test_different_regenerated_answers_have_different_fingerprints():
    request = GatewayMemoryRequest.from_payload(
        {"messages": [{"role": "user", "content": "hello"}]},
        {"x-memory-mode": "full"},
    )
    assert request.message_fingerprint(
        "assistant", "first answer"
    ) != request.message_fingerprint("assistant", "second answer")
