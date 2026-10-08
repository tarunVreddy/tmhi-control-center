from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .advanced_modem import (
    G4AR_LAB_MODES,
    g4ar_firmware_lab_status,
    validate_flash_consent,
)
from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    LoginThrottle,
    RequireSession,
    SessionSigner,
    client_address,
)
from .config import Settings
from .connection import (
    CONNECTION_EVENT_KINDS,
    CONNECTION_HISTORY_START_KEY,
    OUTAGE_EVENT_KINDS,
    ConnectionChangeTracker,
    connection_context,
    connection_state,
    diagnose_outage,
    outage_summary,
    parse_utc_offset,
)
from .connectivity import ConnectivityChecker
from .credentials import ManagedEnvFile
from .firmware_backup import (
    FirmwareBackupError,
    create_g4ar_firmware_backup,
    get_g4ar_backup_archive,
    list_g4ar_firmware_backups,
)
from .gateway import (
    GatewayAuthenticationError,
    GatewayError,
    UnifiedGatewayClient,
    redact_for_sharing,
)
from .geolocation import PublicIpLocationError, PublicIpLocator
from .g4ar_root import assess_g4ar_root_readiness, g4ar_root_research_status
from .insights import build_homelab_insights
from .ipv6 import IPV6_EVENT_KINDS, Ipv6Monitor
from .speedtest import SpeedTestBusyError, SpeedTestError, SpeedTestManager
from .storage import EventStore, compact_telemetry_snapshot
from .telemetry import GatewayTelemetryCollector
from .towers import build_tower_map_payload
from .usb_lab import UsbProbeError, g4ar_usb_status, probe_g4ar_usb
from .watchdog import Watchdog


