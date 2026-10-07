import httpx
import pytest

from tmhi_control_center.gateway import GatewayAuthenticationError, UnifiedGatewayClient


@pytest.mark.asyncio
async def test_authenticate_and_reboot() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "abc123"}})
        if request.url.path.endswith("/gateway/reset"):
            assert request.headers["Authorization"] == "Bearer abc123"
            assert request.url.params["set"] == "reboot"
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"device": {"model": "TMOG4AR"}})

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.reboot()
        assert result.accepted is True
        assert result.uncertain is False
        assert len(requests) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_reboot_g5ar_on_http_port_80_fallback() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.port == 8080:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "g5ar-token"}})
        if request.url.path.endswith("/gateway/reset"):
            assert request.headers["Authorization"] == "Bearer g5ar-token"
            assert request.url.params["set"] == "reboot"
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.reboot()
    finally:
        await client.close()

    assert result.accepted is True
    assert result.uncertain is False
    successful_paths = [
        request.url.path for request in requests if request.url.port != 8080
    ]
    assert successful_paths == [
        "/TMI/v1/auth/login",
        "/TMI/v1/gateway/reset",
    ]


@pytest.mark.asyncio
async def test_missing_token_is_auth_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"message": "Bad credentials"}})

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "wrong",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(GatewayAuthenticationError, match="Bad credentials"):
            await client.authenticate()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_detect_unified_gateway_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/TMI/v1/gateway/")
        return httpx.Response(
            200,
            json={
                "device": {
                    "manufacturer": "Arcadyan",
                    "model": "TMOG4AR",
                    "friendlyName": "T-Mobile Gateway",
                }
            },
        )

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is True
    assert detection.api_type == "unified"
    assert detection.model == "TMOG4AR"
    assert detection.manufacturer == "Arcadyan"


@pytest.mark.asyncio
async def test_gateway_overview_normalizes_signal_and_redacts_private_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(401, json={"result": {"message": "login unavailable"}})
        assert request.url.path.endswith("/TMI/v1/gateway/")
        return httpx.Response(
            200,
            json={
                "device": {
                    "manufacturer": "Arcadyan",
                    "model": "TMOG4AR",
                    "friendlyName": "T-Mobile Gateway",
                    "serialNumber": "SN123456",
                    "firmwareVersion": "1.2.3",
                },
                "connection": {
                    "connectionStatus": "Connected",
                    "networkType": "5G",
                    "band": "n41",
                    "pci": 123,
                    "cellId": "cell-abc",
                    "wanIp": "100.64.1.8",
                },
                "signal": {
                    "rsrp": "-86 dBm",
                    "rsrq": -9,
                    "sinr": "19 dB",
                    "rssi": -68,
                },
                "wifi": {
                    "ssid": "KevinNet",
                    "wifiPassword": "super-secret",
                    "connectedClients": 8,
                },
            },
        )

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        overview = await client.overview()
    finally:
        await client.close()

    assert overview["detection"]["reachable"] is True
    assert overview["device"]["model"] == "TMOG4AR"
    assert overview["device"]["firmware"] == "1.2.3"
    assert overview["connection"]["network_type"] == "5G"
    assert overview["connection"]["band"] == "n41"
    assert overview["wifi"]["ssid"] == "KevinNet"
    assert overview["wifi"]["clients"] == "8"
    assert overview["signal"]["quality"] in {"Good", "Excellent"}
    assert overview["signal"]["score"] >= 70
    assert {metric["key"] for metric in overview["signal"]["metrics"]} >= {
        "rsrp",
        "rsrq",
        "sinr",
    }
    rendered = str(overview)
    assert "super-secret" not in rendered
    assert "SN123456" not in rendered
    assert "[redacted]" in rendered


