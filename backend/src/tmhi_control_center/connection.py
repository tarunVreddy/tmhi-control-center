"""Connection state, change detection, and outage analysis.

Everything here is derived from the compact telemetry snapshots and the event
log the app already keeps. None of it adds traffic to the gateway: the gateway
exposes no event history of its own, so handovers, mode switches, and restarts
are only visible by comparing one snapshot with the next.
"""

from __future__ import annotations

import bisect
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import EventStore


logger = logging.getLogger(__name__)

CONNECTION_EVENT_KINDS = (
    "connection_changed",
    "gateway_restarted",
    "registration_changed",
    "firmware_changed",
)
OUTAGE_EVENT_KINDS = ("internet_lost", "internet_restored")
REBOOT_EVENT_KINDS = ("reboot_requested", "reboot_uncertain")

MODE_LABELS = {
    "5g_sa": "5G standalone",
    "nsa": "LTE + 5G",
    "lte": "LTE only",
    "none": "No service",
}
RADIO_LABELS = {"lte": "LTE", "nr": "5G"}

# Boot time is estimated as observed time minus uptime, so request latency
# makes it wobble by a second or two between samples. A real restart moves it
# by at least the gateway's own boot time, which is minutes.
RESTART_TOLERANCE_SECONDS = 180
# A reboot this app requested shows up as a restart shortly afterwards.
WATCHDOG_REBOOT_LEAD = timedelta(minutes=15)
WATCHDOG_REBOOT_LAG = timedelta(minutes=2)
# Backfilled speed tests borrow the nearest snapshot within this window.
CONTEXT_MATCH_WINDOW_SECONDS = 300

MAX_OUTAGE_PERIODS = 1000

# When the change log begins: modes before this moment are unknown, not
# whatever the first logged change happened to switch away from.
CONNECTION_HISTORY_START_KEY = "connection_history_start"
CONNECTION_BACKFILL_KEY = "connection_history_backfilled"
SPEED_CONTEXT_BACKFILL_KEY = "speed_test_context_backfilled"

OUTAGE_DURATION_BUCKETS = (
    ("under_30s", "Under 30 s", 30),
    ("under_1m", "30-60 s", 60),
    ("under_5m", "1-5 min", 300),
    ("under_30m", "5-30 min", 1800),
    ("over_30m", "30 min+", None),
)
OUTAGE_DIAGNOSES = {
    "upstream": "Radio connected; failure past the gateway",
    "cellular": "Gateway lost its cellular connection",
    "gateway_unreachable": "Gateway did not answer",
    "unknown": "Not diagnosed",
}


def connection_state(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    lte = _radio_cell(snapshot, "lte")
    nr = _radio_cell(snapshot, "nr")
    if lte and nr:
        mode = "nsa"
    elif nr:
        mode = "5g_sa"
    elif lte:
        mode = "lte"
    else:
        mode = "none"
    bands = " + ".join(cell["band"] for cell in (lte, nr) if cell and cell.get("band"))
    connection = snapshot.get("connection") if isinstance(snapshot.get("connection"), dict) else {}
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "bands": bands or None,
        "site": _text(connection.get("cell_id")),
        "cells": {"lte": lte, "nr": nr},
    }