settings = Settings.from_env()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class RedactQueryValues(logging.Filter):
    """Hide API keys and location from httpx's per-request log lines.

    httpx logs every URL at INFO, and OpenCellID lookups carry the API key and
    a bounding box around the gateway in the query string.
    """

    PATTERN = re.compile(
        r"(?i)\b(key|api_?key|token|access_token|bbox|lat|lon|lng|latitude|longitude)=[^&\s\"]*"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.PATTERN.sub(r"\1=<redacted>", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


logging.getLogger("httpx").addFilter(RedactQueryValues())

store = EventStore(
    settings.database_path,
    speed_test_retention_days=settings.speedtest_retention_days,
)
managed_env = ManagedEnvFile(settings.managed_env_path)
public_ip_locator = PublicIpLocator()
checker = ConnectivityChecker(
    settings.probe_urls,
    settings.probe_timeout_seconds,
    settings.minimum_successful_probes,
)
gateway = UnifiedGatewayClient(
    settings.gateway_base_url,
    settings.gateway_username,
    settings.gateway_password,
    settings.gateway_timeout_seconds,
    settings.gateway_user_agent,
)
session_signer = (
    SessionSigner(settings.session_key_path, lambda: settings.gateway_password)
    if settings.dashboard_auth_enabled
    else None
)
login_throttle = LoginThrottle()


async def _diagnose_outage() -> dict[str, Any]:
    # The signal endpoint needs no login, so this adds no authentication to a
    # gateway that may already be struggling.
    try:
        snapshot = await gateway.signal_snapshot()
    except Exception as exc:
        return diagnose_outage(None, str(exc))
    return diagnose_outage(snapshot)


async def _speed_test_context() -> dict[str, Any] | None:
    overview = await telemetry_collector.collect_once(max_age_seconds=120)
    return connection_context(compact_telemetry_snapshot(overview))


def _gateway_timezone_offset() -> int | None:
    overview = telemetry_collector.latest or {}
    system = overview.get("system") if isinstance(overview.get("system"), dict) else {}
    return parse_utc_offset(system.get("timezone"))


watchdog = Watchdog(
    settings,
    checker,
    gateway,
    store,
    outage_diagnoser=_diagnose_outage,
)
watchdog_task: asyncio.Task[None] | None = None
speed_test_manager = SpeedTestManager(
    settings,
    store,
    context_provider=_speed_test_context,
    timezone_provider=_gateway_timezone_offset,
)
change_tracker = ConnectionChangeTracker(store)
speed_test_task: asyncio.Task[None] | None = None


async def _gateway_overview_provider() -> dict[str, Any]:
    return await gateway.overview()


telemetry_collector = GatewayTelemetryCollector(
    _gateway_overview_provider,
    store,
    interval_seconds=settings.telemetry_sample_interval_seconds,
    enabled=settings.telemetry_collection_enabled,
    change_tracker=change_tracker,
)
telemetry_task: asyncio.Task[None] | None = None
ipv6_monitor = Ipv6Monitor(store, internet_online=lambda: watchdog.state.internet_online)
ipv6_task: asyncio.Task[None] | None = None
STATIC_DIR = Path(__file__).parent / "static"
FINGERPRINTED_ASSETS = ("app.js", "styles.css")


def _fingerprint_assets(html: str) -> tuple[str, list[str]]:
    fingerprints = []
    for name in FINGERPRINTED_ASSETS:
        fingerprint = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]
        fingerprints.append(fingerprint)
        html = re.sub(
            rf"(/static/{re.escape(name)})\?v=[^\"']*",
            rf"\g<1>?v={fingerprint}",
            html,
        )
    return html, fingerprints


def _render_dashboard() -> tuple[str, str]:
    """The dashboard page with its script and stylesheet tagged by content.

    Each ?v= becomes a hash of the file it points at, so a deploy that changes
    a file changes its URL and no browser can pair new markup with an old
    script. The build ID covers all three files and is stamped into the page,
    which compares it with /api/version to notice a newer deploy while open.
    """
    source = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html, fingerprints = _fingerprint_assets(source)
    digest = hashlib.sha256(source.encode("utf-8"))
    for fingerprint in fingerprints:
        digest.update(fingerprint.encode("ascii"))
    build = digest.hexdigest()[:12]
    html = html.replace(
        '<meta name="tmhi-build" content="dev" />',
        f'<meta name="tmhi-build" content="{build}" />',
    )
    return html, build


DASHBOARD_HTML, BUILD_ID = _render_dashboard()
LOGIN_HTML, _ = _fingerprint_assets((STATIC_DIR / "login.html").read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global watchdog_task, speed_test_task, telemetry_task, ipv6_task
    await store.initialize()
    try:
        await change_tracker.initialize()
    except Exception:
        # History backfill is a convenience; never let it stop the watchdog.
        logger.exception("Connection history backfill failed")
    await speed_test_manager.initialize()
    watchdog_task = asyncio.create_task(watchdog.run(), name="tmhi-control-center")
    speed_test_task = asyncio.create_task(
        speed_test_manager.run_scheduler(),
        name="tmhi-speed-test-scheduler",
    )
    telemetry_task = asyncio.create_task(
        telemetry_collector.run(),
        name="tmhi-gateway-telemetry-collector",
    )
    if settings.ipv6_check_enabled:
        ipv6_task = asyncio.create_task(ipv6_monitor.run(), name="tmhi-ipv6-monitor")
    try:
        yield
    finally:
        await watchdog.stop()
        if watchdog_task:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        if speed_test_task:
            speed_test_task.cancel()
            try:
                await speed_test_task
            except asyncio.CancelledError:
                pass
        await telemetry_collector.stop()
        if telemetry_task:
            telemetry_task.cancel()
            try:
                await telemetry_task
            except asyncio.CancelledError:
                pass
        if ipv6_task:
            ipv6_task.cancel()
            try:
                await ipv6_task
            except asyncio.CancelledError:
                pass
        await ipv6_monitor.close()
        await speed_test_manager.stop()
        await checker.close()
        await gateway.close()


app = FastAPI(
    title="TMHI Control Center",
    version=__version__,
    description="Local Docker control center for T-Mobile Home Internet gateways.",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

app.add_middleware(RequireSession, signer_provider=lambda: session_signer)


class DashboardLoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=512, repr=False)


class RebootRequest(BaseModel):
    force: bool = False


class GatewayTestRequest(BaseModel):
    gateway_password: str = Field(default="", max_length=512, repr=False)


class GatewayLoginRequest(BaseModel):
    gateway_password: str = Field(..., min_length=1, max_length=512, repr=False)
    remember: bool = True


class SettingsUpdateRequest(BaseModel):
    dry_run: bool | None = None
    tests_per_hour: int | None = Field(default=None, ge=1, le=720)


class AdvancedModemSettingsUpdateRequest(BaseModel):
    mode: Literal[
        "disabled",
        "g4ar_unlock_lab",
        "g4ar_firmware_lab",
    ] = "disabled"
    acknowledged: bool = False
    upload_profile: Literal["balanced", "prefer_upload", "low_latency_upload"] = "balanced"
    radio_profile: Literal[
        "auto",
        "prefer_lte_anchor_nsa",
        "lte_only_test",
        "nr_sa",
        "scan_only",
    ] = "auto"
    skip_stock_backup: bool = False


class G4ARFirmwareFlashRequest(BaseModel):
    stock_backup_sha256: str = Field(default="", max_length=64)
    firmware_sha256: str = Field(default="", max_length=64)
    consent_phrase: str = Field(default="", max_length=128)
    backup_verified: bool = False
    recovery_verified: bool = False
    understands_brick_risk: bool = False


class G4ARFirmwareBackupRequest(BaseModel):
    reason: str = Field(default="ui_request", max_length=80)


class G4ARRootReadinessRequest(BaseModel):
    owns_hardware: bool = False
    not_leased_or_financed: bool = False
    spare_noncritical_unit: bool = False
    hardware_revision_recorded: bool = False
    uart_voltage_verified: bool = False
    read_only_boot_log_captured: bool = False
    full_backup_verified: bool = False
    offline_recovery_verified: bool = False
    accepts_permanent_brick_risk: bool = False
    consent_phrase: str = Field(default="", max_length=128)


class MapSettingsUpdateRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, ge=0.25, le=100)
    opencellid_api_key: str | None = Field(default=None, max_length=256, repr=False)
    clear_opencellid_api_key: bool = False
    clear_location: bool = False


class SpeedTestSettingsUpdateRequest(BaseModel):
    cadence: Literal[
        "disabled",
        "every_5_minutes",
        "every_10_minutes",
        "every_15_minutes",
        "every_30_minutes",
        "hourly",
        "every_6_hours",
        "every_12_hours",
        "daily",
        "weekly",
        "monthly",
    ] = "disabled"
    profile: Literal[
        "gentle",
        "standard",
        "accurate",
        "extended",
        "maximum",
    ] = "gentle"
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    retention_days: int | None = Field(default=None, ge=30, le=730)


class WifiUpdateRequest(BaseModel):
    ssid: str | None = Field(default=None, min_length=1, max_length=32)
    radio_enabled: bool | None = None


def _tests_per_hour_to_interval_seconds(tests_per_hour: int) -> int:
    return max(5, round(3600 / tests_per_hour))


def _gateway_exception(exc: Exception) -> HTTPException:
    status_code = 409 if isinstance(exc, GatewayAuthenticationError) else 502
    return HTTPException(status_code=status_code, detail=str(exc))


def _overview_has_location(overview: dict[str, Any]) -> bool:
    if not overview:
        return False
    text = str(overview).lower()
    return (
        ("latitude" in text or "'lat'" in text or '"lat"' in text)
        and ("longitude" in text or "'lon'" in text or '"lon"' in text or "lng" in text)
    )


async def _collect_or_error(label: str, call, default: Any) -> Any:
    try:
        return await call()
    except Exception as exc:
        logger.warning("%s snapshot collection failed: %s", label, exc)
        if isinstance(default, dict):
            return {**default, "error": str(exc)}
        return default


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard(request: Request) -> Response:
    remaining = (
        session_signer.remaining_seconds(request.cookies.get(SESSION_COOKIE))
        if session_signer
        else SESSION_MAX_AGE_SECONDS
    )
    if remaining <= 0:
        return HTMLResponse(
            LOGIN_HTML,
            headers={"Cache-Control": "no-store", "Vary": "Cookie"},
        )
    # no-cache makes the browser ask every time instead of guessing a reuse
    # period from Last-Modified; the ETag keeps an unchanged answer to a 304.
    headers = {"Cache-Control": "no-cache", "ETag": f'"{BUILD_ID}"', "Vary": "Cookie"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        response: Response = Response(status_code=304, headers=headers)
    else:
        response = HTMLResponse(DASHBOARD_HTML, headers=headers)
    # Opening the app at least every couple of weeks keeps it signed in.
    if remaining < SESSION_MAX_AGE_SECONDS / 2:
        _set_session_cookie(request, response)
    return response


def _set_session_cookie(request: Request, response: Response) -> None:
    if session_signer is None:
        return
    response.set_cookie(
        SESSION_COOKIE,
        session_signer.issue(),
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )


@app.post("/api/auth/login")
async def auth_login(body: DashboardLoginRequest, request: Request) -> JSONResponse:
    client = client_address(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )
    retry_after = login_throttle.client_retry_after(client)
    if retry_after:
        raise _too_many_attempts(retry_after)

    configured = settings.gateway_password
    matches_configured = bool(configured) and hmac.compare_digest(
        body.password.encode("utf-8"),
        configured.encode("utf-8"),
    )
    if not matches_configured:
        # The gateway is the authority: with no password saved yet, or after it
        # was changed on the gateway, a password the gateway accepts is right.
        retry_after = login_throttle.gateway_retry_after()
        if retry_after:
            login_throttle.record_failure(client)
            raise _too_many_attempts(retry_after)
        login_throttle.record_gateway_check()
        accepted = await _gateway_accepts(body.password, password_configured=bool(configured))
        if not accepted:
            login_throttle.record_failure(client)
            await store.record(
                "dashboard_login_failed",
                "Dashboard sign-in failed",
                {"client": client},
            )
            raise HTTPException(status_code=401, detail="Incorrect password")
        # Replace a stale password where it was kept. With none configured, it
        # stays in memory so signing in does not undo a deliberate Forget.
        await _apply_gateway_password(
            body.password,
            remember=settings.gateway_password_source == "saved",
        )

    login_throttle.clear(client)
    await store.record("dashboard_login", "Dashboard signed in", {"client": client})
    response = JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})
    _set_session_cookie(request, response)
    return response


