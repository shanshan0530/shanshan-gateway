import json
from datetime import datetime, timezone

from app.perception import derive_perception_events, parse_device_snapshot


def test_snapshot_decodes_double_encoded_json_and_local_timestamp():
    snapshot = parse_device_snapshot(
        {
            "id": 12,
            "timestamp": "2026-07-23 02:15:00",
            "foreground_app": "private.app",
            "location_latitude": 25.03,
            "location_longitude": 121.56,
            "location_address": "private address",
            "app_usage": json.dumps({"private.app": 120}),
            "notifications": json.dumps({"private": "message"}),
            "health_data": json.dumps(
                {"heartRate": 80, "spo2": None, "invalid": "unknown"}
            ),
        }
    )

    assert snapshot.captured_at == datetime(
        2026, 7, 22, 18, 15, tzinfo=timezone.utc
    )
    assert snapshot.health == {"heartRate": 80.0}
    assert snapshot.app_usage == {"private.app": 120}
    assert snapshot.notifications == {"private": "message"}


def test_snapshot_repr_never_contains_private_values():
    snapshot = parse_device_snapshot(
        {
            "id": 13,
            "timestamp": "2026-07-23 02:30:00",
            "foreground_app": "secret.app",
            "location_latitude": 25.03,
            "location_longitude": 121.56,
            "location_address": "secret address",
            "health_data": json.dumps({"heartRate": 88}),
        }
    )

    rendered = repr(snapshot)
    assert "secret.app" not in rendered
    assert "secret address" not in rendered
    assert "121.56" not in rendered
    assert "88" not in rendered
    assert "has_location=True" in rendered
    assert "has_health=True" in rendered


def test_events_are_semantic_and_do_not_leak_raw_device_data():
    previous = parse_device_snapshot(
        {
            "id": 20,
            "timestamp": "2026-07-23 02:30:00",
            "foreground_app": "old.private.app",
            "location_city": "private city",
            "location_district": "old private district",
            "device_event": "old private event",
            "health_data": json.dumps({"heartRate": 70, "stress": 20}),
        }
    )
    current = parse_device_snapshot(
        {
            "id": 21,
            "timestamp": "2026-07-23 02:45:00",
            "foreground_app": "new.private.app",
            "location_city": "private city",
            "location_district": "new private district",
            "device_event": "new private event",
            "health_data": json.dumps({"heartRate": 90, "stress": 45}),
        }
    )

    events = derive_perception_events(
        previous, current, fingerprint_key="unit-test-secret"
    )
    assert {event.kind for event in events} == {
        "location_changed",
        "app_context_changed",
        "device_event",
        "health_sample_changed",
    }
    assert all(len(event.fingerprint) == 64 for event in events)
    rendered = repr(events)
    for private_value in (
        "private city",
        "old private district",
        "new private district",
        "old.private.app",
        "new.private.app",
        "new private event",
    ):
        assert private_value not in rendered
    summaries = "\n".join(event.summary for event in events)
    assert "heartRate" not in summaries
    assert "stress" not in summaries
    assert "90" not in summaries
    assert "45" not in summaries


def test_invalid_or_replayed_samples_fail_closed():
    previous = parse_device_snapshot(
        {"id": "bad", "timestamp": "not-a-date", "health_data": "not-json"}
    )
    current = parse_device_snapshot(
        {"id": 0, "timestamp": "", "location_latitude": "nan"}
    )
    assert previous.captured_at is None
    assert previous.health == {}
    assert derive_perception_events(
        previous, current, fingerprint_key="unit-test-secret"
    ) == ()
