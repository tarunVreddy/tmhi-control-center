from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from tmhi_control_center.speedtest import (
    MAX_TRANSFER_REQUEST_BYTES,
    LowImpactSpeedTest,
    next_initial_slot,
    next_scheduled_slot,
    profile_summary,
    transfer_chunks,
    usage_summary,
)


@pytest.mark.asyncio
async def test_gentle_speed_test_uses_bounded_sequential_samples() -> None:
    uploaded = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal uploaded
        if request.url.path == "/__down":
            byte_count = int(request.url.params.get("bytes", "0"))
            return httpx.Response(200, content=b"x" * byte_count)
        if request.url.path == "/__up":
            uploaded = len(await request.aread())
            return httpx.Response(200, content=b"ok")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runner = LowImpactSpeedTest(client)
    result = await runner.run("gentle")
    await client.aclose()

    assert result["success"] is True
    assert result["bytes_downloaded"] == 10_000_000
    assert result["bytes_uploaded"] == 2_000_000
    assert uploaded == 2_000_000
    assert result["download_mbps"] > 0
    assert result["upload_mbps"] > 0
    assert result["latency_ms"] >= 0


def test_rotating_schedule_moves_through_local_dayparts() -> None:
    now = datetime(2026, 7, 26, 16, 0, tzinfo=timezone.utc)
    first_run, first_slot = next_initial_slot(now, -7 * 60)
    second_run, second_slot = next_scheduled_slot(
        first_run,
        "daily",
        first_slot,
        -7 * 60,
    )

    assert first_run == datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)
    assert first_slot == 2
    assert second_run == datetime(2026, 7, 28, 3, 0, tzinfo=timezone.utc)
    assert second_slot == 3


def test_monthly_schedule_handles_short_months() -> None:
    completed = datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)
    next_run, next_slot = next_scheduled_slot(completed, "monthly", 0, 0)

    assert next_run == datetime(2026, 2, 28, 8, 0, tzinfo=timezone.utc)
    assert next_slot == 1


def test_interval_schedule_runs_from_save_and_completion_times() -> None:
    now = datetime(2026, 7, 27, 16, 3, 42, tzinfo=timezone.utc)
    first_run, first_slot = next_initial_slot(
        now,
        -7 * 60,
        "every_5_minutes",
    )
    second_run, second_slot = next_scheduled_slot(
        first_run,
        "every_10_minutes",
        first_slot,
        -7 * 60,
    )

    assert first_run == datetime(2026, 7, 27, 16, 8, 42, tzinfo=timezone.utc)
    assert first_slot == 0
    assert second_run == datetime(2026, 7, 27, 16, 18, 42, tzinfo=timezone.utc)
    assert second_slot == 0


def test_large_profiles_and_five_minute_usage_are_explicit() -> None:
    profile = profile_summary("accurate")
    usage = usage_summary("accurate", "every_5_minutes")

    assert profile["download_bytes"] == 100_000_000
    assert profile["upload_bytes"] == 25_000_000
    assert profile["estimated_megabytes"] == 125.0
    assert profile["download_requests"] == len(transfer_chunks(100_000_000))
    assert profile["upload_requests"] == len(transfer_chunks(25_000_000))
    assert usage["runs_per_day"] == 288
    assert usage["estimated_daily_bytes"] == profile["estimated_bytes"] * 288
    assert profile_summary("extended")["estimated_bytes"] == 300_000_000
    assert profile_summary("maximum")["estimated_bytes"] == 1_000_000_000


@pytest.mark.asyncio
async def test_accurate_profile_uses_bounded_requests() -> None:
    download_requests: list[int] = []
    upload_requests: list[int] = []

    class DownloadStream(httpx.AsyncByteStream):
        def __init__(self, byte_count: int) -> None:
            self.byte_count = byte_count

        async def __aiter__(self):
            remaining = self.byte_count
            payload = b"x" * 64 * 1024
            while remaining:
                chunk_size = min(len(payload), remaining)
                yield payload[:chunk_size]
                remaining -= chunk_size

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/__down":
            byte_count = int(request.url.params.get("bytes", "0"))
            if byte_count:
                download_requests.append(byte_count)
            if byte_count > MAX_TRANSFER_REQUEST_BYTES:
                return httpx.Response(403, content=b"oversized")
            return httpx.Response(200, stream=DownloadStream(byte_count))
        if request.url.path == "/__up":
            byte_count = int(request.headers.get("Content-Length", "0"))
            upload_requests.append(byte_count)
            if byte_count > MAX_TRANSFER_REQUEST_BYTES:
                return httpx.Response(403, content=b"oversized")
            assert len(await request.aread()) == byte_count
            return httpx.Response(200, content=b"ok")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runner = LowImpactSpeedTest(client)
    result = await runner.run("accurate")
    await client.aclose()

    assert result["bytes_downloaded"] == 100_000_000
    assert result["bytes_uploaded"] == 25_000_000
    # Workers share the budget concurrently, so request order is not
    # deterministic. What matters is the total volume and that every individual
    # request stays within the provider's accepted size.
    assert sum(download_requests) == 100_000_000
    assert max(download_requests) <= MAX_TRANSFER_REQUEST_BYTES
    assert sum(upload_requests) == 25_000_000
    assert max(upload_requests) <= MAX_TRANSFER_REQUEST_BYTES


def test_transfer_chunks_preserve_requested_volume() -> None:
    chunks = transfer_chunks(1_000_000_000)

    assert sum(chunks) == 1_000_000_000
    assert len(chunks) == 1_000_000_000 // MAX_TRANSFER_REQUEST_BYTES
    assert max(chunks) == MAX_TRANSFER_REQUEST_BYTES