@pytest.mark.asyncio
async def test_gateway_overview_enriches_lte_nr_cell_and_system_telemetry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gateway/"):
            return httpx.Response(
                200,
                json={
                    "device": {
                        "manufacturer": "Arcadyan",
                        "model": "TMOG4AR",
                        "isEnabled": True,
                        "isMeshSupported": True,
                        "updateState": "idle",
                        "deviceTemperature": 42.5,
                    },
                    "signal": {
                        "4g": {
                            "bands": ["B66"],
                            "bars": 4,
                            "rsrp": -91,
                            "rsrq": -11,
                            "sinr": 15,
                            "rssi": -71,
                            "cid": 1001,
                            "eNBID": 2002,
                            "antennaUsed": "External",
                        },
                        "5g": {
                            "bands": ["n41"],
                            "bars": 5,
                            "rsrp": -82,
                            "rsrq": -9,
                            "sinr": 22,
                            "rssi": -64,
                            "cid": 3003,
                            "gNBID": 4004,
                            "antennaUsed": "External",
                        },
                        "generic": {
                            "registration": "registered",
                            "roaming": False,
                            "hasIPv6": True,
                        },
                    },
                    "time": {"upTime": 183845, "localTimeZone": "America/Los_Angeles"},
                },
            )
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "cell-token"}})
        if request.url.path.endswith("/network/telemetry/"):
            assert request.url.params["get"] == "cell"
            assert request.headers["Authorization"] == "Bearer cell-token"
            return httpx.Response(
                200,
                json={
                    "cell": {
                        "4g": {
                            "status": True,
                            "bandwidth": "20 MHz",
                            "cqi": 11,
                            "earfcn": "66786",
                            "pci": "123",
                            "tac": "456",
                            "mcc": "310",
                            "mnc": "260",
                        },
                        "5g": {
                            "status": True,
                            "bandwidth": "100 MHz",
                            "cqi": 14,
                            "earfcn": "520110",
                            "pci": "321",
                            "tac": "654",
                            "mcc": "310",
                            "mnc": "260",
                        },
                    }
                },
            )
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        overview = await client.overview()
    finally:
        await client.close()

    radios = {radio["key"]: radio for radio in overview["radios"]}
    assert set(radios) == {"lte", "nr"}
    assert radios["lte"]["antenna"] == "External"
    assert radios["lte"]["cell"]["bandwidth"] == "20 MHz"
    assert radios["lte"]["cell"]["arfcn"] == "66786"
    assert radios["nr"]["cell"]["band"] == "n41"
    assert radios["nr"]["cell"]["pci"] == "321"
    assert {metric["key"] for metric in radios["nr"]["metrics"]} >= {
        "rsrp",
        "rsrq",
        "sinr",
        "rssi",
        "cqi",
    }
    assert overview["connection"]["mode"] == "LTE + 5G NR"
    assert overview["system"]["temperature"]["celsius"] == 42.5
    assert overview["system"]["uptime"] == "2d 3h 4m"
    assert overview["system"]["mesh_supported"] is True
    assert overview["telemetry"]["advanced_cell_available"] is True


@pytest.mark.asyncio
async def test_connected_devices_extracts_and_identifies_clients() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "abc123"}})
        if request.url.path.endswith("/network/telemetry/"):
            assert request.url.params["get"] == "clients"
            assert request.headers["Authorization"] == "Bearer abc123"
            return httpx.Response(
                200,
                json={
                    "clients": [
                        {
                            "macAddress": "AA:BB:CC:11:22:33",
                            "ipAddress": "192.168.12.44",
                            "hostName": "Kevin-iPhone-16-Pro",
                            "vendor": "Apple",
                            "connectionType": "wifi",
                            "ssid": "KevinNet",
                        },
                        {
                            "macAddress": "11:22:33:44:55:66",
                            "ipAddress": "192.168.12.45",
                            "hostName": "Living-Room-Roku",
                        },
                    ]
                },
            )
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        clients = await client.connected_devices()
    finally:
        await client.close()

    assert clients["count"] == 2
    iphone = clients["devices"][0]
    assert iphone["mac_address"] == "AA:BB:CC:xx:xx:xx"
    assert iphone["mac_oui"] == "AA:BB:CC"
    assert iphone["vendor"] == "Apple"
    assert iphone["identification"]["name"] == "Apple iPhone 16 Pro"
    assert iphone["identification"]["method"] == "hostname_pattern"
    rendered = str(clients)
    assert "AA:BB:CC:11:22:33" not in rendered


