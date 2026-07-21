from app.storage import ConversationStore


def test_conversation_store_survives_new_instance(tmp_path):
    db_path = tmp_path / "telegram.sqlite3"
    first = ConversationStore(str(db_path), max_messages_per_chat=10)
    first.append("123", "user", "第一句")
    first.append("123", "assistant", "第二句")

    reopened = ConversationStore(str(db_path), max_messages_per_chat=10)
    assert reopened.recent("123", 10) == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "第二句"},
    ]


def test_conversation_store_prunes_and_clears(tmp_path):
    store = ConversationStore(
        str(tmp_path / "telegram.sqlite3"), max_messages_per_chat=3
    )
    for index in range(5):
        store.append("123", "user", f"消息{index}")

    assert [row["content"] for row in store.recent("123", 10)] == [
        "消息2",
        "消息3",
        "消息4",
    ]
    store.clear("123")
    assert store.recent("123", 10) == []
