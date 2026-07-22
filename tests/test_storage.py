from datetime import datetime, timedelta, timezone

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


def test_heartbeat_state_persists_toggle_count_and_timestamp(tmp_path):
    db_path = tmp_path / "telegram.sqlite3"
    store = ConversationStore(str(db_path))
    assert store.heartbeat_state("123", default_enabled=True).enabled

    store.set_heartbeat_enabled("123", False)
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    recorded = store.record_heartbeat_sent(
        "123",
        sent_at=sent_at,
        local_date="2026-07-23",
        default_enabled=True,
    )
    assert not recorded.enabled
    assert recorded.daily_count == 1

    reopened = ConversationStore(str(db_path))
    state = reopened.heartbeat_state("123", default_enabled=True)
    assert not state.enabled
    assert state.daily_date == "2026-07-23"
    assert state.daily_count == 1
    assert state.last_sent_at is not None


def test_last_message_at_returns_latest_role_timestamp(tmp_path):
    store = ConversationStore(str(tmp_path / "telegram.sqlite3"))
    assert store.last_message_at("123", "user") is None
    store.append("123", "user", "你好")
    assert store.last_message_at("123", "user") is not None
    assert store.last_message_at("123", "assistant") is None


def test_perception_shadow_state_persists_checkpoint_and_cooldown(tmp_path):
    db_path = tmp_path / "telegram.sqlite3"
    store = ConversationStore(str(db_path))
    first_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)

    state, eligible, processed = store.record_perception_scan(
        latest_row_id=10,
        events=(("location_changed", "fingerprint-a"),),
        checked_at=first_at,
        cooldown_minutes=180,
    )
    assert processed
    assert eligible == ("location_changed",)
    assert state.total_scans == 1
    assert state.total_detected_events == 1
    assert state.total_eligible_events == 1

    duplicate, eligible, processed = store.record_perception_scan(
        latest_row_id=10,
        events=(("location_changed", "fingerprint-a"),),
        checked_at=first_at + timedelta(minutes=15),
        cooldown_minutes=180,
    )
    assert not processed
    assert eligible == ()
    assert duplicate.total_scans == 1

    suppressed, eligible, processed = store.record_perception_scan(
        latest_row_id=11,
        events=(("location_changed", "fingerprint-a"),),
        checked_at=first_at + timedelta(minutes=30),
        cooldown_minutes=180,
    )
    assert processed
    assert eligible == ()
    assert suppressed.total_scans == 2
    assert suppressed.total_detected_events == 2
    assert suppressed.total_eligible_events == 1

    released, eligible, processed = store.record_perception_scan(
        latest_row_id=12,
        events=(("location_changed", "fingerprint-a"),),
        checked_at=first_at + timedelta(hours=4),
        cooldown_minutes=180,
    )
    assert processed
    assert eligible == ("location_changed",)
    assert released.total_eligible_events == 2

    reopened = ConversationStore(str(db_path)).perception_shadow_state()
    assert reopened.last_row_id == 12
    assert reopened.total_scans == 3
    assert reopened.event_counts == {"location_changed": 3}