@pytest.mark.asyncio
async def test_wifi_config_and_update_ssid_and_radios() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "abc123"}})
        if request.url.path.endswith("/network/configuration/v2"):
            assert request.headers["Authorization"] == "Bearer abc123"
            if request.url.params.get("get") == "ap":
                return httpx.Response(
                    200,
                    json={
                        "ap": [
                            {
                                "band": "2.4GHz",
                                "isRadioEnabled": True,
                                "isBroadcastEnabled": True,
                                "ssid": "OldNet",
                                "password": "hide-me",
                            },
                            {
                                "band": "5GHz",
                                "isRadioEnabled": True,
                                "isBroadcastEnabled": True,
                                "ssid": "OldNet",
                            },
                        ]
                    },
                )
            if request.url.params.get("set") == "ap":
                payload = request.read().decode("utf-8")
                assert "NewNet" in payload
                assert "false" in payload
                return httpx.Response(200, json={"result": "ok"})
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        config = await client.wifi_config()
        result = await client.update_wifi(ssid="NewNet", radio_enabled=False)
    finally:
        await client.close()

    assert config["ssid"] == "OldNet"
    assert config["radio_enabled"] is True
    assert "hide-me" not in str(config)
    assert result["accepted"] is True
    assert result["changed"] == {
        "ssid_fields": 2,
        "radio_enabled_fields": 2,
        "ssid_enabled_fields": 0,
        "broadcast_enabled_fields": 2,
        "radio_enabled": False,
    }
    assert any(request.url.params.get("set") == "ap" for request in requests)


@pytest.mark.asyncio
async def test_hintcontrol_wifi_shape_updates_ssids_and_band_radios() -> None:
    posted_payloads: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "abc123"}})
        if request.url.path.endswith("/network/configuration/v2"):
            if request.url.params.get("get") == "ap":
                return httpx.Response(
                    200,
                    json={
                        "2.4ghz": {"isRadioEnabled": True, "channel": "Auto"},
                        "5.0ghz": {"isRadioEnabled": True, "channel": "Auto"},
                        "bandSteering": {"isEnabled": True},
                        "ssids": [
                            {
                                "2.4ghzSsid": True,
                                "5.0ghzSsid": True,
                                "encryptionMode": "AES",
                                "encryptionVersion": "WPA2/WPA3",
                                "guest": False,
                                "isBroadcastEnabled": True,
                                "ssidName": "OldNet",
                                "wpaKey": "hide-me-too",
                                "enabled": True,
                            }
                        ],
                    },
                )
            if request.url.params.get("set") == "ap":
                posted_payloads.append(request.read().decode("utf-8"))
                return httpx.Response(200, json={})
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        config = await client.wifi_config()
        result = await client.update_wifi(ssid="NewNet", radio_enabled=False)
    finally:
        await client.close()

    assert config["ssid"] == "OldNet"
    assert config["radio_enabled"] is True
    assert config["broadcast_enabled"] is True
    assert config["radios"][0]["band"] == "2.4 GHz"
    assert config["ssids"][0]["bands"] == ["2.4 GHz", "5 GHz"]
    assert "hide-me-too" not in str(config)
    assert result["changed"] == {
        "ssid_fields": 1,
        "radio_enabled_fields": 2,
        "ssid_enabled_fields": 1,
        "broadcast_enabled_fields": 1,
        "radio_enabled": False,
    }
    assert posted_payloads
    assert '"ssidName":"NewNet"' in posted_payloads[0]
    assert '"isRadioEnabled":false' in posted_payloads[0]
    assert '"isBroadcastEnabled":false' in posted_payloads[0]
    assert '"enabled":false' in posted_payloads[0]


@pytest.mark.asyncio
async def test_detect_g5ar_on_http_port_80_gateway_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8080:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path.endswith("/TMI/v1/gateway/"):
            return httpx.Response(404)
        if request.url.path.endswith("/TMI/v1/gateway"):
            assert request.url.params["get"] == "all"
            return httpx.Response(
                200,
                json={
                    "device": {
                        "manufacturer": "Arcadyan",
                        "model": "TMO-G5AR",
                        "name": "T-Mobile 5G Gateway",
                    }
                },
            )
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is True
    assert detection.api_type == "unified"
    assert detection.model == "TMO-G5AR"
    assert detection.manufacturer == "Arcadyan"