def connection_context(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Connection plus the signal it had, for attaching to a speed test."""
    if not isinstance(snapshot, dict) or not snapshot.get("radios"):
        return None
    state = connection_state(snapshot)
    signal: dict[str, dict[str, float]] = {}
    for key, cell in state["cells"].items():
        if not cell:
            continue
        metrics = snapshot["radios"].get(key, {}).get("metrics") or {}
        signal[key] = {
            metric: metrics[metric]
            for metric in ("rsrp", "sinr", "cqi")
            if isinstance(metrics.get(metric), (int, float))
        }
    return {**state, "signal": signal}


def detect_changes(
    previous_at: datetime,
    previous: dict[str, Any],
    current_at: datetime,
    current: dict[str, Any],
) -> list[tuple[datetime, str, str, dict[str, Any]]]:
    """Events implied by moving from one snapshot to the next."""
    events: list[tuple[datetime, str, str, dict[str, Any]]] = []

    restart = _detect_restart(previous_at, previous, current_at, current)
    if restart:
        events.append(restart)

    before = connection_state(previous)
    after = connection_state(current)
    change = _connection_change(before, after)
    if change:
        kind_of_change, message = change
        events.append(
            (
                current_at,
                "connection_changed",
                message,
                {"change": kind_of_change, "from": before, "to": after},
            )
        )

    previous_registration = _system(previous).get("registration")
    current_registration = _system(current).get("registration")
    if (
        previous_registration
        and current_registration
        and previous_registration != current_registration
    ):
        events.append(
            (
                current_at,
                "registration_changed",
                f"Network registration changed from {previous_registration} "
                f"to {current_registration}",
                {"from": previous_registration, "to": current_registration},
            )
        )

    previous_firmware = _device(previous).get("firmware")
    current_firmware = _device(current).get("firmware")
    if previous_firmware and current_firmware and previous_firmware != current_firmware:
        events.append(
            (
                current_at,
                "firmware_changed",
                f"Gateway firmware changed from {previous_firmware} to {current_firmware}",
                {"from": previous_firmware, "to": current_firmware},
            )
        )
    return events


class ConnectionChangeTracker:
    """Compares each new snapshot with the last one and logs what changed."""

    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._previous: tuple[datetime, dict[str, Any]] | None = None

    async def initialize(self) -> None:
        await backfill_history(self.store)
        if not await self.store.get_meta(CONNECTION_HISTORY_START_KEY):
            # Installs that backfilled before this key existed: the oldest
            # snapshot still stored is the best remaining record of the start.
            oldest = await self.store.oldest_telemetry_timestamp()
            await self.store.set_meta(
                CONNECTION_HISTORY_START_KEY,
                (oldest or datetime.now(timezone.utc)).isoformat(),
            )
        self._previous = await self.store.latest_telemetry_snapshot()

    async def observe(
        self,
        observed_at: datetime,
        snapshot: dict[str, Any],
    ) -> list[tuple[datetime, str, str, dict[str, Any]]]:
        previous = self._previous
        self._previous = (observed_at, snapshot)
        if previous is None:
            return []
        events = detect_changes(previous[0], previous[1], observed_at, snapshot)
        if not events:
            return []
        if any(kind == "gateway_restarted" for _, kind, _, _ in events):
            earliest = min(timestamp for timestamp, _, _, _ in events)
            reboots = await self.store.events_since(
                REBOOT_EVENT_KINDS, earliest - WATCHDOG_REBOOT_LEAD
            )
            events = _attribute_restarts(events, reboots)
        await self.store.record_many(events)
        for _, kind, message, _ in events:
            logger.info("%s: %s", kind, message)
        return events


async def backfill_history(store: EventStore) -> dict[str, int]:
    """One-time pass over stored snapshots, so history predating this feature
    still shows its handovers and restarts, and past speed tests their radio."""
    connection_done = await store.get_meta(CONNECTION_BACKFILL_KEY)
    context_done = await store.get_meta(SPEED_CONTEXT_BACKFILL_KEY)
    if connection_done and context_done:
        return {"events": 0, "speed_tests": 0}

    snapshots = await store.telemetry_snapshots()
    recorded_events = 0
    updated_tests = 0

    if not connection_done:
        events: list[tuple[datetime, str, str, dict[str, Any]]] = []
        for (previous_at, previous), (current_at, current) in zip(
            snapshots, snapshots[1:]
        ):
            events.extend(detect_changes(previous_at, previous, current_at, current))
        if snapshots:
            reboots = await store.events_since(
                REBOOT_EVENT_KINDS, snapshots[0][0] - WATCHDOG_REBOOT_LEAD
            )
            events = _attribute_restarts(events, reboots)
        for event in events:
            event[3]["backfilled"] = True
        recorded_events = await store.record_many(events)
        start = snapshots[0][0] if snapshots else datetime.now(timezone.utc)
        await store.set_meta(CONNECTION_HISTORY_START_KEY, start.isoformat())
        await store.set_meta(CONNECTION_BACKFILL_KEY, _now_text())

    if not context_done:
        times = [timestamp.timestamp() for timestamp, _ in snapshots]
        contexts: list[tuple[int, dict[str, Any]]] = []
        for test in await store.speed_tests_without_context():
            observed = _parse_time(test["observed_at"]).timestamp()
            nearest = _nearest_index(times, observed)
            if (
                nearest is None
                or abs(times[nearest] - observed) > CONTEXT_MATCH_WINDOW_SECONDS
            ):
                continue
            context = connection_context(snapshots[nearest][1])
            if context:
                contexts.append((test["id"], {**context, "backfilled": True}))
        updated_tests = await store.set_speed_test_contexts(contexts)
        await store.set_meta(SPEED_CONTEXT_BACKFILL_KEY, _now_text())

    if recorded_events or updated_tests:
        logger.info(
            "Backfilled %s connection events and %s speed-test contexts",
            recorded_events,
            updated_tests,
        )
    return {"events": recorded_events, "speed_tests": updated_tests}


def diagnose_outage(
    signal_snapshot: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    """Classify an outage from a signal read taken as it began.

    The probes only say the internet is unreachable. Whether the gateway still
    held a cell at that moment separates a radio problem from one further
    upstream, which is the first question when deciding what to do about it.
    """
    if not isinstance(signal_snapshot, dict):
        return {
            "key": "gateway_unreachable",
            "label": OUTAGE_DIAGNOSES["gateway_unreachable"],
            "error": error,
        }

    registration = signal_snapshot.get("registration")
    radios: dict[str, dict[str, Any]] = {}
    for radio in signal_snapshot.get("radios") or []:
        if not isinstance(radio, dict) or radio.get("active") is False:
            continue
        metrics = {
            metric.get("key"): metric.get("value")
            for metric in radio.get("metrics") or []
            if isinstance(metric, dict)
            and metric.get("key") in {"rsrp", "sinr"}
            and isinstance(metric.get("value"), (int, float))
        }
        cell = radio.get("cell") if isinstance(radio.get("cell"), dict) else {}
        radios[str(radio.get("key"))] = {"band": cell.get("band"), **metrics}

    registered = registration is None or str(registration).lower() == "registered"
    key = "upstream" if radios and registered else "cellular"
    return {
        "key": key,
        "label": OUTAGE_DIAGNOSES[key],
        "registration": registration,
        "radios": radios,
    }


def outage_summary(
    events: list[dict[str, Any]],
    *,
    now: datetime,
    since: datetime,
    days: int,
    timezone_offset_minutes: int,
    check_interval_seconds: float,
) -> dict[str, Any]:
    outages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in sorted(events, key=lambda item: item["timestamp"]):
        timestamp = _parse_time(event["timestamp"])
        if event["kind"] == "internet_lost" and current is None:
            current = {"started_at": timestamp, "details": event.get("details") or {}}
        elif event["kind"] == "internet_restored" and current is not None:
            outages.append(_outage_entry(current, timestamp, ongoing=False))
            current = None
    if current is not None:
        outages.append(_outage_entry(current, now, ongoing=True))
    # Events are read from a little before the window so an outage spanning
    # its start keeps the event that began it; drop any that ended earlier.
    outages = [
        outage
        for outage in outages
        if _parse_time(outage["ended_at"] or now) >= since
    ]

    durations = [outage["duration_seconds"] for outage in outages]
    hourly = [0] * 24
    offset = timedelta(minutes=timezone_offset_minutes)
    for outage in outages:
        hourly[(_parse_time(outage["started_at"]) + offset).hour] += 1

    buckets = []
    lower = 0.0
    for key, label, upper in OUTAGE_DURATION_BUCKETS:
        count = sum(
            1
            for duration in durations
            if duration >= lower and (upper is None or duration < upper)
        )
        buckets.append({"key": key, "label": label, "count": count})
        lower = float(upper or 0)

    diagnoses = []
    for key, label in OUTAGE_DIAGNOSES.items():
        count = sum(1 for outage in outages if outage["diagnosis"] == key)
        if count:
            diagnoses.append({"key": key, "label": label, "count": count})

    peak_hour = max(range(24), key=lambda hour: hourly[hour]) if outages else None
    return {
        "range_days": days,
        "count": len(outages),
        "total_seconds": round(sum(durations)),
        "median_seconds": round(statistics.median(durations)) if durations else None,
        "longest_seconds": round(max(durations)) if durations else None,
        "resolution_seconds": round(check_interval_seconds),
        "timezone_offset_minutes": timezone_offset_minutes,
        "hourly": hourly,
        "peak_hour": peak_hour,
        "peak_hour_count": hourly[peak_hour] if peak_hour is not None else 0,
        "duration_buckets": buckets,
        "diagnoses": diagnoses,
        "recent": list(reversed(outages[-10:])),
        # Every outage in range, oldest first, for drawing on a timeline. The
        # cap only matters for a link that is down several times an hour.
        "periods": outages[-MAX_OUTAGE_PERIODS:],
    }


def parse_utc_offset(value: Any, *, at: datetime | None = None) -> int | None:
    """Minutes east of UTC from the gateway's zone string.

    Most firmware reports a fixed offset such as "-06:00"; some report an IANA
    name such as "America/Denver", which is resolved for the given moment.
    """
    if not isinstance(value, str):
        return None
    if "/" in value:
        try:
            offset = (at or datetime.now(timezone.utc)).astimezone(
                ZoneInfo(value.strip())
            ).utcoffset()
        except (ZoneInfoNotFoundError, ValueError):
            return None
        return round(offset.total_seconds() / 60) if offset is not None else None
    text = value.strip().upper().removeprefix("UTC").removeprefix("GMT")
    if not text or text[0] not in "+-":
        return None
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    if not digits.isdigit() or len(digits) not in (1, 2, 4):
        return None
    hours = int(digits[:-2] or 0) if len(digits) == 4 else int(digits)
    minutes = int(digits[-2:]) if len(digits) == 4 else 0
    total = sign * (hours * 60 + minutes)
    return total if -840 <= total <= 840 else None


def _radio_cell(snapshot: dict[str, Any], key: str) -> dict[str, Any] | None:
    radios = snapshot.get("radios") if isinstance(snapshot.get("radios"), dict) else {}
    radio = radios.get(key)
    if not isinstance(radio, dict) or radio.get("active") is False:
        return None
    band = _text(radio.get("band"))
    if not band and not radio.get("metrics"):
        return None
    return {
        "band": band,
        "cell_id": _text(radio.get("cell_id")),
        "node_id": _text(radio.get("node_id")),
    }


def _connection_change(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[str, str] | None:
    same_cells = all(
        _same_cell(before["cells"].get(key), after["cells"].get(key))
        for key in ("lte", "nr")
    )
    if (
        before["mode"] == after["mode"]
        and before["bands"] == after["bands"]
        and before["site"] == after["site"]
        and same_cells
    ):
        return None

    if before["mode"] != after["mode"]:
        return (
            "mode",
            f"Connection changed from {_describe(before)} to {_describe(after)}",
        )
    if before["site"] != after["site"] and before["site"] and after["site"]:
        return (
            "site",
            f"Moved to a different cell site ({before['site']} → {after['site']}) "
            f"on {_describe(after)}",
        )
    if before["bands"] != after["bands"]:
        return (
            "band",
            f"Bands changed from {before['bands'] or 'none'} to {after['bands'] or 'none'}",
        )
    for key in ("nr", "lte"):
        old = before["cells"].get(key) or {}
        new = after["cells"].get(key) or {}
        if old.get("cell_id") != new.get("cell_id"):
            site = after["site"] or new.get("node_id") or "the same site"
            return (
                "sector",
                f"Switched {RADIO_LABELS[key]} sector on site {site} "
                f"(cell {old.get('cell_id') or '?'} → {new.get('cell_id') or '?'})",
            )
    return ("cell", f"Serving cell changed on {_describe(after)}")


def _same_cell(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is right
    if left["band"] != right["band"] or left["cell_id"] != right["cell_id"]:
        return False
    # Snapshots taken before node IDs were recorded have none; only compare
    # them when both sides carry one, or the upgrade itself reads as a change.
    if left.get("node_id") and right.get("node_id"):
        return left["node_id"] == right["node_id"]
    return True


def _describe(state: dict[str, Any]) -> str:
    return f"{state['label']} ({state['bands']})" if state["bands"] else state["label"]


def _detect_restart(
    previous_at: datetime,
    previous: dict[str, Any],
    current_at: datetime,
    current: dict[str, Any],
) -> tuple[datetime, str, str, dict[str, Any]] | None:
    previous_uptime = _number(_system(previous).get("uptime_seconds"))
    current_uptime = _number(_system(current).get("uptime_seconds"))
    if previous_uptime is None or current_uptime is None:
        return None
    previous_boot = previous_at - timedelta(seconds=previous_uptime)
    current_boot = current_at - timedelta(seconds=current_uptime)
    if (current_boot - previous_boot).total_seconds() <= RESTART_TOLERANCE_SECONDS:
        return None
    # The gateway was seen up at previous_at, so it cannot have booted before.
    booted_at = max(current_boot, previous_at)
    return (
        booted_at,
        "gateway_restarted",
        f"Gateway restarted after {format_duration(previous_uptime)} of uptime",
        {
            "booted_at": booted_at.isoformat(),
            "last_seen_up_at": previous_at.isoformat(),
            "previous_uptime_seconds": round(previous_uptime),
            "requested_by_app": False,
        },
    )


def _attribute_restarts(
    events: list[tuple[datetime, str, str, dict[str, Any]]],
    reboots: list[dict[str, Any]],
) -> list[tuple[datetime, str, str, dict[str, Any]]]:
    reboot_times = [_parse_time(reboot["timestamp"]) for reboot in reboots]
    attributed = []
    for timestamp, kind, message, details in events:
        if kind == "gateway_restarted":
            requested = any(
                timestamp - WATCHDOG_REBOOT_LEAD <= reboot <= timestamp + WATCHDOG_REBOOT_LAG
                for reboot in reboot_times
            )
            details = {**details, "requested_by_app": requested}
            message = (
                f"{message}; requested by this app"
                if requested
                else f"{message}; not requested by this app"
            )
        attributed.append((timestamp, kind, message, details))
    return attributed


def _outage_entry(
    current: dict[str, Any],
    ended_at: datetime,
    *,
    ongoing: bool,
) -> dict[str, Any]:
    started_at: datetime = current["started_at"]
    diagnosis = current["details"].get("diagnosis")
    return {
        "started_at": started_at.isoformat(),
        "ended_at": None if ongoing else ended_at.isoformat(),
        "duration_seconds": max(0, round((ended_at - started_at).total_seconds())),
        "ongoing": ongoing,
        "diagnosis": diagnosis.get("key", "unknown")
        if isinstance(diagnosis, dict)
        else "unknown",
        "diagnosis_label": diagnosis.get("label")
        if isinstance(diagnosis, dict)
        else OUTAGE_DIAGNOSES["unknown"],
    }


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _nearest_index(times: list[float], target: float) -> int | None:
    if not times:
        return None
    index = bisect.bisect_left(times, target)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
    return min(candidates, key=lambda i: abs(times[i] - target))


def _system(snapshot: dict[str, Any]) -> dict[str, Any]:
    system = snapshot.get("system")
    return system if isinstance(system, dict) else {}


def _device(snapshot: dict[str, Any]) -> dict[str, Any]:
    device = snapshot.get("device")
    return device if isinstance(device, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
