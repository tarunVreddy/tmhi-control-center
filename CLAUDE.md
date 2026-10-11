# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local dashboard and watchdog for T-Mobile Home Internet gateways. Two independent clients talk to the gateway's local HTTP API:

- **`backend/`**: a FastAPI app, shipped as a Docker image, that serves the web dashboard and runs 24/7 background jobs (outage watchdog with auto-reboot, telemetry sampling, scheduled speed tests).
- **`android/`**: a native Kotlin app that talks to the gateway directly from the phone, only while it is open. It has no watchdog, scheduler or reboot automation. It does not share code with the backend, so a gateway parsing change usually has to be made in both `gateway.py` and `android/.../core/GatewayClient.kt`.

`web/` is an empty placeholder. The real web UI is `backend/src/tmhi_control_center/static/`.

## Commands

```bash
pip install -r backend/requirements-dev.txt      # Python >= 3.11
pytest -q backend                                 # full suite (what CI runs)
pytest -q backend/tests/test_watchdog.py          # one file
pytest -q backend/tests/test_api.py -k build      # one test by name

docker compose up -d --build                      # build and run from source on :8095 (WEB_PORT overrides)
docker build -t tmhi-control-center:test .        # image build check

gradle -p android :app:assembleDebug              # Android debug APK (JDK 17, SDK 35, Gradle 8.9)
```

There is no linter or formatter configured. CLI diagnostics: `PYTHONPATH=backend/src python -m tmhi_control_center.cli {connectivity|gateway-test|reboot --yes}`, or `tmhi-control-center ...` once the package is installed. Inside the container, `PYTHONPATH` is already `/app/src`.

## Backend architecture

`main.py` builds everything at **import time** from `Settings.from_env()`: the `EventStore`, `UnifiedGatewayClient`, `Watchdog`, `SpeedTestManager`, `GatewayTelemetryCollector` and `ConnectionChangeTracker`. These are module-level singletons, and routes mutate `settings` in place. The `lifespan` hook starts four long-running asyncio tasks: the watchdog, the speed-test scheduler, the telemetry collector and the IPv6 monitor (`ipv6.py`, which reports only once IPv6 has worked from that install). Uvicorn runs with `--workers 1` because all of this state lives in the process.

**Configuration** (`config.py`, `credentials.py`): settings come from process env vars, which take precedence, and otherwise from a managed env file at `/data/control-center.env` (path set by `WATCHDOG_ENV_PATH`). The dashboard writes user changes to that file with `ManagedEnvFile.set_value()` and then updates the live `settings` object, so a settings route has to do both. Secrets also accept a `NAME_FILE` variant. `Settings.safe_summary()` is the redacted view returned to the browser.

**Sign-in** (`auth.py`): the `RequireSession` middleware returns 401 for every path outside `PUBLIC_PATHS` (`/`, `/healthz`, `/api/version`, `/api/auth/login`, `/static/`) unless the request has a valid `tmhi_session` cookie. Users sign in with the gateway admin password. The cookie's signature also covers that password, so changing the password signs everyone out. `/` serves `static/login.html` until the user is signed in. `DASHBOARD_AUTH_ENABLED=false` turns the gate off. Because of the gate, `curl` against `/api/*` on a deployed instance gets 401.

**Gateway client** (`gateway.py`): `UnifiedGatewayClient` covers the Arcadyan, Sagemcom and Sercomm TMI v1 API (`/TMI/v1/...`) and also detects Nokia CGI gateways. It tries several base URLs and ports (port 80 for G5AR, 8080 for the others) and several path spellings for each endpoint, then remembers which one worked. Basic telemetry (`gateway?get=all|signal`) needs no login. Clients, cell, SIM and Wi-Fi data need a bearer token from `/auth/login`. Login-free telemetry must keep working when no password is saved. The Aim page (`signal_snapshot()`) polls every 2s, so it keeps its own token for the cell endpoint, which is the only source of CQI. It logs in again only when that token is refused, and backs off for 60s if a fresh token fails too. Tests inject `httpx.MockTransport` through the `transport=` argument.

**Watchdog** (`watchdog.py`): a state machine driven by `ConnectivityChecker` probes, with a startup grace period, a failure threshold, a post-reboot grace period, a cooldown and a 24h reboot cap. `DRY_RUN=true` is the default and records `reboot_dry_run` events in place of rebooting. When a gateway reboots, probes keep failing for a while (the grace and cooldown windows), so these safeguards must not be loosened casually.

**Storage** (`storage.py`): a single SQLite file (`/data/control-center.db`) holds the events, compact telemetry snapshots (14-day retention), speed-test history and connection history. `connection.py` derives connection-change and outage events from those snapshots.

**Other modules:** `towers.py` (OpenCellID and the map payload), `insights.py` (Homelab readiness score), `speedtest.py`, `geolocation.py` (public-IP location), and the G4AR lab modules (`advanced_modem.py`, `firmware_backup.py`, `g4ar_root.py`, `usb_lab.py`). The flash and lock endpoints are intentionally gated or return "not implemented".

## Frontend

The frontend is plain HTML, CSS and JS with no build step: `static/index.html`, `static/app.js` (one large file) and `static/styles.css`. Leaflet is used for the map. `app.js` holds global `state` and an `api()` fetch helper, and polls live data every 60s.

Cache busting is automatic. `main.py` rewrites each `?v=dev` in `index.html` and `login.html` to a content hash of that file and stamps a build ID into `<meta name="tmhi-build">`. The page compares that ID with `/api/version` and reloads itself when it changes, which matters because the dashboard is used as an iOS home-screen app. Never hand-edit the `?v=` tags. A new fingerprinted asset must be added to `FINGERPRINTED_ASSETS`.

## Tests

The API tests (`test_api.py`) use `load_main(monkeypatch, tmp_path)`. It points `DATABASE_PATH`, `WATCHDOG_ENV_PATH` and `FIRMWARE_BACKUP_DIR` at `tmp_path`, disables the watchdog, telemetry, public-IP lookup, IPv6 check and dashboard sign-in (`test_auth.py` covers sign-in), and re-imports `tmhi_control_center.main`. A test that touches `main` needs this because of the import-time singletons. `asyncio_mode = "auto"` is set, so async tests need no decorator.

## Project rules (from CONTRIBUTING / PR template)

- Keep gateway automation safe by default, and keep `DRY_RUN=true` as the default.
- Changes to outage detection, reboot limits, cooldowns, authentication or gateway requests need tests.
- Add support for a new gateway only once its API behavior is understood and can fail safely. Do not add aggressive endpoint fuzzing or access-control bypasses.
- PRs should say which physical gateway model was tested, or "Not tested on physical hardware".

## Repo and CI

This repo is a fork of kevin1724/tmhi-control-center. CI (`.github/workflows/docker-publish.yml`) runs pytest on Python 3.11 and 3.12, builds the image on PRs and publishes to Docker Hub from `main`. `android-apk.yml` builds the debug APK when `android/**` changes.
