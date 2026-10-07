from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Callable


SESSION_COOKIE = "tmhi_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600
# Paths anyone can reach. The dashboard route picks between the page and the
# sign-in form itself, the health check is Docker's, and the version endpoint
# lets an open page notice a deploy even after its session has lapsed.
PUBLIC_PATHS = frozenset({"/", "/healthz", "/api/version", "/api/auth/login"})
PUBLIC_PREFIXES = ("/static/",)


class SessionSigner:
    """Signs session cookies with a key that also covers the gateway password.

    A cookie is only valid while the password it was issued under is still the
    one configured, so changing or forgetting the password signs every browser
    out without keeping any session list.
    """

    def __init__(self, key_path: str, password_provider: Callable[[], str]) -> None:
        self._key = _load_or_create_key(Path(key_path))
        self._password_provider = password_provider

    def issue(self, now: float | None = None) -> str:
        expires = int((now if now is not None else time.time()) + SESSION_MAX_AGE_SECONDS)
        return f"v1.{expires}.{self._signature(expires)}"

    def remaining_seconds(self, cookie: str | None, now: float | None = None) -> float:
        """Seconds until the cookie expires, or 0 when it is not valid."""
        if not cookie or not self._password_provider():
            return 0
        parts = cookie.split(".")
        if len(parts) != 3 or parts[0] != "v1" or not parts[1].isdigit():
            return 0
        expires = int(parts[1])
        if not hmac.compare_digest(parts[2], self._signature(expires)):
            return 0
        return max(0, expires - (now if now is not None else time.time()))

    def _signature(self, expires: int) -> str:
        password = self._password_provider().encode("utf-8")
        message = f"{expires}|".encode("ascii") + hashlib.sha256(password).digest()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()


class LoginThrottle:
    """Caps failed sign-ins per client and gateway checks overall.

    Wrong guesses that get as far as the gateway could trip its own lockout and
    keep the owner out of its admin page, so those are capped across all
    clients, not just per address.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 900,
        max_failures_per_client: int = 5,
        max_gateway_checks: int = 10,
    ) -> None:
        self.window_seconds = window_seconds
        self.max_failures_per_client = max_failures_per_client
        self.max_gateway_checks = max_gateway_checks
        self._failures: dict[str, deque[float]] = {}
        self._gateway_checks: deque[float] = deque()

    def client_retry_after(self, client: str, now: float | None = None) -> int:
        failures = self._prune(self._failures.get(client), now)
        if failures is None or len(failures) < self.max_failures_per_client:
            return 0
        return self._retry_after(failures, now)

    def gateway_retry_after(self, now: float | None = None) -> int:
        self._prune(self._gateway_checks, now)
        if len(self._gateway_checks) < self.max_gateway_checks:
            return 0
        return self._retry_after(self._gateway_checks, now)

    def record_failure(self, client: str, now: float | None = None) -> None:
        self._failures.setdefault(client, deque()).append(_now(now))

    def record_gateway_check(self, now: float | None = None) -> None:
        self._gateway_checks.append(_now(now))

    def clear(self, client: str) -> None:
        self._failures.pop(client, None)

    def _prune(self, entries: deque[float] | None, now: float | None) -> deque[float] | None:
        if entries is None:
            return None
        cutoff = _now(now) - self.window_seconds
        while entries and entries[0] <= cutoff:
            entries.popleft()
        return entries

    def _retry_after(self, entries: deque[float], now: float | None) -> int:
        return max(1, int(entries[0] + self.window_seconds - _now(now)) + 1)


class RequireSession:
    """ASGI middleware that answers 401 for any non-public path without a session."""

    def __init__(self, app, signer_provider: Callable[[], SessionSigner | None]) -> None:
        self.app = app
        self.signer_provider = signer_provider

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or is_public_path(scope["path"]):
            await self.app(scope, receive, send)
            return
        signer = self.signer_provider()
        if signer is None or signer.remaining_seconds(_scope_cookie(scope)) > 0:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "Sign in required"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def client_address(peer: str | None, forwarded_for: str | None) -> str:
    """The address to throttle on.

    httpd appends the address it saw to X-Forwarded-For, so behind a proxy on a
    private network the last entry is the real client and cannot be forged by
    it. A request straight from a public address keeps its own address.
    """
    peer = peer or "unknown"
    if not forwarded_for:
        return peer
    try:
        trusted_proxy = ipaddress.ip_address(peer).is_private
    except ValueError:
        trusted_proxy = False
    if not trusted_proxy:
        return peer
    last = forwarded_for.split(",")[-1].strip()
    return last or peer


def _scope_cookie(scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            key, _, cookie_value = part.strip().partition("=")
            if key == SESSION_COOKIE:
                return cookie_value
    return None


def _load_or_create_key(path: Path) -> bytes:
    try:
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
        if len(key) >= 32:
            return key
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(key.hex() + "\n", encoding="ascii")
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)
    return key


def _now(now: float | None) -> float:
    return now if now is not None else time.time()