@app.post("/api/auth/logout")
async def auth_logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def _too_many_attempts(retry_after: int) -> HTTPException:
    minutes = max(1, round(retry_after / 60))
    return HTTPException(
        status_code=429,
        detail=f"Too many sign-in attempts. Try again in about {minutes} min.",
        headers={"Retry-After": str(retry_after)},
    )


async def _gateway_accepts(password: str, *, password_configured: bool) -> bool:
    candidate = UnifiedGatewayClient(
        settings.gateway_base_url,
        settings.gateway_username,
        password,
        settings.gateway_timeout_seconds,
        settings.gateway_user_agent,
    )
    try:
        if not await candidate.is_reachable():
            if password_configured:
                return False
            raise HTTPException(
                status_code=503,
                detail="The gateway could not be reached to check this password",
            )
        await candidate.authenticate()
        return True
    except GatewayAuthenticationError:
        return False
    except GatewayError as exc:
        if password_configured:
            return False
        raise HTTPException(
            status_code=502,
            detail=f"The gateway could not check this password: {exc}",
        ) from exc
    finally:
        await candidate.close()


@app.get("/favicon.ico", include_in_schema=False)
async def root_favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon{variant:path}", include_in_schema=False)
async def root_touch_icon(variant: str) -> FileResponse:
    # iOS asks for sized and precomposed variants it never links to; one icon
    # serves them all, and anything else under this name is not ours.
    if not variant.endswith(".png") or "/" in variant:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "apple-touch-icon.png", media_type="image/png")