@pytest.mark.asyncio
async def test_detect_nokia_gateway_as_unsupported() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/TMI/v1/gateway/", "/TMI/v1/gateway")):
            return httpx.Response(404)
        if request.url.path.endswith("/dashboard_device_status_web_app.cgi"):
            return httpx.Response(200, json={"num_extenders": 0})
        if request.url.path.endswith("/dashboard_device_info_status_web_app.cgi"):
            return httpx.Response(
                200,
                json={
                    "device_app_status": [
                        {
                            "ManufacturerOUI": "Nokia",
                            "ProductClass": "5G21",
                            "Description": "Nokia FastMile",
                        }
                    ]
                },
            )
        return httpx.Response(500)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is False
    assert detection.api_type == "nokia"
    assert detection.model == "5G21"


G5AR_ALL = {
    "device": {
        "hardwareVersion": "R01",
        "macId": "18:60:41:00:00:05",
        "manufacturer": "Arcadyan",
        "model": "TMO-G5AR",
        "serial": "XX00Z1E82",
        "softwareVersion": "1.00.06",
    },
    "signal": {
        "4g": {"bands": ["b2"], "cid": 12, "eNBID": 20001, "rsrp": -75, "sinr": 33},
        "5g": {"bands": ["n41"], "cid": 12, "gNBID": 20001, "rsrp": -66, "sinr": 28},
        "generic": {"apn": "FBB.HOME", "hasIPv6": True, "registration": "registered"},
    },
    "time": {"localTime": 1791303219, "localTimeZone": "-06:00", "upTime": 267336},
}


@pytest.mark.asyncio
async def test_non_standalone_5g_identity_is_flagged_as_the_lte_anchor() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gateway/"):
            return httpx.Response(200, json=G5AR_ALL)
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "",
        transport=httpx.MockTransport(handler),
    )
    try:
        overview = await client.overview()
        signal = await client.signal_snapshot()
    finally:
        await client.close()

    radios = {radio["key"]: radio for radio in overview["radios"]}
    assert radios["nr"]["cell"]["anchor_reported"] is True
    assert radios["nr"]["cell"]["node_label"] == "Anchor eNBID"
    assert "anchor" in radios["nr"]["note"]
    assert "anchor_reported" not in radios["lte"]["cell"]
    assert overview["connection"]["architecture"] == "LTE + 5G (non-standalone)"
    assert signal["registration"] == "registered"


@pytest.mark.asyncio
async def test_device_details_masks_sim_and_serial_identifiers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/gateway/"):
            return httpx.Response(200, json=G5AR_ALL)
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "sim-token"}})
        if path.endswith("/network/telemetry/") and request.url.params["get"] == "sim":
            assert request.headers["Authorization"] == "Bearer sim-token"
            return httpx.Response(
                200,
                json={
                    "sim": {
                        "iccId": "8901260123456789012",
                        "imei": "351234567890154",
                        "imsi": "310260123456758",
                        "msisdn": "13035550185",
                        "status": True,
                    }
                },
            )
        if path.endswith("/version"):
            return httpx.Response(200, json={"version": 3.1})
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        details = await client.device_details()
    finally:
        await client.close()

    assert details["device"]["firmware"] == "1.00.06"
    assert details["device"]["serial"] == "•••• 1E82"
    assert details["device"]["api_version"] == "3.1"
    assert details["sim"] == {
        "status": "Active",
        "iccid": "•••• 9012",
        "imei": "•••• 0154",
        "imsi": "•••• 6758",
        "phone_number": "•••• 0185",
    }
    serialized = str(details)
    for secret in ("8901260123456789012", "351234567890154", "13035550185", "XX00Z1E82"):
        assert secret not in serialized
    assert details["network"] == {"apn": "FBB.HOME", "registration": "registered", "ipv6": True}
    assert details["clock"]["timezone"] == "-06:00"
