from __future__ import annotations

import asyncio
import calendar
import logging
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from .storage import EventStore


logger = logging.getLogger(__name__)

CLOUDFLARE_DOWNLOAD_URL = "https://speed.cloudflare.com/__down"
CLOUDFLARE_UPLOAD_URL = "https://speed.cloudflare.com/__up"
MAX_TRANSFER_REQUEST_BYTES = 25_000_000
UPLOAD_STREAM_CHUNK_BYTES = 64 * 1024
INTERVAL_CADENCE_MINUTES = {
    "every_5_minutes": 5,
    "every_10_minutes": 10,
    "every_15_minutes": 15,
    "every_30_minutes": 30,
    "hourly": 60,
    "every_6_hours": 360,
    "every_12_hours": 720,
}
SPEEDTEST_CADENCES = {
    "disabled",
    "daily",
    "weekly",
    "monthly",
    *INTERVAL_CADENCE_MINUTES,
}
SPEEDTEST_PROFILES: dict[str, dict[str, Any]] = {
    "gentle": {
        "label": "Gentle",
        "download_bytes": 10_000_000,
        "upload_bytes": 2_000_000,
        "latency_samples": 3,
    },
    "standard": {
        "label": "Standard",
        "download_bytes": 25_000_000,
        "upload_bytes": 5_000_000,
        "latency_samples": 4,
    },
    "accurate": {
        "label": "Accurate",
        "download_bytes": 100_000_000,
        "upload_bytes": 25_000_000,
        "latency_samples": 6,
    },
    "extended": {
        "label": "Extended",
        "download_bytes": 250_000_000,
        "upload_bytes": 50_000_000,
        "latency_samples": 8,
    },
    "maximum": {
        "label": "Maximum",
        "download_bytes": 800_000_000,
        "upload_bytes": 200_000_000,
        "latency_samples": 10,
    },
}
ROTATING_HOURS = (2, 8, 14, 20)
DAYPARTS = (
    ("night", "Night", 0, 6),
    ("morning", "Morning", 6, 12),
    ("afternoon", "Afternoon", 12, 18),
    ("evening", "Evening", 18, 24),
)


class SpeedTestError(RuntimeError):
    pass


class SpeedTestBusyError(SpeedTestError):
    pass


def transfer_chunks(total_bytes: int) -> list[int]:
    remaining = max(0, int(total_bytes))
    chunks: list[int] = []
    while remaining:
        chunk_size = min(remaining, MAX_TRANSFER_REQUEST_BYTES)
        chunks.append(chunk_size)
        remaining -= chunk_size
    return chunks


class ZeroByteStream(httpx.AsyncByteStream):
    def __init__(self, byte_count: int) -> None:
        self.byte_count = max(0, int(byte_count))

    async def __aiter__(self):
        remaining = self.byte_count
        payload = b"0" * min(UPLOAD_STREAM_CHUNK_BYTES, remaining)
        while remaining:
            chunk_size = min(len(payload), remaining)
            yield payload[:chunk_size]
            remaining -= chunk_size


def profile_summary(profile: str) -> dict[str, Any]:
    selected = SPEEDTEST_PROFILES.get(profile, SPEEDTEST_PROFILES["gentle"])
    total_bytes = selected["download_bytes"] + selected["upload_bytes"]
    return {
        "key": profile if profile in SPEEDTEST_PROFILES else "gentle",
        "label": selected["label"],
        "download_bytes": selected["download_bytes"],
        "upload_bytes": selected["upload_bytes"],
        "estimated_bytes": total_bytes,
        "estimated_megabytes": round(total_bytes / 1_000_000, 1),
        "sequential": True,
        "request_chunk_bytes": MAX_TRANSFER_REQUEST_BYTES,
        "download_requests": len(transfer_chunks(selected["download_bytes"])),
        "upload_requests": len(transfer_chunks(selected["upload_bytes"])),
    }


