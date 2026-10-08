import importlib
import io
import sys
import zipfile
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def load_main(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHDOG_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_COLLECTION_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "control-center.db"))
    monkeypatch.setenv("WATCHDOG_ENV_PATH", str(tmp_path / "control-center.env"))
    monkeypatch.setenv("FIRMWARE_BACKUP_DIR", str(tmp_path / "firmware-backups"))
    monkeypatch.delenv("GATEWAY_PASSWORD", raising=False)
    monkeypatch.delenv("GATEWAY_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("OPENCELLID_API_KEY", raising=False)
    monkeypatch.delenv("OPENCELLID_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PUBLIC_IP_LOCATION_ENABLED", "false")
    monkeypatch.setenv("IPV6_CHECK_ENABLED", "false")
    # Sign-in has its own tests in test_auth.py.
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "false")
    sys.modules.pop("tmhi_control_center.main", None)
    return importlib.import_module("tmhi_control_center.main")


def test_dashboard_is_served(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        response = client.get("/")
        script = client.get("/static/app.js")

    assert response.status_code == 200
    assert "Control Center" in response.text
    assert script.status_code == 200
    assert "window.setInterval(refreshLiveData, LIVE_POLL_INTERVAL_MS)" in script.text
    assert "setInterval(() => refreshAll" not in script.text


def test_dashboard_carries_its_build_and_is_revalidated(monkeypatch, tmp_path) -> None:
    import hashlib
    import re

    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        page = client.get("/")
        version = client.get("/api/version")
        again = client.get("/", headers={"If-None-Match": page.headers["etag"]})

    build = version.json()["build"]
    assert re.fullmatch(r"[0-9a-f]{12}", build)
    assert f'<meta name="tmhi-build" content="{build}" />' in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert version.headers["cache-control"] == "no-store"
    assert again.status_code == 304

    # Each asset URL carries a hash of that file, never a hand-set tag.
    for name in ("app.js", "styles.css", "apple-touch-icon.png", "site.webmanifest"):
        expected = hashlib.sha256((main.STATIC_DIR / name).read_bytes()).hexdigest()[:12]
        assert f"/static/{name}?v={expected}" in page.text
    assert "?v=dev" not in page.text


def test_gateway_overview_endpoint(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeGateway:
        async def overview(self):
            return {
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "detection": {"reachable": True, "api_type": "unified"},
                "signal": {"score": 88, "quality": "Excellent", "metrics": []},
                "device": {"model": "TMOG4AR"},
                "connection": {"network_type": "5G"},
                "wifi": {},
                "sections": [],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/overview")
            history_response = client.get("/api/gateway/telemetry/history?hours=6")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    assert response.json()["signal"]["score"] == 88
    assert response.json()["device"]["model"] == "TMOG4AR"
    assert history_response.status_code == 200
    assert history_response.json()["count"] == 1
    assert history_response.json()["points"][0]["signal_score"] == 88


def test_gateway_clients_endpoint(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeGateway:
        async def connected_devices(self, *, online_vendor_lookup: bool = False):
            return {
                "count": 1,
                "online_vendor_lookup": online_vendor_lookup,
                "devices": [
                    {
                        "hostname": "Kevin-iPad",
                        "mac_address": "AA:BB:CC:xx:xx:xx",
                        "identification": {"name": "Apple iPad"},
                    }
                ],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/clients?online_lookup=true")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["online_vendor_lookup"] is True


def test_homelab_snapshot_includes_readiness_and_docker_lab_guide(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeWatchdog:
        async def stop(self) -> None:
            pass

        async def status_snapshot(self):
            return {
                "internet_online": True,
                "gateway_reachable": True,
                "dry_run": True,
                "watchdog_enabled": True,
            }

    class FakeGateway:
        async def overview(self):
            return {
                "observed_at": "2026-07-24T00:00:00+00:00",
                "detection": {"reachable": True, "api_type": "unified"},
                "signal": {
                    "score": 82,
                    "quality": "Good",
                    "metrics": [
                        {"key": "sinr", "label": "SINR", "score": 80, "value": "18 dB"},
                    ],
                },
                "device": {"model": "TMO-G4AR", "serial": "XX00Z1E82", "macId": "18:60:41:00:00:05"},
                "connection": {
                    "network_type": "5G",
                    "band": "n41",
                    "cell_id": "1841925",
                },
                "wifi": {},
                "sections": [],
            }

        async def wifi_config(self):
            return {"ssid": "HomeLab", "radio_enabled": False}

        async def connected_devices(self, *, online_vendor_lookup: bool = False):
            return {
                "count": 1,
                "devices": [
                    {
                        "hostname": "nas",
                        "ip_address": "192.168.12.20",
                        "mac_address": "AA:BB:CC:11:22:33",
                        "mac_oui": "AA:BB:CC",
                        "ipv6_addresses": [
                            {"address": "2001:db8:a:1::20", "mac": None},
                        ],
                    }
                ],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        original_watchdog = main.watchdog
        main.gateway = FakeGateway()
        main.watchdog = FakeWatchdog()
        try:
            response = client.get("/api/homelab/snapshot")
        finally:
            main.gateway = original_gateway
            main.watchdog = original_watchdog

    assert response.status_code == 200
    payload = response.json()
    assert payload["insights"]["readiness"]["score"] > 50
    docker_lab = payload["insights"]["docker_lab"]
    assert docker_lab["title"] == "G4AR Docker lab"
    assert len(docker_lab["steps"]) == 3
    assert "not a raw eMMC" in docker_lab["safety"][0]
    assert payload["config"]["gateway_password_configured"] is False
    assert payload["clients"]["count"] == 1
    # The export is for sharing, so it masks what the dashboard shows in full.
    nas = payload["clients"]["devices"][0]
    assert nas["mac_address"] == "AA:BB:CC:xx:xx:xx"
    assert nas["mac_oui"] == "AA:BB:CC"
    assert nas["ipv6_addresses"] == "[redacted]"
    assert payload["overview"]["device"]["serial"] == "•••• 1E82"
    assert payload["overview"]["device"]["macId"] == "18:60:41:xx:xx:xx"
    assert "2001:db8" not in response.text


def test_gateway_map_endpoint_reports_tower_identity(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeGateway:
        async def overview(self):
            return {
                "observed_at": "2026-07-24T00:00:00+00:00",
                "detection": {"reachable": True, "api_type": "unified"},
                "signal": {"score": 78, "quality": "Good", "metrics": []},
                "device": {"model": "TMOG4AR"},
                "connection": {
                    "network_type": "5G",
                    "plmn": "310260",
                    "tac": "12345",
                    "cell_id": "987654",
                    "pci": 321,
                    "band": "n41",
                },
                "wifi": {},
                "sections": [],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/map?include_nearby=false")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    payload = response.json()
    assert payload["map"]["library"] == "leaflet"
    assert payload["provider"]["configured"] is False
    assert payload["connected"]["identity"]["queryable"] is True
    assert payload["connected"]["identity"]["mcc"] == 310
    assert payload["connected"]["identity"]["mnc"] == 260
    assert payload["connected"]["identity"]["radio"] == "NR"
    assert payload["tower_lock"]["supported"] is False


def test_map_settings_update_saves_location_and_opencellid_key(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    env_path = tmp_path / "control-center.env"

    with TestClient(main.app) as client:
        response = client.post(
            "/api/map/settings",
            json={
                "latitude": 40.1,
                "longitude": -75.2,
                "radius_km": 0.75,
                "opencellid_api_key": "tower-key",
            },
        )
        saved_settings = env_path.read_text(encoding="utf-8")
        cleared = client.post(
            "/api/map/settings",
            json={"clear_opencellid_api_key": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["map"]["latitude"] == 40.1
    assert payload["map"]["longitude"] == -75.2
    assert payload["map"]["radius_km"] == 0.75
    assert payload["map"]["opencellid_configured"] is True
    assert "MAP_LATITUDE=40.1\n" in saved_settings
    assert "MAP_LONGITUDE=-75.2\n" in saved_settings
    assert "MAP_RADIUS_KM=0.75\n" in saved_settings
    assert "OPENCELLID_API_KEY=tower-key\n" in saved_settings
    assert cleared.status_code == 200
    assert cleared.json()["map"]["opencellid_configured"] is False
    assert "OPENCELLID_API_KEY=\n" in env_path.read_text(encoding="utf-8")


def test_advanced_modem_lab_requires_acknowledgement_and_saves_settings(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    env_path = tmp_path / "control-center.env"

    with TestClient(main.app) as client:
        blocked = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "acknowledged": False,
            },
        )
        saved = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "acknowledged": True,
            },
        )
        saved_settings = env_path.read_text(encoding="utf-8")
        disabled = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "disabled",
                "acknowledged": False,
            },
        )

    assert blocked.status_code == 409
    assert saved.status_code == 200
    payload = saved.json()["advanced_modem"]
    assert payload["mode"] == "g4ar_unlock_lab"
    assert payload["enabled"] is True
    assert payload["docker_direct"] is True
    assert payload["capabilities"]["cell_lock"]["supported"] is False
    assert payload["capabilities"]["cell_lock"]["status"] == "not_exposed_by_stock_api"
    assert payload["capabilities"]["tx_power_override"]["supported"] is False
    assert "ADVANCED_MODEM_MODE=g4ar_unlock_lab\n" in saved_settings
    assert "ADVANCED_MODEM_CONTROL_URL=\n" in saved_settings
    assert "ADVANCED_MODEM_ACKNOWLEDGED=true\n" in saved_settings
    assert disabled.json()["advanced_modem"]["enabled"] is False


def test_advanced_modem_lab_uses_docker_direct_workflow(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    env_path = tmp_path / "control-center.env"

    with TestClient(main.app) as client:
        health = client.get("/health")
        saved = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "acknowledged": True,
                "skip_stock_backup": True,
            },
        )

    assert health.status_code == 200
    assert health.json()["service"] == "tmhi-control-center"
    assert health.json()["mode"] == "docker_direct"
    assert health.json()["capabilities"]["stock_recovery_bundle"] is True
    assert health.json()["capabilities"]["raw_firmware_backup"] is False
    assert saved.status_code == 200
    lab = saved.json()["advanced_modem"]
    assert lab["docker_direct"] is True
    assert lab["skip_stock_backup"] is True
    assert lab["capabilities"]["stock_firmware_backup"]["status"] == (
        "docker_recovery_bundle_ready"
    )
    assert lab["g4ar_unlock_lab"]["docker_ready"] is True
    assert lab["g4ar_unlock_lab"]["stock_backup_skipped"] is True
    saved_settings = env_path.read_text(encoding="utf-8")
    assert "ADVANCED_MODEM_CONTROL_URL=\n" in saved_settings
    assert "ADVANCED_SKIP_STOCK_BACKUP=true\n" in saved_settings


def test_g4ar_usb_probe_reports_docker_hardware_boundary(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "control_url": "",
                "acknowledged": True,
            },
        )
        probed = client.post("/api/g4ar/usb/probe")

    assert probed.status_code == 200
    assert probed.json()["status"] == "hardware_bridge_required"
    assert probed.json()["probe"] is None


def test_g4ar_firmware_lab_flash_gate_requires_full_consent(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)

    valid_hash = "a" * 64
    firmware_hash = "b" * 64
    with TestClient(main.app) as client:
        saved = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "control_url": "http://127.0.0.1:8765",
                "acknowledged": True,
                "upload_profile": "prefer_upload",
                "radio_profile": "prefer_lte_anchor_nsa",
            },
        )
        status = client.get("/api/g4ar/firmware/status")
        blocked = client.post(
            "/api/g4ar/firmware/flash",
            json={
                "stock_backup_sha256": valid_hash,
                "firmware_sha256": firmware_hash,
                "consent_phrase": "wrong phrase",
                "backup_verified": True,
                "recovery_verified": True,
                "understands_brick_risk": True,
            },
        )
        fully_consented = client.post(
            "/api/g4ar/firmware/flash",
            json={
                "stock_backup_sha256": valid_hash,
                "firmware_sha256": firmware_hash,
                "consent_phrase": "I OWN THIS G4AR - BACKUP VERIFIED - OVERRIDE RISK ACCEPTED",
                "backup_verified": True,
                "recovery_verified": True,
                "understands_brick_risk": True,
            },
        )

    assert saved.status_code == 200
    lab = saved.json()["advanced_modem"]
    assert lab["mode"] == "g4ar_unlock_lab"
    assert lab["upload_priority"]["profile"] == "prefer_upload"
    assert lab["g4ar_radio"]["profile"] == "prefer_lte_anchor_nsa"
    assert lab["capabilities"]["custom_firmware_flash"]["status"] == (
        "unavailable_no_verified_writer"
    )
    assert status.status_code == 200
    assert status.json()["consent_phrase"] == (
        "I OWN THIS G4AR - BACKUP VERIFIED - OVERRIDE RISK ACCEPTED"
    )
    assert blocked.status_code == 409
    assert "exact consent phrase" in blocked.json()["detail"]
    assert fully_consented.status_code == 501
    assert "not implemented" in fully_consented.json()["detail"]


def test_g4ar_root_research_api_never_enables_root_execution(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    complete_payload = {
        "owns_hardware": True,
        "not_leased_or_financed": True,
        "spare_noncritical_unit": True,
        "hardware_revision_recorded": True,
        "uart_voltage_verified": True,
        "read_only_boot_log_captured": True,
        "full_backup_verified": True,
        "offline_recovery_verified": True,
        "accepts_permanent_brick_risk": True,
        "consent_phrase": "I OWN THIS G4AR - ROOT RESEARCH CAN PERMANENTLY BRICK IT",
    }

    with TestClient(main.app) as client:
        status = client.get("/api/g4ar/root/status")
        blocked = client.post("/api/g4ar/root/assess", json=complete_payload)
        saved = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "control_url": "",
                "acknowledged": True,
            },
        )
        ready = client.post("/api/g4ar/root/assess", json=complete_payload)

    assert status.status_code == 200
    assert status.json()["verified_root_available"] is False
    assert status.json()["root_execution_enabled"] is False
    assert blocked.status_code == 200
    assert blocked.json()["ready_for_read_only_research"] is False
    assert "G4AR unlock / radio lab mode enabled" in blocked.json()["missing"]
    assert saved.status_code == 200
    assert saved.json()["advanced_modem"]["capabilities"]["root_access"]["supported"] is False
    assert ready.status_code == 200
    assert ready.json()["ready_for_read_only_research"] is True
    assert ready.json()["ready_for_rooting"] is False
    assert ready.json()["root_execution_enabled"] is False


def test_g4ar_firmware_backup_requires_unlock_lab(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        blocked = client.post(
            "/api/g4ar/firmware/backup",
            json={"reason": "test"},
        )

    assert blocked.status_code == 409
    assert "Select G4AR unlock" in blocked.json()["detail"]


def test_g4ar_firmware_backup_saves_downloadable_docker_bundle(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    main.settings.firmware_backup_dir = str(tmp_path / "firmware-backups")

    class FakeGateway:
        async def overview(self):
            return {
                "detection": {"reachable": True, "api_type": "unified"},
                "device": {
                    "model": "TMO-G4AR",
                    "firmware": "1.00.12",
                    "hardware": "lab-unit",
                },
                "connection": {"network_type": "5G", "band": "n41"},
                "signal": {"score": 80, "quality": "Good"},
                "radios": [{"technology": "NR", "band": "n41"}],
                "system": {"uptime": "2d 3h"},
                "telemetry": {"advanced_cell_available": True},
                "sections": [],
            }

        async def wifi_config(self):
            return {
                "supported": True,
                "ssid": "HomeLab",
                "radio_enabled": True,
                "sections": [],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        main.settings.gateway_password = "saved-password"
        saved_settings = client.post(
            "/api/advanced-modem/settings",
            json={
                "mode": "g4ar_unlock_lab",
                "acknowledged": True,
            },
        )
        try:
            created = client.post(
                "/api/g4ar/firmware/backup",
                json={"reason": "test"},
            )
            manifest = created.json()
            listed = client.get("/api/g4ar/firmware/backups")
            downloaded = client.get(manifest["download_url"])
        finally:
            main.gateway = original_gateway

    assert saved_settings.status_code == 200
    assert created.status_code == 200
    assert manifest["firmware_version"] == "1.00.12"
    assert manifest["backup_type"] == "docker_stock_recovery_bundle"
    assert manifest["raw_firmware_included"] is False
    assert manifest["flash_backup_requirement_satisfied"] is False
    assert manifest["artifact_count"] == 4
    assert {artifact["name"] for artifact in manifest["artifacts"]} == {
        "gateway-snapshot.json",
        "wifi-configuration.json",
        "restore-notes.md",
        "SHA256SUMS",
    }
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["backups"][0]["id"] == manifest["id"]
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert set(archive.namelist()) == {
            "backup-manifest.json",
            "gateway-snapshot.json",
            "wifi-configuration.json",
            "restore-notes.md",
            "SHA256SUMS",
        }
        notes = archive.read("restore-notes.md").decode("utf-8")
        assert "not a raw firmware image" in notes


def test_gateway_map_limits_opencellid_bbox_radius(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    main.settings.opencellid_api_key = "tower-key"
    main.settings.opencellid_api_key_source = "saved"
    main.settings.map_latitude = 40.0
    main.settings.map_longitude = -75.0
    main.settings.map_radius_km = 8.0

    class FakeGateway:
        async def overview(self):
            return {
                "connection": {
                    "network_type": "5G",
                    "plmn": "310260",
                    "tac": "12345",
                    "cell_id": "987654",
                    "band": "n41",
                },
                "signal": {},
                "sections": [],
            }

        async def close(self) -> None:
            pass

    calls: list[dict[str, str]] = []

    class FakeOpenCellClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url, params):
            calls.append({key: str(value) for key, value in params.items()})

            class Response:
                is_success = True
                status_code = 200

                def json(self):
                    if url.endswith("/cell/getInArea"):
                        return {"count": 0, "cells": []}
                    return {}

            return Response()

    monkeypatch.setattr("tmhi_control_center.towers.httpx.AsyncClient", FakeOpenCellClient)

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/map?include_nearby=true")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["requested_radius_km"] == 8.0
    assert payload["provider"]["search_limited"] is True
    assert payload["provider"]["search_radius_km"] == 0.85
    assert "limited" in payload["notices"][0].lower()
    area_call = next(call for call in calls if "BBOX" in call)
    lat_min, lon_min, lat_max, lon_max = [
        float(part) for part in area_call["BBOX"].split(",")
    ]
    assert lat_max - lat_min < 0.02
    assert lon_max - lon_min < 0.03


def test_gateway_map_estimates_connected_tower_from_nearby_cells(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    main.settings.opencellid_api_key = "tower-key"
    main.settings.opencellid_api_key_source = "saved"
    main.settings.map_latitude = 45.52345
    main.settings.map_longitude = -122.67621
    main.settings.map_radius_km = 0.8

    class FakeGateway:
        async def overview(self):
            return {
                "connection": {
                    "network_type": "registered",
                    "band": "n41",
                    "cell_id": "1841925",
                },
                "signal": {},
                "sections": [],
            }

        async def close(self) -> None:
            pass

    class FakeOpenCellClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url, params):
            class Response:
                is_success = True
                status_code = 200

                def json(self):
                    assert url.endswith("/cell/getInArea")
                    return {
                        "count": 1,
                        "cells": [
                            {
                                "mcc": 310,
                                "mnc": 260,
                                "lac": 12345,
                                "cellid": 7654711319,
                                "radio": "NR",
                                "lat": 45.5301,
                                "lon": -122.6701,
                                "range": 1000,
                                "samples": 1,
                            }
                        ],
                    }

            return Response()

    monkeypatch.setattr("tmhi_control_center.towers.httpx.AsyncClient", FakeOpenCellClient)

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/map?include_nearby=true")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    payload = response.json()
    connected_location = payload["connected"]["location"]
    assert connected_location["cell_id"] == 7654711319
    assert connected_location["connected"] is True
    assert connected_location["match_type"] == "single_radio_candidate"
    assert connected_location["match_confidence"] == "estimated"
    assert payload["nearby"][0]["connected"] is True
    assert "estimated" in payload["notices"][0].lower()


def test_gateway_map_uses_public_ip_location_when_no_saved_center(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)
    main.settings.public_ip_location_enabled = True

    class FakeGateway:
        async def overview(self):
            return {
                "connection": {
                    "network_type": "5G",
                    "band": "n41",
                    "cell_id": "1841925",
                },
                "signal": {},
                "sections": [],
            }

        async def close(self) -> None:
            pass

    class FakeLocation:
        def to_dict(self):
            return {
                "latitude": 40.123456,
                "longitude": -75.654321,
                "provider": "test-ip",
                "city": "Test City",
                "region": "PA",
                "country": "United States",
                "accuracy": "public_ip_city_estimate",
            }

    class FakeLocator:
        async def locate(self):
            return FakeLocation()

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        original_locator = main.public_ip_locator
        main.gateway = FakeGateway()
        main.public_ip_locator = FakeLocator()
        try:
            response = client.get("/api/gateway/map?include_nearby=false")
        finally:
            main.gateway = original_gateway
            main.public_ip_locator = original_locator

    assert response.status_code == 200
    payload = response.json()
    assert payload["map"]["center"] == {
        "latitude": 40.123456,
        "longitude": -75.654321,
        "source": "public_ip",
    }
    assert payload["location"]["center_source"] == "public_ip"
    assert payload["location"]["auto_detected"]["provider"] == "test-ip"


def test_gateway_wifi_update_endpoint_records_event(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeGateway:
        async def update_wifi(self, *, ssid=None, radio_enabled=None):
            return {
                "accepted": True,
                "source": "/network/configuration/v2?set=ap",
                "changed": {
                    "ssid_fields": 2 if ssid else 0,
                    "radio_enabled": radio_enabled,
                },
                "wifi": {"ssid": ssid, "radio_enabled": radio_enabled},
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.post(
                "/api/gateway/wifi",
                json={"ssid": "NewNet", "radio_enabled": False},
            )
            events = client.get("/api/events")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    assert response.json()["wifi"]["ssid"] == "NewNet"
    assert events.status_code == 200
    assert events.json()[0]["kind"] == "wifi_settings_updated"


def test_gateway_wifi_endpoint(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeGateway:
        async def wifi_config(self):
            return {
                "ssid": "KevinNet",
                "radio_enabled": True,
                "radios": [{"band": "5 GHz", "ssid": "KevinNet"}],
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        original_gateway = main.gateway
        main.gateway = FakeGateway()
        try:
            response = client.get("/api/gateway/wifi")
        finally:
            main.gateway = original_gateway

    assert response.status_code == 200
    assert response.json()["ssid"] == "KevinNet"


def test_gateway_test_accepts_supplied_password(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    passwords: list[str] = []

    class FakeGatewayClient:
        def __init__(
            self,
            _base_url: str,
            _username: str,
            password: str,
            _timeout_seconds: float,
            _user_agent: str,
        ) -> None:
            passwords.append(password)

        async def is_reachable(self) -> bool:
            return True

        async def authenticate(self) -> str:
            return "token"

        async def close(self) -> None:
            pass

    monkeypatch.setattr(main, "UnifiedGatewayClient", FakeGatewayClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/gateway/test",
            json={"gateway_password": "entered-password"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "authenticated": True,
        "used_supplied_password": True,
    }
    assert passwords == ["entered-password"]


def test_gateway_login_saves_authenticated_password(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    env_path = tmp_path / "control-center.env"
    passwords: list[str] = []

    class FakeGatewayClient:
        def __init__(
            self,
            _base_url: str,
            _username: str,
            password: str,
            _timeout_seconds: float,
            _user_agent: str,
        ) -> None:
            self.password = password
            passwords.append(password)

        async def is_reachable(self) -> bool:
            return True

        async def authenticate(self) -> str:
            return "token"

        async def close(self) -> None:
            pass

    monkeypatch.setattr(main, "UnifiedGatewayClient", FakeGatewayClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/gateway/login",
            json={"gateway_password": "entered-password", "remember": True},
        )
        config = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "authenticated": True,
        "saved": True,
        "gateway_password_configured": True,
        "gateway_password_source": "saved",
    }
    assert passwords == ["entered-password"]
    assert 'GATEWAY_PASSWORD=entered-password' in env_path.read_text(
        encoding="utf-8"
    )
    assert main.settings.gateway_password == "entered-password"
    assert main.settings.gateway_password_source == "saved"
    assert main.gateway._password == "entered-password"
    assert config.json()["gateway_password_configured"] is True
    assert config.json()["gateway_password_source"] == "saved"


def test_gateway_login_clear_removes_saved_password(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "control-center.env"
    env_path.write_text("GATEWAY_PASSWORD=saved-password\n", encoding="utf-8")
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        response = client.delete("/api/gateway/login")

    assert response.status_code == 200
    assert response.json()["gateway_password_configured"] is False
    assert response.json()["gateway_password_source"] == "none"
    assert "GATEWAY_PASSWORD=\n" in env_path.read_text(encoding="utf-8")
    assert main.settings.gateway_password == ""
    assert main.gateway._password == ""


def test_settings_update_saves_dry_run_and_frequency(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    env_path = tmp_path / "control-center.env"
    main.settings.gateway_password = "saved-password"

    with TestClient(main.app) as client:
        response = client.post(
            "/api/settings",
            json={"dry_run": False, "tests_per_hour": 120},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["tests_per_hour"] == 120
    assert payload["check_interval_seconds"] == 30
    assert main.settings.dry_run is False
    assert main.settings.check_interval_seconds == 30
    saved_settings = env_path.read_text(encoding="utf-8")
    assert "DRY_RUN=false\n" in saved_settings
    assert "CHECK_INTERVAL_SECONDS=30\n" in saved_settings


def test_settings_update_requires_password_before_live_reboots(
    monkeypatch,
    tmp_path,
) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        response = client.post("/api/settings", json={"dry_run": False})

    assert response.status_code == 409
    assert main.settings.dry_run is True


def test_speed_test_schedule_and_manual_run(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeSpeedTestRunner:
        running = False

        async def run(self, profile: str):
            return {
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "profile": profile,
                "provider": "cloudflare",
                "success": True,
                "download_mbps": 150.5,
                "upload_mbps": 18.25,
                "latency_ms": 28.0,
                "jitter_ms": 1.5,
                "bytes_downloaded": 10 * 1024 * 1024,
                "bytes_uploaded": 2 * 1024 * 1024,
                "duration_seconds": 5.0,
                "error": None,
            }

        async def close(self) -> None:
            pass

    with TestClient(main.app) as client:
        settings_response = client.post(
            "/api/speedtest/settings",
            json={
                "cadence": "every_10_minutes",
                "profile": "accurate",
                "timezone_offset_minutes": -420,
                "retention_days": 180,
            },
        )
        original_runner = main.speed_test_manager.runner
        main.speed_test_manager.runner = FakeSpeedTestRunner()
        try:
            run_response = client.post("/api/speedtest/run")
            history_response = client.get("/api/speedtest/history?days=365")
        finally:
            main.speed_test_manager.runner = original_runner

    assert settings_response.status_code == 200
    assert settings_response.json()["cadence"] == "every_10_minutes"
    assert settings_response.json()["profile"]["key"] == "accurate"
    assert settings_response.json()["interval_minutes"] == 10
    assert settings_response.json()["usage"]["runs_per_day"] == 144
    assert settings_response.json()["retention_days"] == 180
    assert settings_response.json()["next_run_at"] is not None
    assert run_response.status_code == 200
    assert run_response.json()["download_mbps"] == 150.5
    assert history_response.json()["successful_count"] == 1
    saved_settings = (tmp_path / "control-center.env").read_text(encoding="utf-8")
    assert "SPEEDTEST_CADENCE=every_10_minutes\n" in saved_settings
    assert "SPEEDTEST_PROFILE=accurate\n" in saved_settings
    assert "SPEEDTEST_TIMEZONE_OFFSET_MINUTES=-420\n" in saved_settings
    assert "SPEEDTEST_RETENTION_DAYS=180\n" in saved_settings


def test_events_endpoint_defaults_to_ten_and_honors_larger_limits(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        for index in range(12):
            client.post("/api/settings", json={"dry_run": True, "tests_per_hour": index + 1})
        default = client.get("/api/events")
        larger = client.get("/api/events?limit=500")
        too_large = client.get("/api/events?limit=501")

    assert default.status_code == 200
    assert len(default.json()) == 10
    # The activity log asks for more than the default; every event comes back.
    assert len(larger.json()) >= 12
    assert too_large.status_code == 422


def test_request_logs_hide_api_keys_and_location(monkeypatch, tmp_path) -> None:
    import logging

    main = load_main(monkeypatch, tmp_path)
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        'HTTP Request: %s %s "%s %d %s"',
        (
            "GET",
            "https://opencellid.org/cell/getInArea?key=pk.abc123&BBOX=40.1%2C-105.0%2C40.2%2C-104.9&limit=50",
            "HTTP/1.1", 200, "OK",
        ),
        None,
    )

    assert main.RedactQueryValues().filter(record) is True
    message = record.getMessage()
    assert "pk.abc123" not in message
    assert "40.1" not in message
    assert "key=<redacted>" in message
    assert "limit=50" in message
