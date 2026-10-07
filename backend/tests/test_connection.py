from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tmhi_control_center.config import Settings
from tmhi_control_center.connection import (
    CONNECTION_EVENT_KINDS,
    ConnectionChangeTracker,
    backfill_history,
    connection_state,
    detect_changes,
    diagnose_outage,
    outage_summary,
    parse_utc_offset,
)
from tmhi_control_center.storage import EventStore
from tmhi_control_center.watchdog import Watchdog

from test_watchdog import FakeChecker, FakeGateway


T0 = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)


def snapshot(
    *,
    lte: tuple[str, str, str | None] | None = None,
    nr: tuple[str, str, str | None] | None = None,
    site: str | None = None,
    uptime: int = 100_000,
    registration: str = "registered",
    firmware: str = "1.00.06",
) -> dict:
    radios = {}
    for key, cell in (("lte", lte), ("nr", nr)):
        if cell:
            band, cell_id, node_id = cell
            radios[key] = {
                "active": True,
                "band": band,
                "cell_id": cell_id,
                "node_id": node_id,
                "metrics": {"rsrp": -70.0, "sinr": 25.0, "cqi": 14.0},
            }
    return {
        "radios": radios,
        "system": {"uptime_seconds": uptime, "registration": registration},
        "device": {"firmware": firmware},
        "connection": {"cell_id": site},
    }


def test_connection_state_classifies_standalone_and_non_standalone() -> None:
    sa = connection_state(snapshot(nr=("n41", "302", None), site="1000001"))
    nsa = connection_state(
        snapshot(lte=("b2", "12", "20001"), nr=("n41", "12", "20001"), site="20001")
    )
    assert (sa["mode"], sa["label"], sa["bands"]) == ("5g_sa", "5G standalone", "n41")
    assert (nsa["mode"], nsa["bands"]) == ("nsa", "b2 + n41")


def test_mode_switch_and_sector_swap_are_described() -> None:
    sa = snapshot(nr=("n41", "302", None), site="1000001")
    sector = snapshot(nr=("n41", "312", None), site="1000001")
    nsa = snapshot(lte=("b2", "12", "20001"), nr=("n41", "12", "20001"), site="20001")

    [(_, kind, message, details)] = detect_changes(T0, sa, T0 + timedelta(minutes=1), sector)
    assert kind == "connection_changed"
    assert details["change"] == "sector"
    assert "cell 302 → 312" in message

    [(_, _, message, details)] = detect_changes(T0, sa, T0 + timedelta(minutes=1), nsa)
    assert details["change"] == "mode"
    assert message == "Connection changed from 5G standalone (n41) to LTE + 5G (b2 + n41)"


def test_node_ids_missing_from_older_snapshots_do_not_read_as_a_change() -> None:
    older = snapshot(lte=("b2", "12", None), nr=("n41", "12", None), site="20001")
    newer = snapshot(lte=("b2", "12", "20001"), nr=("n41", "12", "20001"), site="20001")
    assert detect_changes(T0, older, T0 + timedelta(minutes=1), newer) == []


def test_restart_is_detected_from_boot_time_not_uptime_alone() -> None:
    before = snapshot(nr=("n41", "302", None), site="1", uptime=400_000)
    # Seen two hours later having booted 90 minutes ago: a restart in between.
    after = snapshot(nr=("n41", "302", None), site="1", uptime=5_400)
    [(booted_at, kind, message, details)] = detect_changes(
        T0, before, T0 + timedelta(hours=2), after
    )
    assert kind == "gateway_restarted"
    assert booted_at == T0 + timedelta(minutes=30)
    assert message.startswith("Gateway restarted after 4d 15h")
    assert details["previous_uptime_seconds"] == 400_000

    # A long collection gap with the gateway up throughout is not a restart.
    still_up = snapshot(nr=("n41", "302", None), site="1", uptime=400_000 + 7_200)
    assert detect_changes(T0, before, T0 + timedelta(hours=2), still_up) == []