@app.get("/api/version")
async def version() -> JSONResponse:
    return JSONResponse(
        {"version": __version__, "build": BUILD_ID},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return await watchdog.status_snapshot()


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return settings.safe_summary()


@app.get("/api/homelab/snapshot")
async def homelab_snapshot(
    include_nearby: bool = Query(default=False),
) -> dict[str, Any]:
    safe_config = settings.safe_summary()
    status_payload = await _collect_or_error(
        "status",
        watchdog.status_snapshot,
        {},
    )
    overview = await _collect_or_error(
        "gateway overview",
        gateway.overview,
        {},
    )
    wifi = await _collect_or_error(
        "gateway Wi-Fi",
        gateway.wifi_config,
        {},
    )
    clients = await _collect_or_error(
        "gateway clients",
        lambda: gateway.connected_devices(online_vendor_lookup=False),
        {"count": 0, "devices": []},
    )
    map_payload = await build_tower_map_payload(
        overview if isinstance(overview, dict) else {},
        settings=settings,
        include_nearby=include_nearby,
    )
    events_payload = await store.recent(50)
    firmware_backups = list_g4ar_firmware_backups(settings.firmware_backup_dir)
    insights = build_homelab_insights(
        config=safe_config,
        status=status_payload if isinstance(status_payload, dict) else {},
        overview=overview if isinstance(overview, dict) else {},
        wifi=wifi if isinstance(wifi, dict) else {},
        clients=clients if isinstance(clients, dict) else {"count": 0, "devices": []},
        map_data=map_payload,
        events=events_payload,
        firmware_backups=firmware_backups,
    )
    # The dashboard shows identifiers in full to the signed-in owner; this
    # export is meant to be shared, so it masks them.
    return redact_for_sharing({
        "generated_at": map_payload.get("observed_at"),
        "version": __version__,
        "config": safe_config,
        "status": status_payload,
        "overview": overview,
        "wifi": wifi,
        "clients": clients,
        "map": map_payload,
        "events": events_payload,
        "firmware_backups": firmware_backups,
        "insights": insights,
    })


@app.get("/api/gateway/overview")
async def gateway_overview() -> dict[str, Any]:
    try:
        return await telemetry_collector.collect_once(max_age_seconds=15)
    except Exception as exc:
        logger.exception("Gateway overview failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/gateway/signal")
async def gateway_signal() -> dict[str, Any]:
    try:
        return await gateway.signal_snapshot()
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc
    except Exception as exc:
        logger.exception("Gateway signal snapshot failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/gateway/telemetry/history")
async def gateway_telemetry_history(
    hours: int = Query(default=6, ge=1, le=336),
    limit: int = Query(default=720, ge=20, le=2000),
) -> dict[str, Any]:
    history = await store.telemetry_history(hours=hours, limit=limit)
    history["collector"] = telemetry_collector.status()
    return history


@app.get("/api/connection/history")
async def connection_history(
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    changes = await store.events_since(CONNECTION_EVENT_KINDS, since)
    # Start a little earlier so an outage already under way at the window's
    # edge is paired with the event that began it.
    outage_events = await store.events_since(OUTAGE_EVENT_KINDS, since - timedelta(hours=1))
    outages = outage_summary(
        outage_events,
        now=now,
        since=since,
        days=days,
        timezone_offset_minutes=speed_test_manager.timezone_offset_minutes(),
        check_interval_seconds=settings.check_interval_seconds,
    )
    restarts = [event for event in changes if event["kind"] == "gateway_restarted"]
    latest = telemetry_collector.latest
    return {
        "range_days": days,
        "range_start": since.isoformat(),
        "range_end": now.isoformat(),
        "known_since": await store.get_meta(CONNECTION_HISTORY_START_KEY),
        "current": connection_state(compact_telemetry_snapshot(latest))
        if latest
        else None,
        "changes": list(reversed(changes))[:500],
        "change_count": sum(1 for event in changes if event["kind"] == "connection_changed"),
        "restart_count": len(restarts),
        "unrequested_restart_count": sum(
            1 for event in restarts if not event["details"].get("requested_by_app")
        ),
        "outages": outages,
        "ipv6": ipv6_monitor.summary(
            await store.events_since(IPV6_EVENT_KINDS, since - timedelta(days=30)),
            since=since,
            now=now,
        ),
    }


@app.get("/api/gateway/details")
async def gateway_details() -> dict[str, Any]:
    try:
        return await gateway.device_details()
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc


@app.get("/api/speedtest/status")
async def speed_test_status() -> dict[str, Any]:
    return await speed_test_manager.status()


@app.get("/api/speedtest/history")
async def speed_test_history(
    days: int = Query(default=365, ge=1, le=730),
    limit: int = Query(default=1000, ge=20, le=2000),
) -> dict[str, Any]:
    return await store.speed_test_history(days=days, limit=limit)


@app.post("/api/speedtest/run")
async def run_speed_test() -> dict[str, Any]:
    try:
        return await speed_test_manager.run(trigger="manual")
    except SpeedTestBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SpeedTestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/speedtest/settings")
async def update_speed_test_settings(
    request: SpeedTestSettingsUpdateRequest,
) -> dict[str, Any]:
    retention_days = (
        request.retention_days
        if request.retention_days is not None
        else settings.speedtest_retention_days
    )
    try:
        managed_env.set_value("SPEEDTEST_CADENCE", request.cadence)
        managed_env.set_value("SPEEDTEST_PROFILE", request.profile)
        managed_env.set_value(
            "SPEEDTEST_TIMEZONE_OFFSET_MINUTES",
            str(request.timezone_offset_minutes),
        )
        managed_env.set_value(
            "SPEEDTEST_RETENTION_DAYS",
            str(retention_days),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Speed test schedule could not be saved",
        ) from exc

    settings.speedtest_cadence = request.cadence
    settings.speedtest_profile = request.profile
    settings.speedtest_timezone_offset_minutes = request.timezone_offset_minutes
    deleted_count = await store.set_speed_test_retention_days(
        retention_days
    )
    settings.speedtest_retention_days = retention_days
    await speed_test_manager.reset_schedule()
    await store.record(
        "speed_test_settings_updated",
        "Speed test schedule updated",
        {
            "cadence": request.cadence,
            "profile": request.profile,
            "timezone_offset_minutes": request.timezone_offset_minutes,
            "retention_days": retention_days,
            "deleted_history_records": deleted_count,
        },
    )
    return await speed_test_manager.status()


@app.get("/api/gateway/clients")
async def gateway_clients(
    online_lookup: bool = Query(default=False),
) -> dict[str, Any]:
    try:
        return await gateway.connected_devices(online_vendor_lookup=online_lookup)
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc
    except Exception as exc:
        logger.exception("Gateway client list failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/gateway/map")
async def gateway_map(
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float | None = Query(default=None, ge=0.25, le=100),
    include_nearby: bool = Query(default=False),
) -> dict[str, Any]:
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422,
            detail="Latitude and longitude must be supplied together",
        )

    errors: list[str] = []
    notices: list[str] = []
    try:
        overview = await gateway.overview()
    except Exception as exc:
        logger.exception("Gateway map overview failed")
        overview = {}
        errors.append(f"Gateway telemetry failed: {exc}")

    public_ip_location: dict[str, Any] | None = None
    if (
        latitude is None
        and longitude is None
        and settings.map_latitude is None
        and settings.map_longitude is None
        and settings.public_ip_location_enabled
        and not _overview_has_location(overview)
    ):
        try:
            public_ip_location = (await public_ip_locator.locate()).to_dict()
        except PublicIpLocationError as exc:
            notices.append(f"Public IP location estimate failed: {exc}")

    payload = await build_tower_map_payload(
        overview,
        settings=settings,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        public_ip_location=public_ip_location,
        include_nearby=include_nearby,
    )
    payload["errors"] = [*errors, *payload.get("errors", [])]
    payload["notices"] = [*notices, *payload.get("notices", [])]
    return payload


@app.get("/api/gateway/location")
async def gateway_location() -> dict[str, Any]:
    try:
        location = await gateway.gps_location()
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc
    except Exception as exc:
        logger.exception("Gateway location lookup failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if location is None:
        raise HTTPException(
            status_code=404,
            detail="This gateway does not report a GPS location",
        )
    return location


@app.get("/api/gateway/wifi")
async def gateway_wifi() -> dict[str, Any]:
    try:
        return await gateway.wifi_config()
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc
    except Exception as exc:
        logger.exception("Gateway Wi-Fi config failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/gateway/wifi")
async def gateway_wifi_update(request: WifiUpdateRequest) -> dict[str, Any]:
    if request.ssid is None and request.radio_enabled is None:
        raise HTTPException(status_code=422, detail="No Wi-Fi changes were requested")
    try:
        result = await gateway.update_wifi(
            ssid=request.ssid,
            radio_enabled=request.radio_enabled,
        )
    except GatewayError as exc:
        raise _gateway_exception(exc) from exc
    except Exception as exc:
        logger.exception("Gateway Wi-Fi update failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await store.record(
        "wifi_settings_updated",
        "Gateway Wi-Fi settings updated from dashboard",
        {
            "ssid_changed": request.ssid is not None,
            "radio_enabled": request.radio_enabled,
            "source": result.get("source"),
        },
    )
    return result


@app.post("/api/settings")
async def update_settings(request: SettingsUpdateRequest) -> dict[str, Any]:
    updated: dict[str, Any] = {}

    if request.dry_run is not None:
        if request.dry_run is False and not settings.gateway_password:
            raise HTTPException(
                status_code=409,
                detail="Save the gateway admin password before turning Dry Run off",
            )
        try:
            managed_env.set_value("DRY_RUN", str(request.dry_run).lower())
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Dry Run could not be saved",
            ) from exc
        settings.dry_run = request.dry_run
        updated["dry_run"] = request.dry_run

    if request.tests_per_hour is not None:
        interval_seconds = _tests_per_hour_to_interval_seconds(request.tests_per_hour)
        try:
            managed_env.set_value("CHECK_INTERVAL_SECONDS", str(interval_seconds))
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Test frequency could not be saved",
            ) from exc
        settings.check_interval_seconds = interval_seconds
        updated["tests_per_hour"] = request.tests_per_hour
        updated["check_interval_seconds"] = interval_seconds

    if updated:
        await store.record(
            "settings_updated",
            "Dashboard settings updated",
            updated,
        )

    return settings.safe_summary()


