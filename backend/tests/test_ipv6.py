from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tmhi_control_center.ipv6 import (
    IPV6_EVENT_KINDS,
    Ipv6Monitor,
    container_ipv6_addresses,
)
from tmhi_control_center.storage import EventStore


EPOCH = datetime.fromtimestamp(0, timezone.utc)


class Network:
    """Answers the IPv6 probes, with a switch to break them."""

    def __init__(self, address: str = "2001:db8:a:1::5") -> None:
        self.up = True
        self.address = address

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("Network is unreachable")
        if request.url.path == "/cdn-cgi/trace":
            return httpx.Response(200, text=f"fl=1\nip={self.address}\n")
        return httpx.Response(200, json={"Status": 0})


async def make_monitor(tmp_path, network, *, addresses=("fd00:db8::2",), online=True):
    store = EventStore(str(tmp_path / "events.db"))
    await store.initialize()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monitor = Ipv6Monitor(
        store,
        internet_online=lambda: online,
        addresses_provider=lambda: list(addresses),
        transport=httpx.MockTransport(network.handler),
        sleep=fake_sleep,
    )
    await monitor.initialize()
    return monitor, store, sleeps


async def kinds(store):
    return [event["kind"] for event in await store.events_since(IPV6_EVENT_KINDS, EPOCH)]


def summary(monitor, events):
    now = datetime.now(timezone.utc)
    return monitor.summary(events, since=now - timedelta(days=14), now=now)


@pytest.mark.asyncio
async def test_no_container_address_means_nothing_is_checked_or_reported(tmp_path) -> None:
    network = Network()
    monitor, store, _ = await make_monitor(tmp_path, network, addresses=())

    result = await monitor.check_once()

    assert result["available"] is False
    assert summary(monitor, []) == {"reported": False, "available": False, "confirmed": False}
    await monitor.close()


@pytest.mark.asyncio
async def test_never_working_ipv6_is_not_reported(tmp_path) -> None:
    # An IPv4-only host: Docker gave the container an address that goes nowhere.
    network = Network()
    network.up = False
    monitor, store, _ = await make_monitor(tmp_path, network)

    await monitor.check_once()
    await monitor.check_once()

    assert await kinds(store) == []
    assert summary(monitor, [])["reported"] is False
    await monitor.close()


@pytest.mark.asyncio
async def test_outage_is_recorded_after_a_confirming_retry_and_restored(tmp_path) -> None:
    network = Network()
    monitor, store, sleeps = await make_monitor(tmp_path, network)

    first = await monitor.check_once()
    assert first["ok"] and first["confirmed"]
    assert first["public_prefix"] == "2001:db8:a:1::/64"

    network.up = False
    await monitor.check_once()
    # One failure is retried before it counts.
    assert sleeps == [30]
    assert await kinds(store) == ["ipv6_lost"]
    report = summary(monitor, await store.events_since(IPV6_EVENT_KINDS, EPOCH))
    assert report["status"] == "down"
    assert report["outages"]["periods"][0]["ongoing"] is True

    network.up = True
    await monitor.check_once()
    events = await store.events_since(IPV6_EVENT_KINDS, EPOCH)
    assert [event["kind"] for event in events] == ["ipv6_lost", "ipv6_restored"]
    assert events[1]["details"]["duration_seconds"] >= 0
    report = summary(monitor, events)
    assert report["status"] == "ok"
    assert report["outages"]["count"] == 1
    assert report["outages"]["periods"][0]["ongoing"] is False
    await monitor.close()


@pytest.mark.asyncio
async def test_a_single_blip_is_not_an_outage(tmp_path) -> None:
    network = Network()
    monitor, store, _ = await make_monitor(tmp_path, network)
    await monitor.check_once()

    calls = {"count": 0}
    original = network.handler

    async def flaky(request):
        calls["count"] += 1
        if calls["count"] <= 2:  # both probes of the first attempt fail
            raise httpx.ConnectError("blip")
        return await original(request)

    monitor._client._transport = httpx.MockTransport(flaky)
    await monitor.check_once()

    assert await kinds(store) == []
    await monitor.close()


@pytest.mark.asyncio
async def test_full_internet_outage_is_not_counted_as_ipv6(tmp_path) -> None:
    network = Network()
    store = EventStore(str(tmp_path / "events.db"))
    await store.initialize()
    online = {"value": True}
    monitor = Ipv6Monitor(
        store,
        internet_online=lambda: online["value"],
        addresses_provider=lambda: ["fd00:db8::2"],
        transport=httpx.MockTransport(network.handler),
        sleep=lambda _seconds: _noop(),
    )
    await monitor.check_once()

    online["value"] = False
    network.up = False
    await monitor.check_once()

    assert await kinds(store) == []
    await monitor.close()


async def _noop() -> None:
    pass


@pytest.mark.asyncio
async def test_prefix_change_is_recorded(tmp_path) -> None:
    network = Network("2001:db8:a:1::5")
    monitor, store, _ = await make_monitor(tmp_path, network)
    await monitor.check_once()

    network.address = "2001:db8:b:2::5"
    await monitor.check_once()

    events = await store.events_since(IPV6_EVENT_KINDS, EPOCH)
    assert [event["kind"] for event in events] == ["ipv6_prefix_changed"]
    assert events[0]["details"] == {"from": "2001:db8:a:1::/64", "to": "2001:db8:b:2::/64"}
    report = summary(monitor, events)
    assert report["public_prefix"] == "2001:db8:b:2::/64"
    assert report["prefix_changes"][0]["to"] == "2001:db8:b:2::/64"
    await monitor.close()


@pytest.mark.asyncio
async def test_open_outage_survives_a_restart(tmp_path) -> None:
    network = Network()
    monitor, store, _ = await make_monitor(tmp_path, network)
    await monitor.check_once()
    network.up = False
    await monitor.check_once()
    await monitor.close()

    network.up = True
    restarted, _, _ = await make_monitor(tmp_path, network)
    await restarted.check_once()

    assert await kinds(store) == ["ipv6_lost", "ipv6_restored"]
    await restarted.close()


def test_container_ipv6_addresses_skips_loopback_and_link_local(tmp_path) -> None:
    path = tmp_path / "if_inet6"
    path.write_text(
        "00000000000000000000000000000001 01 80 10 80       lo\n"
        "fe800000000000000042acfffe120002 1b 40 20 80     eth0\n"
        "fd000db8000000000000000000000002 1b 40 00 00     eth0\n",
        encoding="ascii",
    )

    assert container_ipv6_addresses(str(path)) == ["fd00:db8::2"]
    assert container_ipv6_addresses(str(tmp_path / "missing")) == []