def test_registration_and_firmware_changes_are_logged() -> None:
    before = snapshot(nr=("n41", "302", None), site="1")
    after = snapshot(
        nr=("n41", "302", None),
        site="1",
        uptime=100_060,
        registration="searching",
        firmware="1.00.07",
    )
    kinds = {
        kind: message
        for _, kind, message, _ in detect_changes(T0, before, T0 + timedelta(minutes=1), after)
    }
    assert kinds == {
        "registration_changed": "Network registration changed from registered to searching",
        "firmware_changed": "Gateway firmware changed from 1.00.06 to 1.00.07",
    }


@pytest.mark.asyncio
async def test_backfill_runs_once_and_attributes_app_reboots(tmp_path) -> None:
    store = EventStore(str(tmp_path / "history.db"))
    await store.initialize()
    overview = {
        "observed_at": T0.isoformat(),
        "detection": {"reachable": True},
        "device": {"firmware": "1.00.06"},
        "signal": {"score": 90},
        "radios": [
            {
                "key": "nr",
                "active": True,
                "cell": {"band": "n41", "cell_id": "302"},
                "metrics": [{"key": "sinr", "value": 27}],
            }
        ],
        "system": {"uptime_seconds": 200_000},
        "connection": {"cell_id": "1000001"},
    }
    await store.record_telemetry(overview)
    await store.record_telemetry(
        {
            **overview,
            "observed_at": (T0 + timedelta(minutes=10)).isoformat(),
            "system": {"uptime_seconds": 240},
        }
    )
    await store.record("reboot_requested", "Gateway reboot requested", timestamp=T0 + timedelta(minutes=5))
    await store.record_speed_test(
        {
            "observed_at": (T0 + timedelta(minutes=9)).isoformat(),
            "success": True,
            "download_mbps": 700.0,
            "upload_mbps": 90.0,
        },
        trigger="scheduled",
        daypart="night",
    )

    assert await backfill_history(store) == {"events": 1, "speed_tests": 1}
    assert await backfill_history(store) == {"events": 0, "speed_tests": 0}

    [restart] = await store.events_since(CONNECTION_EVENT_KINDS, T0 - timedelta(days=1))
    assert restart["details"]["requested_by_app"] is True
    assert restart["details"]["backfilled"] is True
    assert restart["message"].endswith("requested by this app")

    history = await store.speed_test_history(days=730)
    assert history["points"][0]["context"]["label"] == "5G standalone"
    assert history["connections"][0]["label"] == "5G standalone · n41"


@pytest.mark.asyncio
async def test_tracker_resumes_from_the_last_stored_snapshot(tmp_path) -> None:
    store = EventStore(str(tmp_path / "tracker.db"))
    await store.initialize()
    await store.record_telemetry(
        {
            "observed_at": T0.isoformat(),
            "detection": {"reachable": True},
            "radios": [
                {
                    "key": "nr",
                    "active": True,
                    "cell": {"band": "n41", "cell_id": "302"},
                    "metrics": [{"key": "sinr", "value": 27}],
                }
            ],
            "system": {"uptime_seconds": 1_000},
            "connection": {"cell_id": "1000001"},
        }
    )
    tracker = ConnectionChangeTracker(store)
    await tracker.initialize()

    events = await tracker.observe(
        T0 + timedelta(minutes=1),
        snapshot(lte=("b2", "12", "20001"), nr=("n41", "12", "20001"), site="20001", uptime=1_060),
    )
    assert [kind for _, kind, _, _ in events] == ["connection_changed"]
    stored = await store.events_since(CONNECTION_EVENT_KINDS, T0)
    assert stored[0]["details"]["to"]["mode"] == "nsa"


