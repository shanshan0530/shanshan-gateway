from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_HEALTH_CHANGE_TOLERANCES: dict[str, float] = {
    "heartRate": 15.0,
    "spo2": 3.0,
    "stress": 20.0,
    "sleepTotalMinutes": 30.0,
}


@dataclass(frozen=True, repr=False)
class DeviceSnapshot:
    """Internal device sample. Its repr deliberately excludes sensitive values."""

    row_id: int
    captured_at: datetime | None
    foreground_app: str = field(default="", repr=False)
    latitude: float | None = field(default=None, repr=False)
    longitude: float | None = field(default=None, repr=False)
    address: str = field(default="", repr=False)
    city: str = field(default="", repr=False)
    district: str = field(default="", repr=False)
    street: str = field(default="", repr=False)
    app_usage: dict[str, Any] = field(default_factory=dict, repr=False)
    notifications: dict[str, Any] = field(default_factory=dict, repr=False)
    device_event: str = field(default="", repr=False)
    health: dict[str, float] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        return (
            "DeviceSnapshot("
            f"row_id={self.row_id}, captured_at={self.captured_at!r}, "
            f"has_location={self.latitude is not None and self.longitude is not None}, "
            f"has_health={bool(self.health)})"
        )


@dataclass(frozen=True)
class PerceptionEvent:
    """Privacy-safe delta that may later be consumed by the intent engine."""

    kind: str
    severity: str
    summary: str
    fingerprint: str
    occurred_at: datetime | None
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class PerceptionScan:
    latest_row_id: int
    captured_at: datetime | None
    events: tuple[PerceptionEvent, ...]


def parse_device_snapshot(
    row: dict[str, Any],
    *,
    timezone_name: str = "Asia/Taipei",
) -> DeviceSnapshot:
    health_payload = _decode_json_object(row.get("health_data"))
    health = {
        key: value
        for key, raw in health_payload.items()
        if (value := _finite_number(raw)) is not None
    }
    return DeviceSnapshot(
        row_id=_safe_int(row.get("id")),
        captured_at=_parse_local_datetime(row.get("timestamp"), timezone_name),
        foreground_app=_bounded_text(row.get("foreground_app")),
        latitude=_coordinate(row.get("location_latitude"), latitude=True),
        longitude=_coordinate(row.get("location_longitude"), latitude=False),
        address=_bounded_text(row.get("location_address")),
        city=_bounded_text(row.get("location_city")),
        district=_bounded_text(row.get("location_district")),
        street=_bounded_text(row.get("location_street")),
        app_usage=_decode_json_object(row.get("app_usage")),
        notifications=_decode_json_object(row.get("notifications")),
        device_event=_bounded_text(row.get("device_event")),
        health=health,
    )


def derive_perception_events(
    previous: DeviceSnapshot,
    current: DeviceSnapshot,
    *,
    fingerprint_key: str = "",
) -> tuple[PerceptionEvent, ...]:
    """Turn two raw samples into bounded events that contain no raw private data."""

    if current.row_id <= previous.row_id:
        return ()

    events: list[PerceptionEvent] = []
    if _location_changed(previous, current):
        events.append(
            _event(
                current,
                kind="location_changed",
                severity="normal",
                summary="设备位置状态发生了有意义的变化。",
                private_state=_location_state(current),
                fingerprint_key=fingerprint_key,
            )
        )

    if (
        previous.foreground_app
        and current.foreground_app
        and previous.foreground_app != current.foreground_app
    ):
        events.append(
            _event(
                current,
                kind="app_context_changed",
                severity="info",
                summary="设备当前使用情境发生了变化。",
                private_state=current.foreground_app,
                fingerprint_key=fingerprint_key,
            )
        )

    if current.device_event and current.device_event != previous.device_event:
        events.append(
            _event(
                current,
                kind="device_event",
                severity="normal",
                summary="设备报告了一个新的状态事件。",
                private_state=current.device_event,
                fingerprint_key=fingerprint_key,
            )
        )

    changed_health = _changed_health_fields(previous.health, current.health)
    if changed_health:
        private_state = "|".join(
            f"{key}:{_health_bucket(key, current.health[key])}"
            for key in changed_health
        )
        events.append(
            _event(
                current,
                kind="health_sample_changed",
                severity="info",
                summary="可穿戴设备的健康采样出现了值得重新评估的变化。",
                private_state=private_state,
                fingerprint_key=fingerprint_key,
                changed_fields=changed_health,
            )
        )

    return tuple(events)


def _event(
    snapshot: DeviceSnapshot,
    *,
    kind: str,
    severity: str,
    summary: str,
    private_state: str,
    fingerprint_key: str,
    changed_fields: tuple[str, ...] = (),
) -> PerceptionEvent:
    payload = f"{kind}\0{private_state}".encode("utf-8")
    digest = (
        hmac.new(fingerprint_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if fingerprint_key
        else hashlib.sha256(payload).hexdigest()
    )
    return PerceptionEvent(
        kind=kind,
        severity=severity,
        summary=summary,
        fingerprint=digest,
        occurred_at=snapshot.captured_at,
        changed_fields=changed_fields,
    )


def _decode_json_object(value: Any) -> dict[str, Any]:
    current = value
    for _ in range(3):
        if isinstance(current, dict):
            return dict(current)
        if not isinstance(current, str) or not current.strip():
            return {}
        try:
            current = json.loads(current)
        except (json.JSONDecodeError, TypeError):
            return {}
    return dict(current) if isinstance(current, dict) else {}


def _parse_local_datetime(value: Any, timezone_name: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            local_timezone = timezone.utc
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(timezone.utc)


def _location_changed(previous: DeviceSnapshot, current: DeviceSnapshot) -> bool:
    for old, new in (
        (previous.city, current.city),
        (previous.district, current.district),
        (previous.street, current.street),
    ):
        if old and new and old != new:
            return True
    distance = _distance_metres(previous, current)
    return distance is not None and distance >= 750.0


def _distance_metres(
    previous: DeviceSnapshot,
    current: DeviceSnapshot,
) -> float | None:
    coordinates = (
        previous.latitude,
        previous.longitude,
        current.latitude,
        current.longitude,
    )
    if any(value is None for value in coordinates):
        return None
    lat1, lon1, lat2, lon2 = (math.radians(float(value)) for value in coordinates)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return 6_371_000.0 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _location_state(snapshot: DeviceSnapshot) -> str:
    semantic = "|".join(
        part for part in (snapshot.city, snapshot.district, snapshot.street) if part
    )
    if semantic:
        return semantic
    if snapshot.latitude is not None and snapshot.longitude is not None:
        return f"{snapshot.latitude:.3f}|{snapshot.longitude:.3f}"
    return "changed"


def _changed_health_fields(
    previous: dict[str, float],
    current: dict[str, float],
) -> tuple[str, ...]:
    changed = []
    for key, tolerance in _HEALTH_CHANGE_TOLERANCES.items():
        if key not in previous or key not in current:
            continue
        if abs(current[key] - previous[key]) >= tolerance:
            changed.append(key)
    return tuple(changed)


def _health_bucket(key: str, value: float) -> int:
    tolerance = _HEALTH_CHANGE_TOLERANCES[key]
    return math.floor(value / tolerance)


def _coordinate(value: Any, *, latitude: bool) -> float | None:
    number = _finite_number(value)
    limit = 90.0 if latitude else 180.0
    if number is None or not -limit <= number <= limit:
        return None
    return number


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _bounded_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:1000]
