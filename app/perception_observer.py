from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

from .config import Settings
from .storage import ConversationStore, PerceptionShadowState
from .supabase import SupabaseBridge


logger = logging.getLogger("shanshan-gateway.perception")


class PerceptionObserver:
    """Observe normalized device deltas without injecting or sending anything."""

    def __init__(
        self,
        settings: Settings,
        bridge: SupabaseBridge,
        *,
        store: ConversationStore | None = None,
    ) -> None:
        self.settings = settings
        self.bridge = bridge
        self._store = store
        self._store_unavailable = False

    async def run(self) -> None:
        await asyncio.sleep(min(30, self.settings.device_perception_check_seconds))
        while True:
            try:
                await self.observe_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("perception shadow scan failed: %s", type(exc).__name__)
            await asyncio.sleep(self.settings.device_perception_check_seconds)

    async def observe_once(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[PerceptionShadowState | None, tuple[str, ...]]:
        if not self.settings.device_perception_ready:
            return None, ()
        scan = await self.bridge.perception_scan()
        if scan is None:
            return None, ()
        store = self._state_store()
        if store is None:
            return None, ()
        checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            state, eligible, processed = store.record_perception_scan(
                latest_row_id=scan.latest_row_id,
                events=((event.kind, event.fingerprint) for event in scan.events),
                checked_at=checked_at,
                cooldown_minutes=self.settings.device_perception_cooldown_minutes,
            )
        except (OSError, sqlite3.Error):
            self._mark_store_unavailable()
            return None, ()
        if processed:
            logger.info(
                "perception shadow row=%d detected=%d eligible=%d kinds=%s",
                scan.latest_row_id,
                len(scan.events),
                len(eligible),
                ",".join(sorted(set(eligible))) or "none",
            )
        return state, eligible

    def status(self) -> PerceptionShadowState | None:
        if not self.settings.device_perception_ready:
            return None
        store = self._state_store()
        if store is None:
            return None
        try:
            return store.perception_shadow_state()
        except (OSError, sqlite3.Error):
            self._mark_store_unavailable()
            return None

    def _state_store(self) -> ConversationStore | None:
        if self._store_unavailable:
            return None
        if self._store is None:
            try:
                self._store = ConversationStore(
                    self.settings.device_perception_db_path,
                    self.settings.telegram_max_stored_messages,
                )
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
                return None
        return self._store

    def _mark_store_unavailable(self) -> None:
        if not self._store_unavailable:
            logger.warning("perception persistence unavailable; shadow scan paused")
        self._store_unavailable = True
        self._store = None