def test_outage_diagnosis_separates_radio_from_upstream_failures() -> None:
    connected = {
        "registration": "registered",
        "radios": [
            {
                "key": "nr",
                "active": True,
                "cell": {"band": "n41"},
                "metrics": [{"key": "sinr", "value": 27}, {"key": "bars", "value": 5}],
            }
        ],
    }
    upstream = diagnose_outage(connected)
    assert upstream["key"] == "upstream"
    assert upstream["radios"] == {"nr": {"band": "n41", "sinr": 27}}
    assert diagnose_outage({**connected, "registration": "searching"})["key"] == "cellular"
    assert diagnose_outage({"registration": "registered", "radios": []})["key"] == "cellular"
    assert diagnose_outage(None, "timed out")["key"] == "gateway_unreachable"


def test_outage_summary_pairs_events_and_buckets_by_local_hour() -> None:
    def event(kind: str, at: datetime, details: dict | None = None) -> dict:
        return {"kind": kind, "timestamp": at.isoformat(), "details": details or {}}

    since = T0 - timedelta(hours=6)
    events = [
        # Ended before the window: dropped.
        event("internet_lost", since - timedelta(minutes=30)),
        event("internet_restored", since - timedelta(minutes=29)),
        # 07:00 UTC is 01:00 at -06:00.
        event("internet_lost", T0 + timedelta(hours=1), {"diagnosis": {"key": "upstream", "label": "x"}}),
        event("internet_restored", T0 + timedelta(hours=1, seconds=20)),
        event("internet_lost", T0 + timedelta(hours=2)),
    ]
    now = T0 + timedelta(hours=2, minutes=10)
    summary = outage_summary(
        events,
        now=now,
        since=since,
        days=1,
        timezone_offset_minutes=-360,
        check_interval_seconds=20,
    )
    assert summary["count"] == 2
    assert summary["hourly"][1] == 1 and summary["hourly"][2] == 1
    assert summary["recent"][0]["ongoing"] is True
    assert summary["recent"][0]["duration_seconds"] == 600
    assert summary["recent"][1]["diagnosis"] == "upstream"
    assert {item["key"]: item["count"] for item in summary["diagnoses"]} == {
        "upstream": 1,
        "unknown": 1,
    }


def test_parse_utc_offset() -> None:
    assert parse_utc_offset("-06:00") == -360
    assert parse_utc_offset("+05:30") == 330
    assert parse_utc_offset("UTC-7") == -420
    assert parse_utc_offset("-0600") == -360
    assert parse_utc_offset("Mountain") is None
    assert parse_utc_offset(None) is None


@pytest.mark.asyncio
async def test_watchdog_records_outage_diagnosis_and_duration(tmp_path) -> None:
    settings = Settings(
        startup_grace_seconds=0,
        failure_threshold_seconds=3600,
        database_path=str(tmp_path / "watchdog.db"),
    )
    store = EventStore(settings.database_path)
    await store.initialize()
    checker = FakeChecker(False)

    async def diagnoser() -> dict:
        return {"key": "upstream", "label": "Radio connected; failure past the gateway"}

    watchdog = Watchdog(settings, checker, FakeGateway(), store, outage_diagnoser=diagnoser)
    await watchdog.initialize()
    await watchdog.check_once(allow_reboot=False)
    watchdog.state.failure_started_at -= timedelta(seconds=40)
    checker.online = True
    await watchdog.check_once(allow_reboot=False)

    events = {event["kind"]: event for event in await store.recent()}
    assert events["internet_lost"]["details"]["diagnosis"]["key"] == "upstream"
    assert events["internet_restored"]["details"]["outage_seconds"] >= 40


def test_parse_utc_offset_resolves_named_zones_for_the_moment() -> None:
    summer = datetime(2026, 7, 1, tzinfo=timezone.utc)
    winter = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert parse_utc_offset("America/Denver", at=summer) == -360
    assert parse_utc_offset("America/Denver", at=winter) == -420
    assert parse_utc_offset("Not/AZone") is None
