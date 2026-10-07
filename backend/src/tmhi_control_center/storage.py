from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


MAX_RECENT_EVENTS = 10
TELEMETRY_RETENTION_DAYS = 14
MAX_TELEMETRY_POINTS = 2000
MIN_SPEED_TEST_RETENTION_DAYS = 30
SPEED_TEST_RETENTION_DAYS = 730
MAX_SPEED_TEST_POINTS = 2000


class EventStore:
    def __init__(
        self,
        path: str,
        *,
        speed_test_retention_days: int = SPEED_TEST_RETENTION_DAYS,
    ) -> None:
        self.path = path
        self.speed_test_retention_days = max(
            MIN_SPEED_TEST_RETENTION_DAYS,
            min(int(speed_test_retention_days), SPEED_TEST_RETENTION_DAYS),
        )
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    async def initialize(self) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _initialize() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        kind TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_kind_timestamp ON events(kind, timestamp)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp "
                    "ON telemetry_snapshots(timestamp)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS speed_tests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        trigger TEXT NOT NULL,
                        daypart TEXT NOT NULL,
                        profile TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        download_mbps REAL,
                        upload_mbps REAL,
                        latency_ms REAL,
                        jitter_ms REAL,
                        bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                        bytes_uploaded INTEGER NOT NULL DEFAULT 0,
                        duration_seconds REAL NOT NULL DEFAULT 0,
                        error TEXT
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_speed_tests_timestamp "
                    "ON speed_tests(timestamp)"
                )
                speed_test_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(speed_tests)")
                }
                if "context_json" not in speed_test_columns:
                    # The radio connection each test ran on. Added after the
                    # table shipped, so older databases gain it in place.
                    connection.execute(
                        "ALTER TABLE speed_tests ADD COLUMN context_json TEXT"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS speed_test_schedule (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        next_run_at REAL,
                        slot_index INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )

        async with self._lock:
            await asyncio.to_thread(_initialize)

    async def record(
        self,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        timestamp = timestamp or datetime.now(timezone.utc)
        details_json = json.dumps(details or {}, separators=(",", ":"), default=str)

        def _record() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO events(timestamp, kind, message, details_json) VALUES (?, ?, ?, ?)",
                    (timestamp.timestamp(), kind, message, details_json),
                )

        async with self._lock:
            await asyncio.to_thread(_record)

    async def record_many(
        self,
        events: Iterable[tuple[datetime, str, str, dict[str, Any]]],
    ) -> int:
        rows = [
            (
                timestamp.timestamp(),
                kind,
                message,
                json.dumps(details or {}, separators=(",", ":"), default=str),
            )
            for timestamp, kind, message, details in events
        ]
        if not rows:
            return 0

        def _record() -> None:
            with self._connect() as connection:
                connection.executemany(
                    "INSERT INTO events(timestamp, kind, message, details_json) VALUES (?, ?, ?, ?)",
                    rows,
                )

        async with self._lock:
            await asyncio.to_thread(_record)
        return len(rows)

    async def events_since(
        self,
        kinds: Iterable[str],
        since: datetime,
    ) -> list[dict[str, Any]]:
        kind_list = tuple(kinds)
        if not kind_list:
            return []
        placeholders = ",".join("?" for _ in kind_list)

        def _events() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT id, timestamp, kind, message, details_json FROM events "
                    f"WHERE kind IN ({placeholders}) AND timestamp >= ? "
                    f"ORDER BY timestamp ASC",
                    (*kind_list, since.timestamp()),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "timestamp": datetime.fromtimestamp(
                        row["timestamp"], timezone.utc
                    ).isoformat(),
                    "kind": row["kind"],
                    "message": row["message"],
                    "details": json.loads(row["details_json"]),
                }
                for row in rows
            ]

        async with self._lock:
            return await asyncio.to_thread(_events)

    async def get_meta(self, key: str) -> str | None:
        def _get() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = ?", (key,)
                ).fetchone()
            return row["value"] if row else None

        async with self._lock:
            return await asyncio.to_thread(_get)

    async def set_meta(self, key: str, value: str) -> None:
        def _set() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO app_meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

        async with self._lock:
            await asyncio.to_thread(_set)

    async def recent(self, limit: int = MAX_RECENT_EVENTS) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, MAX_RECENT_EVENTS))

        def _recent() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, timestamp, kind, message, details_json "
                    "FROM events ORDER BY timestamp DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                result.append(
                    {
                        "id": row["id"],
                        "timestamp": datetime.fromtimestamp(
                            row["timestamp"], timezone.utc
                        ).isoformat(),
                        "kind": row["kind"],
                        "message": row["message"],
                        "details": json.loads(row["details_json"]),
                    }
                )
            return result

        async with self._lock:
            return await asyncio.to_thread(_recent)

    async def count_since(self, kinds: Iterable[str], since: datetime) -> int:
        kind_list = tuple(kinds)
        if not kind_list:
            return 0
        placeholders = ",".join("?" for _ in kind_list)

        def _count() -> int:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM events "
                    f"WHERE kind IN ({placeholders}) AND timestamp >= ?",
                    (*kind_list, since.timestamp()),
                ).fetchone()
                return int(row["count"])

        async with self._lock:
            return await asyncio.to_thread(_count)

    async def latest_timestamp(self, kinds: Iterable[str]) -> datetime | None:
        kind_list = tuple(kinds)
        if not kind_list:
            return None
        placeholders = ",".join("?" for _ in kind_list)

        def _latest() -> datetime | None:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT MAX(timestamp) AS timestamp FROM events "
                    f"WHERE kind IN ({placeholders})",
                    kind_list,
                ).fetchone()
            value = row["timestamp"]
            return datetime.fromtimestamp(value, timezone.utc) if value else None

        async with self._lock:
            return await asyncio.to_thread(_latest)

    async def reboots_last_24h(self, now: datetime) -> int:
        return await self.count_since(
            {"reboot_requested", "reboot_uncertain"}, now - timedelta(hours=24)
        )

    async def record_telemetry(self, overview: dict[str, Any]) -> bool:
        snapshot = compact_telemetry_snapshot(overview)
        if snapshot is None:
            return False
        observed_at = _parse_timestamp(overview.get("observed_at"))
        payload_json = json.dumps(snapshot, separators=(",", ":"), default=str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=TELEMETRY_RETENTION_DAYS)

        def _record() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO telemetry_snapshots(timestamp, payload_json) VALUES (?, ?)",
                    (observed_at.timestamp(), payload_json),
                )
                connection.execute(
                    "DELETE FROM telemetry_snapshots WHERE timestamp < ?",
                    (cutoff.timestamp(),),
                )

        async with self._lock:
            await asyncio.to_thread(_record)
        return True

    async def telemetry_history(
        self,
        *,
        hours: int = 6,
        limit: int = 720,
    ) -> dict[str, Any]:
        safe_hours = max(1, min(hours, 24 * TELEMETRY_RETENTION_DAYS))
        safe_limit = max(20, min(limit, MAX_TELEMETRY_POINTS))
        since = datetime.now(timezone.utc) - timedelta(hours=safe_hours)

        def _history() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT timestamp, payload_json FROM telemetry_snapshots "
                    "WHERE timestamp >= ? ORDER BY timestamp ASC",
                    (since.timestamp(),),
                ).fetchall()
            points = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload["observed_at"] = datetime.fromtimestamp(
                    row["timestamp"], timezone.utc
                ).isoformat()
                points.append(payload)
            return _downsample(points, safe_limit)

        async with self._lock:
            points = await asyncio.to_thread(_history)

        return {
            "range_hours": safe_hours,
            "retention_days": TELEMETRY_RETENTION_DAYS,
            "count": len(points),
            "first_observed_at": points[0]["observed_at"] if points else None,
            "last_observed_at": points[-1]["observed_at"] if points else None,
            "series": _available_series(points),
            "points": points,
        }

    async def telemetry_snapshots(self) -> list[tuple[datetime, dict[str, Any]]]:
        """Every stored snapshot, oldest first, at full resolution."""

        def _all() -> list[tuple[datetime, dict[str, Any]]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT timestamp, payload_json FROM telemetry_snapshots "
                    "ORDER BY timestamp ASC"
                ).fetchall()
            return [
                (
                    datetime.fromtimestamp(row["timestamp"], timezone.utc),
                    json.loads(row["payload_json"]),
                )
                for row in rows
            ]

        async with self._lock:
            return await asyncio.to_thread(_all)

    async def oldest_telemetry_timestamp(self) -> datetime | None:
        def _oldest() -> datetime | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT MIN(timestamp) AS timestamp FROM telemetry_snapshots"
                ).fetchone()
            value = row["timestamp"]
            return datetime.fromtimestamp(value, timezone.utc) if value else None

        async with self._lock:
            return await asyncio.to_thread(_oldest)

    async def latest_telemetry_snapshot(
        self,
    ) -> tuple[datetime, dict[str, Any]] | None:
        def _latest() -> tuple[datetime, dict[str, Any]] | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT timestamp, payload_json FROM telemetry_snapshots "
                    "ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            return (
                datetime.fromtimestamp(row["timestamp"], timezone.utc),
                json.loads(row["payload_json"]),
            )

        async with self._lock:
            return await asyncio.to_thread(_latest)

    async def speed_tests_without_context(self) -> list[dict[str, Any]]:
        def _missing() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM speed_tests WHERE context_json IS NULL "
                    "ORDER BY timestamp ASC"
                ).fetchall()
            return [_speed_test_row(row) for row in rows]

        async with self._lock:
            return await asyncio.to_thread(_missing)

    async def set_speed_test_contexts(
        self,
        contexts: Iterable[tuple[int, dict[str, Any]]],
    ) -> int:
        rows = [
            (json.dumps(context, separators=(",", ":"), default=str), test_id)
            for test_id, context in contexts
        ]
        if not rows:
            return 0

        def _set() -> None:
            with self._connect() as connection:
                connection.executemany(
                    "UPDATE speed_tests SET context_json = ? WHERE id = ?",
                    rows,
                )

        async with self._lock:
            await asyncio.to_thread(_set)
        return len(rows)

    async def record_speed_test(
        self,
        result: dict[str, Any],
        *,
        trigger: str,
        daypart: str,
    ) -> None:
        observed_at = _parse_timestamp(result.get("observed_at"))
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.speed_test_retention_days
        )
        context = result.get("context") if isinstance(result.get("context"), dict) else None

        def _record() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO speed_tests(
                        timestamp, trigger, daypart, profile, provider, success,
                        download_mbps, upload_mbps, latency_ms, jitter_ms,
                        bytes_downloaded, bytes_uploaded, duration_seconds, error,
                        context_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observed_at.timestamp(),
                        trigger,
                        daypart,
                        result.get("profile") or "gentle",
                        result.get("provider") or "cloudflare",
                        1 if result.get("success") else 0,
                        result.get("download_mbps"),
                        result.get("upload_mbps"),
                        result.get("latency_ms"),
                        result.get("jitter_ms"),
                        int(result.get("bytes_downloaded") or 0),
                        int(result.get("bytes_uploaded") or 0),
                        float(result.get("duration_seconds") or 0),
                        result.get("error"),
                        json.dumps(context, separators=(",", ":"), default=str)
                        if context
                        else None,
                    ),
                )
                connection.execute(
                    "DELETE FROM speed_tests WHERE timestamp < ?",
                    (cutoff.timestamp(),),
                )

        async with self._lock:
            await asyncio.to_thread(_record)

    async def latest_speed_test(self) -> dict[str, Any] | None:
        def _latest() -> dict[str, Any] | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM speed_tests ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
            return _speed_test_row(row) if row else None

        async with self._lock:
            return await asyncio.to_thread(_latest)

    async def set_speed_test_retention_days(self, days: int) -> int:
        safe_days = max(
            MIN_SPEED_TEST_RETENTION_DAYS,
            min(int(days), SPEED_TEST_RETENTION_DAYS),
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=safe_days)

        def _prune() -> int:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM speed_tests WHERE timestamp < ?",
                    (cutoff.timestamp(),),
                )
                return max(0, int(cursor.rowcount))

        async with self._lock:
            deleted_count = await asyncio.to_thread(_prune)
            self.speed_test_retention_days = safe_days
        return deleted_count

    async def speed_test_history(
        self,
        *,
        days: int = 365,
        limit: int = 1000,
    ) -> dict[str, Any]:
        safe_days = max(1, min(days, self.speed_test_retention_days))
        safe_limit = max(20, min(limit, MAX_SPEED_TEST_POINTS))
        since = datetime.now(timezone.utc) - timedelta(days=safe_days)

        def _history() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM speed_tests WHERE timestamp >= ? "
                    "ORDER BY timestamp ASC",
                    (since.timestamp(),),
                ).fetchall()
            return _downsample([_speed_test_row(row) for row in rows], safe_limit)

        async with self._lock:
            points = await asyncio.to_thread(_history)

        successful = [point for point in points if point["success"]]
        total_bytes = sum(
            point["bytes_downloaded"] + point["bytes_uploaded"] for point in points
        )
        return {
            "range_days": safe_days,
            "retention_days": self.speed_test_retention_days,
            "count": len(points),
            "successful_count": len(successful),
            "failed_count": len(points) - len(successful),
            "total_bytes": total_bytes,
            "averages": _speed_test_averages(successful),
            "dayparts": _speed_test_dayparts(successful),
            "connections": _speed_test_connections(successful),
            "points": points,
        }

    async def get_speed_test_schedule(self) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT next_run_at, slot_index, updated_at "
                    "FROM speed_test_schedule WHERE id = 1"
                ).fetchone()
            if row is None:
                return {"next_run_at": None, "slot_index": 0, "updated_at": None}
            return {
                "next_run_at": datetime.fromtimestamp(row["next_run_at"], timezone.utc)
                if row["next_run_at"] is not None
                else None,
                "slot_index": int(row["slot_index"]),
                "updated_at": datetime.fromtimestamp(
                    row["updated_at"], timezone.utc
                ),
            }

        async with self._lock:
            return await asyncio.to_thread(_get)

    async def set_speed_test_schedule(
        self,
        next_run_at: datetime | None,
        slot_index: int,
    ) -> None:
        updated_at = datetime.now(timezone.utc)

        def _set() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO speed_test_schedule(id, next_run_at, slot_index, updated_at)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        next_run_at = excluded.next_run_at,
                        slot_index = excluded.slot_index,
                        updated_at = excluded.updated_at
                    """,
                    (
                        next_run_at.timestamp() if next_run_at else None,
                        int(slot_index),
                        updated_at.timestamp(),
                    ),
                )

        async with self._lock:
            await asyncio.to_thread(_set)


def compact_telemetry_snapshot(overview: dict[str, Any]) -> dict[str, Any] | None:
    detection = overview.get("detection")
    if not isinstance(detection, dict) or detection.get("reachable") is not True:
        return None

    radios_payload: dict[str, Any] = {}
    radios = overview.get("radios")
    if isinstance(radios, list):
        for radio in radios:
            if not isinstance(radio, dict) or not radio.get("key"):
                continue
            metrics_payload: dict[str, float] = {}
            metrics = radio.get("metrics")
            if isinstance(metrics, list):
                for metric in metrics:
                    if not isinstance(metric, dict) or not metric.get("key"):
                        continue
                    value = metric.get("value")
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        metrics_payload[str(metric["key"])] = float(value)
            cell = radio.get("cell") if isinstance(radio.get("cell"), dict) else {}
            radios_payload[str(radio["key"])] = {
                "active": radio.get("active"),
                "score": radio.get("score"),
                "quality": radio.get("quality"),
                "antenna": radio.get("antenna"),
                "band": cell.get("band"),
                "bandwidth": cell.get("bandwidth"),
                "pci": cell.get("pci"),
                "arfcn": cell.get("arfcn"),
                "cell_id": cell.get("cell_id"),
                "node_id": cell.get("node_id"),
                "metrics": metrics_payload,
            }

    signal = overview.get("signal") if isinstance(overview.get("signal"), dict) else {}
    system = overview.get("system") if isinstance(overview.get("system"), dict) else {}
    temperature = (
        system.get("temperature")
        if isinstance(system.get("temperature"), dict)
        else {}
    )
    connection = (
        overview.get("connection")
        if isinstance(overview.get("connection"), dict)
        else {}
    )
    device = overview.get("device") if isinstance(overview.get("device"), dict) else {}
    snapshot = {
        "signal_score": signal.get("score"),
        "radios": radios_payload,
        "system": {
            "temperature_c": temperature.get("celsius"),
            "uptime_seconds": system.get("uptime_seconds"),
            "registration": system.get("registration"),
        },
        "device": {"firmware": device.get("firmware")},
        "connection": {
            "mode": connection.get("mode") or connection.get("network_type"),
            "band": connection.get("band"),
            "cell_id": connection.get("cell_id"),
        },
    }
    has_measurement = bool(
        radios_payload
        or snapshot["signal_score"] is not None
        or snapshot["system"]["temperature_c"] is not None
    )
    return snapshot if has_measurement else None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _downsample(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(points) <= limit:
        return points
    last_index = len(points) - 1
    indexes = [round(index * last_index / (limit - 1)) for index in range(limit)]
    return [points[index] for index in indexes]


def _available_series(points: list[dict[str, Any]]) -> list[str]:
    series: set[str] = set()
    for point in points:
        if point.get("signal_score") is not None:
            series.add("signal_score")
        system = point.get("system") if isinstance(point.get("system"), dict) else {}
        if system.get("temperature_c") is not None:
            series.add("temperature_c")
        radios = point.get("radios") if isinstance(point.get("radios"), dict) else {}
        for radio_key, radio in radios.items():
            if not isinstance(radio, dict):
                continue
            metrics = radio.get("metrics") if isinstance(radio.get("metrics"), dict) else {}
            for metric_key, value in metrics.items():
                if value is not None:
                    series.add(f"{radio_key}.{metric_key}")
    return sorted(series)


def _speed_test_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "observed_at": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
        "trigger": row["trigger"],
        "daypart": row["daypart"],
        "profile": row["profile"],
        "provider": row["provider"],
        "success": bool(row["success"]),
        "download_mbps": row["download_mbps"],
        "upload_mbps": row["upload_mbps"],
        "latency_ms": row["latency_ms"],
        "jitter_ms": row["jitter_ms"],
        "bytes_downloaded": int(row["bytes_downloaded"]),
        "bytes_uploaded": int(row["bytes_uploaded"]),
        "duration_seconds": row["duration_seconds"],
        "error": row["error"],
        "context": json.loads(row["context_json"]) if row["context_json"] else None,
    }


def _speed_test_averages(points: list[dict[str, Any]]) -> dict[str, float | None]:
    def average(key: str) -> float | None:
        values = [float(point[key]) for point in points if point.get(key) is not None]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "download_mbps": average("download_mbps"),
        "upload_mbps": average("upload_mbps"),
        "latency_ms": average("latency_ms"),
        "jitter_ms": average("jitter_ms"),
    }


def _speed_test_connections(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Averages per radio connection, most-sampled first.

    Keyed by mode and bands rather than cell, so a sector swap on the same
    site does not split the comparison into groups too small to read.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for point in points:
        context = point.get("context")
        if not isinstance(context, dict) or context.get("mode") in (None, "none"):
            continue
        key = f"{context.get('mode')}|{context.get('bands') or ''}"
        groups.setdefault(key, []).append(point)
        bands = context.get("bands")
        labels[key] = f"{context.get('label')} · {bands}" if bands else str(context.get("label"))
    result = [
        {
            "key": key,
            "label": labels[key],
            "count": len(matching),
            **_speed_test_averages(matching),
        }
        for key, matching in groups.items()
    ]
    return sorted(result, key=lambda item: item["count"], reverse=True)


def _speed_test_dayparts(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "night": "Night",
        "morning": "Morning",
        "afternoon": "Afternoon",
        "evening": "Evening",
    }
    result = []
    for key, label in labels.items():
        matching = [point for point in points if point.get("daypart") == key]
        result.append(
            {
                "key": key,
                "label": label,
                "count": len(matching),
                **_speed_test_averages(matching),
            }
        )
    return result