@app.post("/api/advanced-modem/settings")
async def update_advanced_modem_settings(
    request: AdvancedModemSettingsUpdateRequest,
) -> dict[str, Any]:
    if request.mode != "disabled" and not request.acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Acknowledge the custom firmware and RF compliance warning first",
        )
    try:
        managed_env.set_value("ADVANCED_MODEM_MODE", request.mode)
        managed_env.set_value("ADVANCED_MODEM_CONTROL_URL", "")
        managed_env.set_value(
            "ADVANCED_MODEM_ACKNOWLEDGED",
            str(request.mode != "disabled" and request.acknowledged).lower(),
        )
        managed_env.set_value("ADVANCED_UPLOAD_PROFILE", request.upload_profile)
        managed_env.set_value("ADVANCED_RADIO_PROFILE", request.radio_profile)
        managed_env.set_value(
            "ADVANCED_SKIP_STOCK_BACKUP",
            str(request.mode != "disabled" and request.skip_stock_backup).lower(),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Advanced modem settings could not be saved",
        ) from exc

    settings.advanced_modem_mode = request.mode
    settings.advanced_modem_control_url = ""
    settings.advanced_modem_acknowledged = request.mode != "disabled" and request.acknowledged
    settings.advanced_upload_profile = request.upload_profile
    settings.advanced_radio_profile = request.radio_profile
    settings.advanced_skip_stock_backup = (
        request.mode != "disabled" and request.skip_stock_backup
    )

    await store.record(
        "advanced_modem_settings_updated",
        "Advanced modem lab settings updated",
        {
            "mode": settings.advanced_modem_mode,
            "docker_direct": True,
            "acknowledged": settings.advanced_modem_acknowledged,
            "upload_profile": settings.advanced_upload_profile,
            "radio_profile": settings.advanced_radio_profile,
            "skip_stock_backup": settings.advanced_skip_stock_backup,
        },
    )
    return settings.safe_summary()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "tmhi-control-center",
        "version": __version__,
        "mode": "docker_direct",
        "message": (
            "TMHI Control Center is running in Docker-only mode. It can create "
            "stock-API recovery bundles directly; raw firmware, cell lock, and "
            "radio overrides are not exposed by stock G4AR firmware."
        ),
        "capabilities": {
            "health": True,
            "stock_recovery_bundle": True,
            "raw_firmware_backup": False,
            "radio_profile": False,
            "cell_scan": False,
            "cell_lock": False,
            "usb_hardware_probe": False,
            "usb_ethernet_bridge": False,
            "firmware_flash": False,
            "root_access": False,
            "tx_power_override": False,
        },
    }