def usage_summary(profile: str, cadence: str) -> dict[str, Any]:
    per_run_bytes = int(profile_summary(profile)["estimated_bytes"])
    interval_minutes = INTERVAL_CADENCE_MINUTES.get(cadence)
    if cadence == "disabled":
        runs_per_day = 0.0
    elif interval_minutes:
        runs_per_day = 1440 / interval_minutes
    elif cadence == "daily":
        runs_per_day = 1.0
    elif cadence == "weekly":
        runs_per_day = 1 / 7
    else:
        runs_per_day = 1 / 30
    return {
        "runs_per_day": round(runs_per_day, 4),
        "estimated_daily_bytes": round(per_run_bytes * runs_per_day),
        "estimated_30_day_bytes": round(per_run_bytes * runs_per_day * 30),
    }


def daypart_for_hour(hour: int) -> tuple[str, str]:
    for key, label, start, end in DAYPARTS:
        if start <= hour < end:
            return key, label
    return "night", "Night"


def next_initial_slot(
    now: datetime,
    timezone_offset_minutes: int,
    cadence: str = "daily",
) -> tuple[datetime, int]:
    interval_minutes = INTERVAL_CADENCE_MINUTES.get(cadence)
    if interval_minutes:
        return (
            now.astimezone(timezone.utc) + timedelta(minutes=interval_minutes),
            0,
        )

    local_tz = timezone(timedelta(minutes=timezone_offset_minutes))
    local_now = now.astimezone(local_tz)
    for index, hour in enumerate(ROTATING_HOURS):
        candidate = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > local_now:
            return candidate.astimezone(timezone.utc), index
    candidate = (local_now + timedelta(days=1)).replace(
        hour=ROTATING_HOURS[0], minute=0, second=0, microsecond=0
    )
    return candidate.astimezone(timezone.utc), 0


def next_scheduled_slot(
    completed_at: datetime,
    cadence: str,
    completed_slot_index: int,
    timezone_offset_minutes: int,
) -> tuple[datetime, int]:
    interval_minutes = INTERVAL_CADENCE_MINUTES.get(cadence)
    if interval_minutes:
        return (
            completed_at.astimezone(timezone.utc)
            + timedelta(minutes=interval_minutes),
            completed_slot_index,
        )

    local_tz = timezone(timedelta(minutes=timezone_offset_minutes))
    local_completed = completed_at.astimezone(local_tz)
    next_index = (completed_slot_index + 1) % len(ROTATING_HOURS)
    if cadence == "weekly":
        target_date = local_completed.date() + timedelta(days=7)
    elif cadence == "monthly":
        year = local_completed.year + (1 if local_completed.month == 12 else 0)
        month = 1 if local_completed.month == 12 else local_completed.month + 1
        day = min(local_completed.day, calendar.monthrange(year, month)[1])
        target_date = local_completed.date().replace(year=year, month=month, day=day)
    else:
        target_date = local_completed.date() + timedelta(days=1)
    target = datetime.combine(
        target_date,
        datetime.min.time(),
        tzinfo=local_tz,
    ).replace(hour=ROTATING_HOURS[next_index])
    return target.astimezone(timezone.utc), next_index


