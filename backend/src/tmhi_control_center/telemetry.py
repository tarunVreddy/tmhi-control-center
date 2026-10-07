from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .storage import EventStore, compact_telemetry_snapshot

if TYPE_CHECKING:
    from .connection import ConnectionChangeTracker


logger = logging.getLogger(__name__)


class GatewayTelemetryCollector:
    def __init__(
        self,
        overview_provider: Callable[[], Awaitable[dict[str, Any]]],
        store: EventStore,
        *,
        interval_seconds: float = 60,
        enabled: bool = True,
        change_tracker: ConnectionChangeTracker | None = None,
    ) -> None:
        self.overview_provider = overview_provider
        self.store = store
        self.change_tracker = change_tracker
        self.interval_seconds = max(0.01, float(interval_seconds))
        self.enabled = enabled
        self._collect_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._latest: dict[str, Any] | None = None
        self._last_collected_at: datetime | None = None
        self._last_error: str | None = None

    async def stop(self) -> None:
        self._stop_event.set()

    async def collect_once(
        self,
        *,
        max_age_seconds: float = 0,
    ) -> dict[str, Any]:
        cached = self._fresh_cached(max_age_seconds)
        if cached is not None:
            return cached

        async with self._collect_lock:
            cached = self._fresh_cached(max_age_seconds)
            if cached is not None:
                return cached

            try:
                overview = await self.overview_provider()
                await self.store.record_telemetry(overview)
            except Exception as exc:
                self._last_error = str(exc)
                raise

            self._latest = overview
            self._last_collected_at = datetime.now(timezone.utc)
            self._last_error = None
            await self._track_changes(overview)
            return overview

    @property
    def latest(self) -> dict[str, Any] | None:
        return self._latest

    async def _track_changes(self, overview: dict[str, Any]) -> None:
        if self.change_tracker is None:
            return
        snapshot = compact_telemetry_snapshot(overview)
        if snapshot is None:
            return
        try:
            observed_at = datetime.fromisoformat(
                str(overview.get("observed_at")).replace("Z", "+00:00")
            )
        except ValueError:
            observed_at = self._last_collected_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        try:
            await self.change_tracker.observe(observed_at, snapshot)
        except Exception as exc:  # change logging must never stop collection
            logger.warning("Connection change tracking failed: %s", exc)

    async def run(self) -> None:
        if not self.enabled:
            logger.info("Gateway telemetry background collection is disabled")
            return

        while not self._stop_event.is_set():
            try:
                await self.collect_once(max_age_seconds=self.interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Gateway telemetry collection failed: %s", exc)

            delay = self._next_delay()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "interval_seconds": round(self.interval_seconds),
            "last_collected_at": self._last_collected_at.isoformat()
            if self._last_collected_at
            else None,
            "last_error": self._last_error,
        }

    def _fresh_cached(self, max_age_seconds: float) -> dict[str, Any] | None:
        if (
            self._latest is None
            or self._last_collected_at is None
            or max_age_seconds <= 0
        ):
            return None
        age = (datetime.now(timezone.utc) - self._last_collected_at).total_seconds()
        return self._latest if age <= max_age_seconds else None

    def _next_delay(self) -> float:
        if self._last_collected_at is None:
            return min(self.interval_seconds, 30.0)
        age = (datetime.now(timezone.utc) - self._last_collected_at).total_seconds()
        return max(0.01, self.interval_seconds - age)