def _docker_operation_not_implemented(action: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=(
            f"Docker received the {action} request, but stock G4AR firmware does "
            "not expose that operation through its local API. This capability "
            "remains unavailable in the Docker-only workflow."
        ),
    )


@app.post("/g4ar/firmware/backup")
async def legacy_g4ar_backup() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="Use POST /api/g4ar/firmware/backup for the Docker recovery bundle",
    )


@app.post("/modem/radio/profile")
async def docker_radio_profile() -> dict[str, Any]:
    raise _docker_operation_not_implemented("radio profile")


@app.post("/modem/cell/scan")
async def docker_cell_scan() -> dict[str, Any]:
    raise _docker_operation_not_implemented("cell scan")


@app.post("/modem/lock")
async def docker_modem_lock() -> dict[str, Any]:
    raise _docker_operation_not_implemented("tower lock")


@app.get("/g4ar/usb/probe")
async def docker_g4ar_usb_probe() -> dict[str, Any]:
    raise _docker_operation_not_implemented("G4AR USB-C hardware probe")


@app.get("/api/g4ar/usb/status")
async def g4ar_usb_lab_status() -> dict[str, Any]:
    return g4ar_usb_status(settings)


@app.post("/api/g4ar/usb/probe")
async def g4ar_usb_lab_probe() -> dict[str, Any]:
    if settings.advanced_modem_mode not in G4AR_LAB_MODES:
        raise HTTPException(
            status_code=409,
            detail="Select G4AR unlock / radio lab mode before probing the USB-C port",
        )
    if not settings.advanced_modem_acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Acknowledge the owned-hardware research warning before probing",
        )

    try:
        result = await probe_g4ar_usb(settings)
    except UsbProbeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    probe = result.get("probe") or {}
    await store.record(
        "g4ar_usb_probe_completed",
        "G4AR USB-C hardware probe completed",
        {
            "status": result.get("status"),
            "hardware_adapter_ready": result.get("hardware_adapter_ready"),
            "device_count": len(probe.get("devices") or []),
            "ready_for_isolated_test": probe.get("ready_for_isolated_test"),
            "ready_for_lan_bridge": probe.get("ready_for_lan_bridge"),
        },
    )
    return result