class LowImpactSpeedTest:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=True,
            headers={"User-Agent": "TMHI-Control-Center/0.1 speed-history"},
        )
        self._owns_client = client is None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def run(self, profile: str = "gentle") -> dict[str, Any]:
        if self._lock.locked():
            raise SpeedTestBusyError("A speed test is already running")
        selected = SPEEDTEST_PROFILES.get(profile)
        if selected is None:
            raise SpeedTestError(f"Unknown speed test profile: {profile}")

        async with self._lock:
            started_at = datetime.now(timezone.utc)
            started = time.perf_counter()
            latency_samples = await self._measure_latency(selected["latency_samples"])
            download_mbps, downloaded = await self._measure_download(
                selected["download_bytes"]
            )
            upload_mbps, uploaded = await self._measure_upload(selected["upload_bytes"])
            latency_ms = statistics.median(latency_samples)
            jitter_ms = (
                statistics.mean(
                    abs(right - left)
                    for left, right in zip(latency_samples, latency_samples[1:])
                )
                if len(latency_samples) > 1
                else 0.0
            )
            observed_at = datetime.now(timezone.utc)
            return {
                "observed_at": observed_at.isoformat(),
                "started_at": started_at.isoformat(),
                "profile": profile,
                "provider": "cloudflare",
                "success": True,
                "download_mbps": round(download_mbps, 2),
                "upload_mbps": round(upload_mbps, 2),
                "latency_ms": round(latency_ms, 2),
                "jitter_ms": round(jitter_ms, 2),
                "bytes_downloaded": downloaded,
                "bytes_uploaded": uploaded,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "error": None,
            }

    async def _measure_latency(self, count: int) -> list[float]:
        samples: list[float] = []
        for index in range(count):
            started = time.perf_counter()
            response = await self._client.get(
                CLOUDFLARE_DOWNLOAD_URL,
                params={"bytes": 0, "measId": f"tmhi-latency-{time.time_ns()}-{index}"},
                headers={"Cache-Control": "no-cache"},
            )
            response.raise_for_status()
            samples.append((time.perf_counter() - started) * 1000)
        return samples

    async def _measure_download(self, byte_count: int) -> tuple[float, int]:
        received = 0
        started = time.perf_counter()
        for index, chunk_size in enumerate(transfer_chunks(byte_count)):
            query = urlencode(
                {
                    "bytes": chunk_size,
                    "measId": f"tmhi-down-{time.time_ns()}-{index}",
                }
            )
            async with self._client.stream(
                "GET",
                f"{CLOUDFLARE_DOWNLOAD_URL}?{query}",
                headers={"Cache-Control": "no-cache"},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
        elapsed = max(time.perf_counter() - started, 0.001)
        if received <= 0:
            raise SpeedTestError("The download sample returned no data")
        return received * 8 / elapsed / 1_000_000, received

    async def _measure_upload(self, byte_count: int) -> tuple[float, int]:
        uploaded = 0
        started = time.perf_counter()
        for index, chunk_size in enumerate(transfer_chunks(byte_count)):
            response = await self._client.post(
                CLOUDFLARE_UPLOAD_URL,
                params={"measId": f"tmhi-up-{time.time_ns()}-{index}"},
                content=ZeroByteStream(chunk_size),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(chunk_size),
                    "Cache-Control": "no-cache",
                },
            )
            response.raise_for_status()
            uploaded += chunk_size
        elapsed = max(time.perf_counter() - started, 0.001)
        return uploaded * 8 / elapsed / 1_000_000, uploaded


