"""Occasional IPv6 reachability checks from inside the container.

The general connectivity probes use whichever address family works, so an
IPv6 path that breaks while IPv4 keeps working never shows up as an outage.
This checks IPv6 on its own, against literal IPv6 addresses so no IPv4
fallback can hide a failure, and records when it stops and starts working and
when the public /64 the carrier assigned changes.

It only reports on installs where IPv6 has worked at least once. A container
can hold an IPv6 address (Docker hands out private ones) on a host with no
IPv6 upstream at all, and those failures say nothing about stability.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .storage import EventStore


logger = logging.getLogger(__name__)

# Two providers, so one having a bad minute is not an IPv6 outage. Cloudflare's
# trace also reports the address the request came from.
IPV6_PROBES = (
    "https://[2606:4700:4700::1111]/cdn-cgi/trace",
    "https://[2001:4860:4860::8888]/resolve?name=example.com&type=A",
)
IPV6_EVENT_KINDS = ("ipv6_lost", "ipv6_restored", "ipv6_prefix_changed")
IPV6_CONFIRMED_KEY = "ipv6_confirmed_at"
IPV6_PREFIX_KEY = "ipv6_public_prefix"

CHECK_INTERVAL_SECONDS = 300
# While IPv6 is down, look again sooner so the restore time is close.
DOWN_RECHECK_SECONDS = 60
# One failed check is retried after this long before it counts as an outage.
CONFIRM_FAILURE_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 5.0


def container_ipv6_addresses(path: str = "/proc/net/if_inet6") -> list[str]:
    """Non-loopback, non-link-local IPv6 addresses on this container."""
    try:
        lines = Path(path).read_text(encoding="ascii").splitlines()
    except OSError:
        return []
    addresses = []
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            continue
        try:
            address = ipaddress.IPv6Address(bytes.fromhex(fields[0]))
        except ValueError:
            continue
        if address.is_loopback or address.is_link_local:
            continue
        addresses.append(str(address))
    return addresses


class Ipv6Monitor:
    def __init__(
        self,
        store: EventStore,
        *,
        internet_online: Callable[[], bool | None],
        addresses_provider: Callable[[], list[str]] = container_ipv6_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.store = store
        self._internet_online = internet_online
        self._addresses_provider = addresses_provider
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS),
            trust_env=False,
            headers={"User-Agent": "tmhi-control-center/0.1", "Cache-Control": "no-cache"},
            transport=transport,
        )
        self.latest: dict[str, Any] | None = None
        self._down = False
        self._down_since: datetime | None = None

    async def initialize(self) -> None:
        # Pick up an outage that was still open when the app last stopped.
        events = await self.store.events_since(
            ("ipv6_lost", "ipv6_restored"), datetime.fromtimestamp(0, timezone.utc)
        )
        if events and events[-1]["kind"] == "ipv6_lost":
            self._down = True
            self._down_since = _parse_time(events[-1]["timestamp"])

    async def close(self) -> None:
        await self._client.aclose()

    async def run(self) -> None:
        await self.initialize()
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("IPv6 check failed")
            await self._sleep(DOWN_RECHECK_SECONDS if self._down else CHECK_INTERVAL_SECONDS)

    async def check_once(self) -> dict[str, Any] | None:
        addresses = self._addresses_provider()
        if not addresses:
            self.latest = {"available": False, "checked_at": _now().isoformat()}
            return self.latest
        if self._internet_online() is False:
            # A full outage is already recorded as one; don't count it twice.
            return self.latest

        result = await self._probe()
        if not result["ok"] and not self._down:
            first_failure = result["checked_at"]
            await self._sleep(CONFIRM_FAILURE_SECONDS)
            result = await self._probe()
            # The outage began at the first failed check, not the retry.
            result["failed_since"] = first_failure
        result["available"] = True
        result["container_addresses"] = addresses

        confirmed = await self.store.get_meta(IPV6_CONFIRMED_KEY)
        if result["ok"]:
            if not confirmed:
                await self.store.set_meta(IPV6_CONFIRMED_KEY, result["checked_at"])
                confirmed = result["checked_at"]
            if self._down:
                await self._record_restored(result)
            await self._track_prefix(result)
        elif confirmed and not self._down:
            await self._record_lost(result)
        result["confirmed"] = bool(confirmed)
        self.latest = result
        return result

    async def _probe(self) -> dict[str, Any]:
        outcomes = await asyncio.gather(*(self._probe_one(url) for url in IPV6_PROBES))
        successes = [outcome for outcome in outcomes if outcome["ok"]]
        public_address = next(
            (outcome["public_address"] for outcome in successes if outcome.get("public_address")),
            None,
        )
        return {
            "ok": bool(successes),
            "checked_at": _now().isoformat(),
            "latency_ms": min((outcome["latency_ms"] for outcome in successes), default=None),
            "public_address": public_address,
            "public_prefix": _prefix_of(public_address),
            "errors": [outcome["error"] for outcome in outcomes if outcome.get("error")],
        }

    async def _probe_one(self, url: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = await self._client.get(url)
        except (httpx.HTTPError, OSError) as exc:
            return {"ok": False, "error": f"{url}: {type(exc).__name__}: {exc}"}
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if response.status_code != 200:
            return {"ok": False, "error": f"{url}: HTTP {response.status_code}"}
        public_address = None
        if "cdn-cgi/trace" in url:
            for line in response.text.splitlines():
                if line.startswith("ip="):
                    public_address = line[3:].strip()
        return {"ok": True, "latency_ms": latency_ms, "public_address": public_address}

    async def _record_lost(self, result: dict[str, Any]) -> None:
        self._down = True
        self._down_since = _parse_time(result.get("failed_since") or result["checked_at"])
        await self.store.record(
            "ipv6_lost",
            "IPv6 stopped working while IPv4 stayed up",
            {"errors": result["errors"][:2]},
            timestamp=self._down_since,
        )

    async def _record_restored(self, result: dict[str, Any]) -> None:
        duration = None
        if self._down_since:
            duration = round((_parse_time(result["checked_at"]) - self._down_since).total_seconds())
        self._down = False
        self._down_since = None
        await self.store.record(
            "ipv6_restored",
            "IPv6 is working again",
            {"duration_seconds": duration, "public_prefix": result["public_prefix"]},
        )

    async def _track_prefix(self, result: dict[str, Any]) -> None:
        prefix = result["public_prefix"]
        if not prefix:
            return
        previous = await self.store.get_meta(IPV6_PREFIX_KEY)
        if prefix == previous:
            return
        await self.store.set_meta(IPV6_PREFIX_KEY, prefix)
        if previous:
            await self.store.record(
                "ipv6_prefix_changed",
                f"Public IPv6 prefix changed from {previous} to {prefix}",
                {"from": previous, "to": prefix},
            )

    def summary(
        self,
        events: list[dict[str, Any]],
        *,
        since: datetime,
        now: datetime,
    ) -> dict[str, Any]:
        latest = self.latest or {}
        available = bool(latest.get("available"))
        confirmed = bool(latest.get("confirmed"))
        reported = available and confirmed
        if not reported:
            return {"reported": False, "available": available, "confirmed": confirmed}

        periods: list[dict[str, Any]] = []
        started: datetime | None = None
        prefix_changes = []
        for event in events:
            moment = _parse_time(event["timestamp"])
            if event["kind"] == "ipv6_lost":
                started = moment
            elif event["kind"] == "ipv6_restored" and started is not None:
                if moment >= since:
                    periods.append(_period(started, moment, ongoing=False))
                started = None
            elif event["kind"] == "ipv6_prefix_changed" and moment >= since:
                prefix_changes.append({"timestamp": event["timestamp"], **event["details"]})
        if started is not None and self._down:
            periods.append(_period(started, now, ongoing=True))

        return {
            "reported": True,
            "available": True,
            "confirmed": True,
            "status": "down" if self._down else "ok",
            "checked_at": latest.get("checked_at"),
            "latency_ms": latest.get("latency_ms"),
            "public_prefix": latest.get("public_prefix")
            or (prefix_changes[-1]["to"] if prefix_changes else None),
            "outages": {
                "count": len(periods),
                "total_seconds": sum(period["duration_seconds"] for period in periods),
                "periods": periods,
            },
            "prefix_changes": prefix_changes,
        }


def _period(started: datetime, ended: datetime, *, ongoing: bool) -> dict[str, Any]:
    return {
        "started_at": started.isoformat(),
        "ended_at": None if ongoing else ended.isoformat(),
        "duration_seconds": max(0, round((ended - started).total_seconds())),
        "ongoing": ongoing,
    }


def _prefix_of(address: str | None) -> str | None:
    if not address:
        return None
    try:
        parsed = ipaddress.IPv6Address(address)
    except ValueError:
        return None
    return str(ipaddress.IPv6Network(f"{parsed}/64", strict=False))


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)