@app.get("/api/g4ar/firmware/status")
async def g4ar_firmware_status() -> dict[str, Any]:
    return g4ar_firmware_lab_status(settings)


@app.get("/api/g4ar/root/status")
async def g4ar_root_status() -> dict[str, Any]:
    return g4ar_root_research_status()


@app.post("/api/g4ar/root/assess")
async def g4ar_root_assess(request: G4ARRootReadinessRequest) -> dict[str, Any]:
    request_payload = (
        request.model_dump() if hasattr(request, "model_dump") else request.dict()
    )
    result = assess_g4ar_root_readiness(
        request_payload,
        lab_mode_active=settings.advanced_modem_mode in G4AR_LAB_MODES,
        lab_acknowledged=settings.advanced_modem_acknowledged,
    )
    await store.record(
        "g4ar_root_readiness_assessed",
        "G4AR owner root-research readiness assessed",
        {
            "ready_for_read_only_research": result["ready_for_read_only_research"],
            "root_execution_enabled": False,
            "missing_count": len(result["missing"]),
        },
    )
    return result


@app.get("/api/g4ar/firmware/backups")
async def g4ar_firmware_backups() -> dict[str, Any]:
    return list_g4ar_firmware_backups(settings.firmware_backup_dir)


@app.get("/api/g4ar/firmware/backups/{backup_id}/download")
async def g4ar_firmware_backup_download(backup_id: str) -> FileResponse:
    try:
        archive_path = get_g4ar_backup_archive(
            settings.firmware_backup_dir,
            backup_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{backup_id}-recovery-bundle.zip",
    )


@app.post("/api/g4ar/firmware/backup")
async def g4ar_firmware_backup(request: G4ARFirmwareBackupRequest) -> dict[str, Any]:
    if settings.advanced_modem_mode not in G4AR_LAB_MODES:
        raise HTTPException(
            status_code=409,
            detail="Select G4AR unlock / radio lab mode before creating a stock backup",
        )
    if not settings.advanced_modem_acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Acknowledge the custom firmware and RF compliance warning first",
        )
    if not settings.gateway_password:
        raise HTTPException(
            status_code=409,
            detail="Save the gateway admin password before creating a recovery bundle",
        )

    try:
        manifest = await create_g4ar_firmware_backup(
            settings,
            gateway,
            reason=request.reason,
        )
    except FirmwareBackupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Backup could not be saved: {exc}") from exc

    await store.record(
        "g4ar_recovery_bundle_created",
        "G4AR Docker recovery bundle saved",
        {
            "backup_id": manifest.get("id"),
            "artifact_count": manifest.get("artifact_count"),
            "firmware_version": manifest.get("firmware_version"),
        },
    )
    return manifest


@app.post("/api/g4ar/firmware/flash")
async def g4ar_firmware_flash_gate(request: G4ARFirmwareFlashRequest) -> dict[str, Any]:
    if settings.advanced_modem_mode not in G4AR_LAB_MODES:
        raise HTTPException(
            status_code=409,
            detail="Select G4AR unlock / radio lab mode before preparing a flash operation",
        )
    if not settings.advanced_modem_acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Acknowledge the custom firmware and RF compliance warning first",
        )
    request_payload = (
        request.model_dump() if hasattr(request, "model_dump") else request.dict()
    )
    missing = validate_flash_consent(request_payload)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Flash gate is locked. Missing: {', '.join(missing)}",
        )

    await store.record(
        "g4ar_flash_gate_validated",
        "G4AR firmware override consent gate validated",
        {
            "stock_backup_sha256": request.stock_backup_sha256,
            "firmware_sha256": request.firmware_sha256,
        },
    )
    raise HTTPException(
        status_code=501,
        detail=(
            "Flash consent validated, but firmware writing is not implemented until "
            "a reproducible G4AR write and exact-device recovery method is verified"
        ),
    )


