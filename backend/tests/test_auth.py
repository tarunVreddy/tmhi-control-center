import importlib
import sys

from fastapi.testclient import TestClient

from tmhi_control_center.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    LoginThrottle,
    SessionSigner,
    client_address,
)
from tmhi_control_center.gateway import GatewayAuthenticationError


GATEWAY_PASSWORD = "gateway-secret"


def load_main(monkeypatch, tmp_path, *, saved_password: str = "", auth: bool = True):
    env_path = tmp_path / "control-center.env"
    if saved_password:
        env_path.write_text(f"GATEWAY_PASSWORD={saved_password}\n", encoding="utf-8")
    monkeypatch.setenv("WATCHDOG_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_COLLECTION_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "control-center.db"))
    monkeypatch.setenv("WATCHDOG_ENV_PATH", str(env_path))
    monkeypatch.setenv("FIRMWARE_BACKUP_DIR", str(tmp_path / "firmware-backups"))
    monkeypatch.delenv("GATEWAY_PASSWORD", raising=False)
    monkeypatch.delenv("GATEWAY_PASSWORD_FILE", raising=False)
    if auth:
        monkeypatch.delenv("DASHBOARD_AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_IP_LOCATION_ENABLED", "false")
    monkeypatch.setenv("IPV6_CHECK_ENABLED", "false")
    sys.modules.pop("tmhi_control_center.main", None)
    return importlib.import_module("tmhi_control_center.main")


def fake_gateway(monkeypatch, main, *, accepts: str | None, reachable: bool = True):
    """Stand in for the gateway, accepting only the given password."""
    attempts: list[str] = []

    class FakeGatewayClient:
        def __init__(self, _base_url, _username, password, _timeout, _agent) -> None:
            self.password = password

        async def is_reachable(self) -> bool:
            return reachable

        async def authenticate(self) -> str:
            attempts.append(self.password)
            if self.password != accepts:
                raise GatewayAuthenticationError("Gateway login failed")
            return "token"

        async def close(self) -> None:
            pass

    monkeypatch.setattr(main, "UnifiedGatewayClient", FakeGatewayClient)
    return attempts


def test_signed_out_browser_gets_sign_in_page_and_401s(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        page = client.get("/")
        stale = client.get("/", headers={"If-None-Match": f'"{main.BUILD_ID}"'})
        status = client.get("/api/status")
        reboot = client.post("/api/reboot", json={"force": True})
        docs = client.get("/docs")
        schema = client.get("/openapi.json")
        health = client.get("/healthz")
        version = client.get("/api/version")
        stylesheet = client.get("/static/styles.css")

    assert page.status_code == 200
    assert 'id="signinForm"' in page.text
    assert "tmhi-build" not in page.text
    # The sign-in page is what iOS fetches without cookies; its icon URL is
    # fingerprinted like the dashboard's.
    assert "/static/apple-touch-icon.png?v=dev" not in page.text
    assert "/static/apple-touch-icon.png?v=" in page.text
    assert page.headers["cache-control"] == "no-store"
    # A cached dashboard must not be revalidated for a signed-out browser.
    assert stale.status_code == 200
    assert 'id="signinForm"' in stale.text
    for response in (status, reboot, docs, schema):
        assert response.status_code == 401
        assert response.json() == {"detail": "Sign in required"}
    assert health.status_code == 200
    assert version.status_code == 200
    assert stylesheet.status_code == 200


def test_root_icons_are_served_without_a_session(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        touch = client.get("/apple-touch-icon.png")
        sized = client.get("/apple-touch-icon-180x180-precomposed.png")
        favicon = client.get("/favicon.ico")
        not_an_icon = client.get("/apple-touch-icon-evil/../../api/status")
        manifest = client.get("/static/site.webmanifest")

    for response in (touch, sized):
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == (main.STATIC_DIR / "apple-touch-icon.png").read_bytes()
    assert favicon.status_code == 200
    assert not_an_icon.status_code in (401, 404)
    # The icons have transparent rounded corners, so they are not maskable.
    assert {icon["purpose"] for icon in manifest.json()["icons"]} == {"any"}
    # iOS home-screen icons are 180x180; the manifest offers one at that size.
    icons = {icon["sizes"]: icon["src"] for icon in manifest.json()["icons"]}
    assert icons["180x180"] == "/static/apple-touch-icon.png"
    assert manifest.json()["id"] == manifest.json()["scope"] == "/"
    assert client_head_ok(main)


def client_head_ok(main) -> bool:
    with TestClient(main.app) as client:
        return client.head("/apple-touch-icon.png").status_code == 200


def test_saved_password_signs_in_without_asking_the_gateway(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)
    attempts = fake_gateway(monkeypatch, main, accepts=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        login = client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})
        page = client.get("/")
        config = client.get("/api/config")

    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie
    assert attempts == []
    assert f'<meta name="tmhi-build" content="{main.BUILD_ID}" />' in page.text
    assert config.status_code == 200


def test_cookie_is_secure_behind_https_proxy(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        login = client.post(
            "/api/auth/login",
            json={"password": GATEWAY_PASSWORD},
            headers={"X-Forwarded-Proto": "https"},
        )

    assert "Secure" in login.headers["set-cookie"]


def test_wrong_password_is_rejected_then_throttled(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)
    attempts = fake_gateway(monkeypatch, main, accepts=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        failures = [
            client.post("/api/auth/login", json={"password": "guess"}) for _ in range(5)
        ]
        throttled = client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})
        status = client.get("/api/status")

    assert [response.status_code for response in failures] == [401] * 5
    assert failures[0].json() == {"detail": "Incorrect password"}
    assert "set-cookie" not in failures[0].headers
    # Even the right password waits out the lockout.
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) > 0
    assert status.status_code == 401
    assert attempts == ["guess"] * 5


def test_throttle_is_per_forwarded_client(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)
    fake_gateway(monkeypatch, main, accepts=GATEWAY_PASSWORD)
    attacker = {"X-Forwarded-For": "203.0.113.9"}
    owner = {"X-Forwarded-For": "spoofed, 192.168.12.50"}

    # As seen through httpd, which reaches the container from the Docker bridge.
    with TestClient(main.app, client=("172.18.0.1", 50000)) as client:
        for _ in range(5):
            client.post("/api/auth/login", json={"password": "guess"}, headers=attacker)
        blocked = client.post(
            "/api/auth/login",
            json={"password": GATEWAY_PASSWORD},
            headers=attacker,
        )
        allowed = client.post(
            "/api/auth/login",
            json={"password": GATEWAY_PASSWORD},
            headers=owner,
        )

    assert blocked.status_code == 429
    assert allowed.status_code == 200


def test_first_sign_in_is_checked_by_the_gateway(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    attempts = fake_gateway(monkeypatch, main, accepts=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        wrong = client.post("/api/auth/login", json={"password": "guess"})
        right = client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})
        config = client.get("/api/config")

    assert wrong.status_code == 401
    assert right.status_code == 200
    assert attempts == ["guess", GATEWAY_PASSWORD]
    assert config.status_code == 200
    # Kept in memory only: signing in must not undo a deliberate Forget.
    assert main.settings.gateway_password == GATEWAY_PASSWORD
    assert main.settings.gateway_password_source == "runtime"
    assert GATEWAY_PASSWORD not in (tmp_path / "control-center.env").read_text(
        encoding="utf-8"
    )


def test_unreachable_gateway_is_reported_when_nothing_is_saved(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    fake_gateway(monkeypatch, main, accepts=GATEWAY_PASSWORD, reachable=False)

    with TestClient(main.app) as client:
        response = client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})

    assert response.status_code == 503


