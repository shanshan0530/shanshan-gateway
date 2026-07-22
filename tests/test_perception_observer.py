import asyncio
from datetime import datetime, timezone

from app.config import Settings
from app.perception import PerceptionEvent, PerceptionScan
from app.perception_observer import PerceptionObserver
from app.storage import ConversationStore


def observer_settings(tmp_path):
    return Settings(
        gateway_api_key="gateway-secret",
        upstream_api_key="upstream-secret",
        upstream_base_url="https://relay.example/v1",
        upstream_model="model",
        public_model_name="public",
        request_timeout_seconds=300,
        max_request_bytes=1024,
        supabase_url="https://memory.example",
        supabase_key="publishable-key",
        orangechat_assistant_id="assistant-id",
        device_perception_enabled=True,
        device_perception_db_path=str(tmp_path / "telegram.sqlite3"),
    )


def test_shadow_observer_records_only_safe_event_metadata(tmp_path):
    occurred_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)
    scan = PerceptionScan(
        latest_row_id=50,
        captured_at=occurred_at,
        events=(
            PerceptionEvent(
                kind="location_changed",
                severity="normal",
                summary="设备位置状态发生了有意义的变化。",
                fingerprint="a" * 64,
                occurred_at=occurred_at,
            ),
        ),
    )

    class FakeBridge:
        async def perception_scan(self):
            return scan

    store = ConversationStore(str(tmp_path / "telegram.sqlite3"))
    observer = PerceptionObserver(
        observer_settings(tmp_path), FakeBridge(), store=store
    )
    state, eligible = asyncio.run(observer.observe_once(now=occurred_at))

    assert state is not None
    assert state.last_row_id == 50
    assert eligible == ("location_changed",)
    assert state.event_counts == {"location_changed": 1}

    reopened = PerceptionObserver(
        observer_settings(tmp_path), FakeBridge(),
        store=ConversationStore(str(tmp_path / "telegram.sqlite3")),
    )
    replay_state, replay_eligible = asyncio.run(
        reopened.observe_once(now=occurred_at)
    )
    assert replay_state is not None
    assert replay_state.total_scans == 1
    assert replay_eligible == ()


def test_shadow_observer_does_nothing_when_disabled(tmp_path):
    class MustNotCall:
        async def perception_scan(self):
            raise AssertionError("disabled observer must not query Supabase")

    settings = observer_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "device_perception_enabled": False})
    observer = PerceptionObserver(settings, MustNotCall())
    assert asyncio.run(observer.observe_once()) == (None, ())