@app.post("/api/map/settings")
async def update_map_settings(request: MapSettingsUpdateRequest) -> dict[str, Any]:
    if (request.latitude is None) != (request.longitude is None):
        raise HTTPException(
            status_code=422,
            detail="Latitude and longitude must be saved together",
        )

    updated: dict[str, Any] = {}

    try:
        if request.clear_location:
            managed_env.clear_value("MAP_LATITUDE")
            managed_env.clear_value("MAP_LONGITUDE")
            settings.map_latitude = None
            settings.map_longitude = None
            updated["map_location_cleared"] = True
        elif request.latitude is not None and request.longitude is not None:
            managed_env.set_value("MAP_LATITUDE", str(request.latitude))
            managed_env.set_value("MAP_LONGITUDE", str(request.longitude))
            settings.map_latitude = request.latitude
            settings.map_longitude = request.longitude
            updated["map_latitude"] = request.latitude
            updated["map_longitude"] = request.longitude

        if request.radius_km is not None:
            managed_env.set_value("MAP_RADIUS_KM", str(request.radius_km))
            settings.map_radius_km = request.radius_km
            updated["map_radius_km"] = request.radius_km

        if request.clear_opencellid_api_key:
            managed_env.clear_value("OPENCELLID_API_KEY")
            if settings.opencellid_api_key_source != "environment":
                settings.opencellid_api_key = ""
                settings.opencellid_api_key_source = "none"
            updated["opencellid_api_key_cleared"] = True
        elif request.opencellid_api_key is not None:
            key = request.opencellid_api_key.strip()
            if key:
                managed_env.set_value("OPENCELLID_API_KEY", key)
                settings.opencellid_api_key = key
                settings.opencellid_api_key_source = "saved"
                updated["opencellid_api_key_saved"] = True
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Map settings could not be saved",
        ) from exc

    if updated:
        await store.record(
            "map_settings_updated",
            "Tower map settings updated",
            updated,
        )

    return settings.safe_summary()


@app.get("/api/events")
async def events(limit: int = Query(default=10, ge=1, le=500)) -> list[dict[str, Any]]:
    return await store.recent(limit)


@app.post("/api/check")
async def check_now() -> dict[str, Any]:
    return await watchdog.check_once(allow_reboot=False)


@app.post("/api/gateway/test")
async def gateway_test(request: GatewayTestRequest | None = None) -> dict[str, Any]:
    try:
        supplied_password = request.gateway_password if request else ""
        if supplied_password:
            test_gateway = UnifiedGatewayClient(
                settings.gateway_base_url,
                settings.gateway_username,
                supplied_password,
                settings.gateway_timeout_seconds,
                settings.gateway_user_agent,
            )
            try:
                reachable = await test_gateway.is_reachable()
                if not reachable:
                    return {
                        "reachable": False,
                        "authenticated": False,
                        "used_supplied_password": True,
                    }
                await test_gateway.authenticate()
                return {
                    "reachable": True,
                    "authenticated": True,
                    "used_supplied_password": True,
                }
            finally:
                await test_gateway.close()
        return await watchdog.test_gateway_login()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/gateway/login", response_model=None)
async def gateway_login(
    request: GatewayLoginRequest,
    http_request: Request,
) -> JSONResponse | dict[str, Any]:
    test_gateway = UnifiedGatewayClient(
        settings.gateway_base_url,
        settings.gateway_username,
        request.gateway_password,
        settings.gateway_timeout_seconds,
        settings.gateway_user_agent,
    )
    try:
        reachable = await test_gateway.is_reachable()
        if not reachable:
            return {
                "reachable": False,
                "authenticated": False,
                "saved": False,
                "gateway_password_configured": bool(settings.gateway_password),
                "gateway_password_source": settings.gateway_password_source,
            }
        await test_gateway.authenticate()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await test_gateway.close()

    password_source = await _apply_gateway_password(
        request.gateway_password,
        remember=request.remember,
    )
    response = JSONResponse(
        {
            "reachable": True,
            "authenticated": True,
            "saved": request.remember,
            "gateway_password_configured": True,
            "gateway_password_source": password_source,
        }
    )
    # A new password invalidates every session, including this one.
    _set_session_cookie(http_request, response)
    return response


async def _apply_gateway_password(password: str, *, remember: bool) -> str:
    if remember:
        try:
            managed_env.set_value("GATEWAY_PASSWORD", password)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Gateway login worked, but the password could not be saved",
            ) from exc
        password_source = "saved"
    else:
        password_source = "runtime"

    settings.gateway_password = password
    settings.gateway_password_source = password_source
    gateway.set_password(password)
    await store.record(
        "gateway_login_saved" if remember else "gateway_login_authenticated",
        (
            "Gateway login saved from dashboard"
            if remember
            else "Gateway login authenticated from dashboard"
        ),
        {"username": settings.gateway_username, "remember": remember},
    )
    return password_source


@app.delete("/api/gateway/login")
async def gateway_login_clear() -> dict[str, Any]:
    try:
        saved_removed = managed_env.clear_value("GATEWAY_PASSWORD")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Saved gateway login could not be cleared",
        ) from exc
    environment_password_active = settings.gateway_password_source == "environment"

    if not environment_password_active:
        settings.gateway_password = ""
        settings.gateway_password_source = "none"
        gateway.set_password("")

    await store.record(
        "gateway_login_cleared",
        "Saved gateway login cleared from dashboard",
        {
            "saved_removed": saved_removed,
            "environment_password_active": environment_password_active,
        },
    )
    return {
        "cleared": saved_removed or not environment_password_active,
        "saved_removed": saved_removed,
        "gateway_password_configured": bool(settings.gateway_password),
        "gateway_password_source": settings.gateway_password_source,
    }


@app.post("/api/reboot")
async def reboot(request: RebootRequest) -> dict[str, Any]:
    try:
        return await watchdog.manual_reboot(force=request.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Manual reboot failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