def test_password_changed_on_gateway_replaces_saved_one(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password="old-password")
    fake_gateway(monkeypatch, main, accepts="new-password")

    with TestClient(main.app) as client:
        client.post("/api/auth/login", json={"password": "old-password"})
        old_cookie = client.cookies.get(SESSION_COOKIE)
        assert client.get("/api/status").status_code == 200

        client.cookies.clear()
        login = client.post("/api/auth/login", json={"password": "new-password"})
        new_status = client.get("/api/status")
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE, old_cookie)
        old_status = client.get("/api/status")

    assert login.status_code == 200
    assert new_status.status_code == 200
    # The old password's sessions end with it.
    assert old_status.status_code == 401
    assert main.settings.gateway_password_source == "saved"
    assert "GATEWAY_PASSWORD=new-password" in (tmp_path / "control-center.env").read_text(
        encoding="utf-8"
    )


def test_saving_a_new_password_keeps_the_saver_signed_in(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password="old-password")
    fake_gateway(monkeypatch, main, accepts="new-password")

    with TestClient(main.app) as client:
        client.post("/api/auth/login", json={"password": "old-password"})
        saved = client.post(
            "/api/gateway/login",
            json={"gateway_password": "new-password", "remember": True},
        )
        status = client.get("/api/status")

    assert saved.status_code == 200
    assert status.status_code == 200