class SpeedTestManager:
    def __init__(self, settings: Any, store: EventStore) -> None:
        self.settings = settings
        self.store = store
        self.runner = LowImpactSpeedTest()
        self._stop_event = asyncio.Event()

    async def initialize(self) -> None:
        if self.settings.speedtest_cadence == "disabled":
            await self.store.set_speed_test_schedule(None, 0)
            return
        schedule = await self.store.get_speed_test_schedule()
        if schedule.get("next_run_at") is None:
            await self.reset_schedule()

    async def stop(self) -> None:
        self._stop_event.set()
        await self.runner.close()

    async def reset_schedule(self) -> dict[str, Any]:
        if self.settings.speedtest_cadence == "disabled":
            await self.store.set_speed_test_schedule(None, 0)
        else:
            next_run, slot_index = next_initial_slot(
                datetime.now(timezone.utc),
                self.settings.speedtest_timezone_offset_minutes,
                self.settings.speedtest_cadence,
            )
            await self.store.set_speed_test_schedule(next_run, slot_index)
        return await self.status()

    async def run_scheduler(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_if_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Scheduled speed test check failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except TimeoutError:
                pass

    async def run_if_due(self, now: datetime | None = None) -> dict[str, Any] | None:
        if self.settings.speedtest_cadence == "disabled" or self.runner.running:
            return None
        schedule = await self.store.get_speed_test_schedule()
        next_run_at = schedule.get("next_run_at")
        now = now or datetime.now(timezone.utc)
        if next_run_at is None:
            await self.reset_schedule()
            return None
        if next_run_at > now:
            return None
        return await self.run(trigger="scheduled", slot_index=schedule.get("slot_index", 0))

    async def run(
        self,
        *,
        trigger: str,
        slot_index: int | None = None,
    ) -> dict[str, Any]:
        profile = self.settings.speedtest_profile
        observed_at = datetime.now(timezone.utc)
        try:
            result = await self.runner.run(profile)
        except SpeedTestBusyError:
            raise
        except Exception as exc:
            failure = {
                "observed_at": observed_at.isoformat(),
                "profile": profile,
                "provider": "cloudflare",
                "success": False,
                "download_mbps": None,
                "upload_mbps": None,
                "latency_ms": None,
                "jitter_ms": None,
                "bytes_downloaded": 0,
                "bytes_uploaded": 0,
                "duration_seconds": 0,
                "error": str(exc),
            }
            await self._finish_run(failure, trigger, slot_index)
            raise SpeedTestError(f"Speed test failed: {exc}") from exc
        await self._finish_run(result, trigger, slot_index)
        return result

    async def _finish_run(
        self,
        result: dict[str, Any],
        trigger: str,
        slot_index: int | None,
    ) -> None:
        observed_at = datetime.fromisoformat(
            str(result["observed_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        local_hour = (
            observed_at
            + timedelta(minutes=self.settings.speedtest_timezone_offset_minutes)
        ).hour
        daypart, _ = daypart_for_hour(local_hour)
        await self.store.record_speed_test(
            result,
            trigger=trigger,
            daypart=daypart,
        )
        await self.store.record(
            "speed_test_completed" if result.get("success") else "speed_test_failed",
            "Speed test completed" if result.get("success") else "Speed test failed",
            {
                "trigger": trigger,
                "profile": result.get("profile"),
                "download_mbps": result.get("download_mbps"),
                "upload_mbps": result.get("upload_mbps"),
                "error": result.get("error"),
            },
        )
        if trigger == "scheduled" and self.settings.speedtest_cadence != "disabled":
            completed_slot = int(slot_index or 0) % len(ROTATING_HOURS)
            next_run, next_index = next_scheduled_slot(
                observed_at,
                self.settings.speedtest_cadence,
                completed_slot,
                self.settings.speedtest_timezone_offset_minutes,
            )
            await self.store.set_speed_test_schedule(next_run, next_index)

    async def status(self) -> dict[str, Any]:
        schedule = await self.store.get_speed_test_schedule()
        latest = await self.store.latest_speed_test()
        next_run = schedule.get("next_run_at")
        next_daypart = None
        if next_run:
            local_hour = (
                next_run
                + timedelta(minutes=self.settings.speedtest_timezone_offset_minutes)
            ).hour
            next_daypart = daypart_for_hour(local_hour)[1]
        interval_minutes = INTERVAL_CADENCE_MINUTES.get(
            self.settings.speedtest_cadence
        )
        return {
            "cadence": self.settings.speedtest_cadence,
            "profile": profile_summary(self.settings.speedtest_profile),
            "usage": usage_summary(
                self.settings.speedtest_profile,
                self.settings.speedtest_cadence,
            ),
            "running": self.runner.running,
            "next_run_at": next_run.isoformat() if next_run else None,
            "next_daypart": next_daypart,
            "schedule_mode": "interval"
            if interval_minutes
            else "rotating"
            if self.settings.speedtest_cadence != "disabled"
            else "disabled",
            "interval_minutes": interval_minutes,
            "retention_days": self.settings.speedtest_retention_days,
            "timezone_offset_minutes": self.settings.speedtest_timezone_offset_minutes,
            "rotating_hours": list(ROTATING_HOURS),
            "latest": latest,
            "provider": "cloudflare",
            "privacy_notice": "Test traffic and measurement metadata are sent to Cloudflare.",
        }