def test_forgetting_the_password_signs_everyone_out(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})
        forget = client.delete("/api/gateway/login")
        status = client.get("/api/status")

    assert forget.status_code == 200
    assert status.status_code == 401


def test_sign_out_clears_the_cookie(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, saved_password=GATEWAY_PASSWORD)

    with TestClient(main.app) as client:
        client.post("/api/auth/login", json={"password": GATEWAY_PASSWORD})
        logout = client.post("/api/auth/logout")
        status = client.get("/api/status")

    assert logout.status_code == 200
    assert status.status_code == 401


def test_auth_can_be_disabled(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path, auth=False)

    with TestClient(main.app) as client:
        page = client.get("/")
        status = client.get("/api/status")

    assert "tmhi-build" in page.text
    assert status.status_code == 200


def test_session_signer(tmp_path) -> None:
    password = {"value": GATEWAY_PASSWORD}
    key_path = tmp_path / "session.key"
    signer = SessionSigner(str(key_path), lambda: password["value"])
    cookie = signer.issue(now=1_000)

    assert signer.remaining_seconds(cookie, now=1_000) == SESSION_MAX_AGE_SECONDS
    assert signer.remaining_seconds(cookie, now=1_000 + SESSION_MAX_AGE_SECONDS) == 0
    assert signer.remaining_seconds(cookie.replace("v1.", "v1.9"), now=1_000) == 0
    tampered = cookie[:-1] + ("1" if cookie[-1] == "0" else "0")
    assert signer.remaining_seconds(tampered, now=1_000) == 0
    assert signer.remaining_seconds("garbage", now=1_000) == 0
    assert signer.remaining_seconds(None, now=1_000) == 0
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"

    # The key survives a restart.
    reloaded = SessionSigner(str(key_path), lambda: password["value"])
    assert reloaded.remaining_seconds(cookie, now=1_000) > 0

    password["value"] = "changed"
    assert signer.remaining_seconds(cookie, now=1_000) == 0
    password["value"] = ""
    assert signer.remaining_seconds(signer.issue(now=1_000), now=1_000) == 0


def test_login_throttle_window() -> None:
    throttle = LoginThrottle(window_seconds=60, max_failures_per_client=2, max_gateway_checks=3)
    throttle.record_failure("a", now=0)
    assert throttle.client_retry_after("a", now=1) == 0
    throttle.record_failure("a", now=1)
    assert throttle.client_retry_after("a", now=2) == 59
    assert throttle.client_retry_after("b", now=2) == 0
    assert throttle.client_retry_after("a", now=61) == 0
    throttle.clear("a")

    for moment in range(3):
        throttle.record_gateway_check(now=moment)
    assert throttle.gateway_retry_after(now=3) > 0
    assert throttle.gateway_retry_after(now=60) == 0


def test_client_address() -> None:
    assert client_address("172.18.0.1", "203.0.113.9") == "203.0.113.9"
    assert client_address("172.18.0.1", "1.2.3.4, 2001:db8::1") == "2001:db8::1"
    assert client_address("172.18.0.1", None) == "172.18.0.1"
    # A public peer cannot pick its own throttle bucket.
    assert client_address("8.8.8.8", "10.0.0.1") == "8.8.8.8"
    assert client_address(None, None) == "unknown"
