from __future__ import annotations

import logging
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import GatewayDetection, RebootResult, utc_now


logger = logging.getLogger(__name__)

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passphrase",
    "wpakey",
    "presharedkey",
    "psk",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "auth",
    "imei",
    "imsi",
    "iccid",
    "msisdn",
    "serial",
    "mac",
    "bssid",
    "private",
    "pin",
    "puk",
)

SIGNAL_METRICS: tuple[dict[str, Any], ...] = (
    {
        "key": "rsrp",
        "label": "RSRP",
        "unit": "dBm",
        "kind": "rsrp",
        "candidates": ("rsrp", "nr_rsrp", "lte_rsrp", "5g_rsrp"),
    },
    {
        "key": "rsrq",
        "label": "RSRQ",
        "unit": "dB",
        "kind": "rsrq",
        "candidates": ("rsrq", "nr_rsrq", "lte_rsrq", "5g_rsrq"),
    },
    {
        "key": "sinr",
        "label": "SINR",
        "unit": "dB",
        "kind": "sinr",
        "candidates": ("sinr", "snr", "nr_sinr", "lte_sinr", "5g_sinr"),
    },
    {
        "key": "rssi",
        "label": "RSSI",
        "unit": "dBm",
        "kind": "rssi",
        "candidates": ("rssi", "nr_rssi", "lte_rssi", "5g_rssi"),
    },
    {
        "key": "bars",
        "label": "Bars",
        "unit": "",
        "kind": "bars",
        "candidates": ("bars", "signalbars", "signal_bar", "signal_strength"),
    },
)

DEVICE_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("manufacturer", "Manufacturer", ("manufacturer", "vendor", "brand")),
    ("model", "Model", ("model", "productclass", "product_class", "sku")),
    ("name", "Name", ("friendlyname", "friendly_name", "devicename", "name")),
    ("firmware", "Firmware", ("firmware", "firmwareversion", "softwareversion")),
    ("hardware", "Hardware", ("hardware", "hardwareversion", "hwversion")),
)

CONNECTION_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("state", "Connection", ("connectionstatus", "connection_status", "wanstatus", "state")),
    ("network_type", "Network", ("networktype", "network_type", "rat", "access_technology")),
    (
        "mode",
        "Radio mode",
        ("currentaccesstechnology", "current_access_technology", "radiomode", "networkmode"),
    ),
    ("registration", "Registration", ("registration", "registrationstatus")),
    ("roaming", "Roaming", ("roaming", "roamingstatus")),
    ("operator", "Operator", ("operator", "carrier", "plmnname", "plmn_name")),
    ("plmn", "PLMN", ("plmn", "plmnid", "operatorcode")),
    ("mcc", "MCC", ("mcc", "mobilecountrycode")),
    ("mnc", "MNC", ("mnc", "mobilenetworkcode")),
    ("band", "Band", ("primaryband", "primary_band", "nrband", "lteband", "band")),
    ("pci", "PCI", ("pci", "physicalcellid", "physical_cell_id")),
    ("tac", "TAC", ("tac", "trackingareacode", "trackingarea")),
    ("lac", "LAC", ("lac", "localareacode")),
    ("cell_id", "Cell ID", ("nci", "nrcellid", "cellid", "cell_id", "enbid", "gnbid")),
    ("earfcn", "EARFCN", ("earfcn", "lteearfcn", "lte_earfcn")),
    ("nr_arfcn", "NR-ARFCN", ("nrarfcn", "nr_arfcn", "nrArfcn")),
    ("apn", "APN", ("apn",)),
    ("wan_ipv4", "WAN IPv4", ("wanip", "wan_ip", "ipv4address", "ipv4_address")),
    ("wan_ipv6", "WAN IPv6", ("ipv6address", "ipv6_address", "wanipv6", "wan_ipv6")),
    ("uptime", "Uptime", ("uptime", "up_time", "systemuptime", "system_uptime")),
)

WIFI_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ssid", "SSID", ("ssid", "primaryssid", "primary_ssid")),
    ("ssid_2g", "2.4 GHz SSID", ("ssid2g", "ssid_2g", "2gssid", "2_4ghzssid")),
    ("ssid_5g", "5 GHz SSID", ("ssid5g", "ssid_5g", "5gssid", "5ghzssid")),
    ("channel_2g", "2.4 GHz channel", ("channel2g", "channel_2g", "2gchannel")),
    ("channel_5g", "5 GHz channel", ("channel5g", "channel_5g", "5gchannel")),
    ("clients", "Connected clients", ("clients", "connectedclients", "connected_devices")),
)

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
MAC_PATTERN = re.compile(
    r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|[0-9a-f]{12}"
)

CLIENT_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "mac_address": (
        "mac",
        "macaddress",
        "macaddr",
        "clientmac",
        "hwaddr",
        "physicaladdress",
    ),
    "ip_address": (
        "ip",
        "ipaddress",
        "ipv4",
        "ipv4address",
        "clientip",
        "hostip",
    ),
    "hostname": (
        "hostname",
        "host",
        "host_name",
        "name",
        "clientname",
        "devicename",
        "friendlyname",
    ),
    "interface": ("interface", "connectiontype", "medium", "type", "ifname"),
    "ssid": ("ssid", "networkname", "apname"),
    "band": ("band", "radio", "frequency", "freq"),
    "rssi": ("rssi", "signal", "signalstrength"),
    "vendor": ("vendor", "manufacturer", "maker", "brand"),
    "model": ("model", "modelname", "devicemodel", "product", "productname"),
    "os": ("os", "operatingsystem", "platform"),
}

WIFI_RADIO_CANDIDATES = (
    "isradioenabled",
    "radioenabled",
    "radioenable",
    "wifienabled",
    "wirelessenabled",
    "enabled",
)

WIFI_BROADCAST_CANDIDATES = (
    "isbroadcastenabled",
    "broadcastenabled",
    "ssidbroadcast",
    "broadcastssid",
)

WIFI_SSID_CANDIDATES = ("ssid", "ssidname", "networkname", "apname")


class GatewayError(RuntimeError):
    """Base gateway communication error."""


class GatewayAuthenticationError(GatewayError):
    """Gateway rejected credentials or did not return a token."""


class GatewayUnavailableError(GatewayError):
    """Gateway local API could not be reached."""


class UnifiedGatewayClient:
    """Client for Arcadyan/Sagemcom/Sercomm gateways using the TMI v1 API."""

    AUTH_PATH = "/auth/login"
    INFO_PATHS = ("/gateway/?get=all", "/gateway?get=all")
    REBOOT_PATH = "/gateway/reset?set=reboot"
    CLIENT_PATHS = (
        "/network/telemetry/?get=clients",
        "/network/telemetry?get=clients",
        "/network/telemetry/?get=all",
        "/network/telemetry?get=all",
    )
    CELL_PATHS = (
        "/network/telemetry/?get=cell",
        "/network/telemetry?get=cell",
    )
    WIFI_CONFIG_PATHS = (
        "/network/configuration/v2?get=ap",
        "/network/configuration?get=ap",
    )
    WIFI_SET_PATHS = {
        "/network/configuration/v2?get=ap": "/network/configuration/v2?set=ap",
        "/network/configuration?get=ap": "/network/configuration?set=ap",
    }
    NOKIA_STATUS_PATH = "/dashboard_device_status_web_app.cgi"
    NOKIA_INFO_PATH = "/dashboard_device_info_status_web_app.cgi"

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 15.0,
        user_agent: str = "homeisp/android/2.12.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._tmi_base_urls = _candidate_tmi_base_urls(self.base_url)
        self._active_tmi_base_url = self._tmi_base_urls[0]
        self.username = username
        self._password = password
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def set_password(self, password: str) -> None:
        self._password = password

    async def detect(self) -> GatewayDetection:
        unified = await self._detect_unified()
        if unified.reachable:
            return unified

        nokia = await self._detect_nokia()
        if nokia.reachable:
            return nokia

        return GatewayDetection(
            reachable=False,
            error=unified.error or nokia.error or "Gateway was not detected",
        )

    async def is_reachable(self) -> bool:
        """Use broad unified-gateway detection for local reachability checks."""
        detection = await self._detect_unified()
        return detection.reachable

    async def overview(self) -> dict[str, Any]:
        detection, payload = await self._fetch_unified_info()
        if payload is not None:
            cell_source: str | None = None
            cell_payload: dict[str, Any] | None = None
            try:
                token = await self.authenticate()
                cell_source, cell_payload = await self._fetch_authenticated_json(
                    token,
                    self.CELL_PATHS,
                    label="Cell telemetry",
                )
            except GatewayError as exc:
                logger.debug("Advanced cell telemetry is unavailable: %s", exc)
            return _build_unified_overview(
                detection,
                payload,
                cell_payload=cell_payload,
                cell_source=cell_source,
            )

        if not detection.reachable:
            nokia = await self._detect_nokia()
            if nokia.reachable:
                detection = nokia

        return _empty_overview(detection)

    async def gps_location(self) -> dict[str, Any] | None:
        """Latitude and longitude exactly as the gateway reports them.

        Read from the raw telemetry rather than the assembled overview. That
        rendering formats every float to a single decimal place, which suits
        signal metrics but collapses a coordinate onto a roughly ten-kilometre
        grid -- useless as a map centre.

        Returns None when the gateway exposes no GPS block, which is the case on
        some models.
        """
        token = await self.authenticate()
        _source, payload = await self._fetch_authenticated_json(
            token,
            self.CELL_PATHS,
            label="Cell telemetry",
        )
        cell = _mapping_child(payload, ("cell",)) or payload
        gps = _mapping_child(cell, ("gps", "location"))
        latitude = _number_or_none(
            _find_mapping_value(gps, ("latitude", "lat"), exact=True)
        )
        longitude = _number_or_none(
            _find_mapping_value(gps, ("longitude", "lon", "lng"), exact=True)
        )
        if latitude is None or longitude is None:
            return None
        return {"latitude": float(latitude), "longitude": float(longitude)}

    async def connected_devices(
        self,
        *,
        online_vendor_lookup: bool = False,
    ) -> dict[str, Any]:
        token = await self.authenticate()
        errors: list[str] = []
        for base_url in self._ordered_tmi_base_urls():
            for path in self.CLIENT_PATHS:
                try:
                    response = await self._client.get(
                        _endpoint_url(base_url, path),
                        headers=_auth_headers(token),
                    )
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{base_url}{path}: {type(exc).__name__}: {exc}")
                    continue

                if not response.is_success:
                    errors.append(
                        f"{base_url}{path}: clients API returned HTTP {response.status_code}"
                    )
                    continue

                try:
                    payload = response.json()
                except ValueError:
                    errors.append(f"{base_url}{path}: clients API returned invalid JSON")
                    continue

                self._active_tmi_base_url = base_url
                devices = _connected_devices_from_payload(payload)
                if online_vendor_lookup:
                    await self._apply_online_vendor_lookup(devices)
                return {
                    "observed_at": utc_now().isoformat(),
                    "supported": True,
                    "source": path,
                    "count": len(devices),
                    "online_vendor_lookup": online_vendor_lookup,
                    "devices": devices,
                }

        raise GatewayUnavailableError(
            _summarize_errors(errors, "Connected-device telemetry was not reachable")
        )

    async def wifi_config(self) -> dict[str, Any]:
        token = await self.authenticate()
        _base_url, path, payload = await self._fetch_wifi_config_payload(token)
        return _build_wifi_config(payload, source=path)

    async def update_wifi(
        self,
        *,
        ssid: str | None = None,
        radio_enabled: bool | None = None,
    ) -> dict[str, Any]:
        if ssid is None and radio_enabled is None:
            raise GatewayError("No Wi-Fi changes were requested")

        token = await self.authenticate()
        base_url, get_path, payload = await self._fetch_wifi_config_payload(token)
        updated_payload = deepcopy(payload)

        changes: dict[str, Any] = {}
        if ssid is not None:
            ssid_count = _set_wifi_ssid(updated_payload, ssid)
            if ssid_count == 0:
                raise GatewayError("No writable SSID fields were found in the gateway config")
            changes["ssid_fields"] = ssid_count

        if radio_enabled is not None:
            radio_count = _set_wifi_radio_enabled(updated_payload, radio_enabled)
            ssid_enabled_count = _set_wifi_ssid_enabled(updated_payload, radio_enabled)
            broadcast_count = _set_wifi_broadcast_enabled(updated_payload, radio_enabled)
            if radio_count + ssid_enabled_count + broadcast_count == 0:
                raise GatewayError(
                    "No writable Wi-Fi radio enable fields were found in the gateway config"
                )
            changes["radio_enabled_fields"] = radio_count
            changes["ssid_enabled_fields"] = ssid_enabled_count
            changes["broadcast_enabled_fields"] = broadcast_count
            changes["radio_enabled"] = radio_enabled

        set_path = self.WIFI_SET_PATHS.get(get_path, get_path.replace("get=ap", "set=ap"))
        try:
            response = await self._client.post(
                _endpoint_url(base_url, set_path),
                json=updated_payload,
                headers={
                    **_auth_headers(token),
                    "Content-Type": "application/json",
                },
            )
        except (httpx.HTTPError, OSError) as exc:
            raise GatewayUnavailableError(
                f"Could not send Wi-Fi settings to the gateway: {type(exc).__name__}: {exc}"
            ) from exc

        if not response.is_success:
            raise GatewayError(
                f"Gateway rejected Wi-Fi settings with HTTP {response.status_code}"
            )

        return {
            "accepted": True,
            "message": f"Gateway accepted Wi-Fi settings (HTTP {response.status_code})",
            "source": set_path,
            "changed": changes,
            "wifi": _build_wifi_config(updated_payload, source=get_path),
        }

    async def _detect_unified(self) -> GatewayDetection:
        detection, _payload = await self._fetch_unified_info()
        return detection

    async def _fetch_unified_info(self) -> tuple[GatewayDetection, dict[str, Any] | None]:
        errors: list[str] = []
        reachable_error: str | None = None
        for base_url in self._ordered_tmi_base_urls():
            for info_path in self.INFO_PATHS:
                try:
                    response = await self._client.get(_endpoint_url(base_url, info_path))
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
                    continue

                if not response.is_success:
                    error = (
                        f"{base_url}{info_path}: unified API returned HTTP "
                        f"{response.status_code}"
                    )
                    errors.append(error)
                    if response.status_code not in {403, 404} and reachable_error is None:
                        reachable_error = error
                    continue

                self._active_tmi_base_url = base_url
                try:
                    payload = response.json()
                except ValueError:
                    error = f"{base_url}{info_path}: unified API returned invalid JSON"
                    errors.append(error)
                    reachable_error = reachable_error or error
                    continue

                if not isinstance(payload, dict):
                    error = f"{base_url}{info_path}: unified API returned non-object JSON"
                    errors.append(error)
                    reachable_error = reachable_error or error
                    continue

                device = payload.get("device")
                device_info = device if isinstance(device, dict) else {}
                return (
                    GatewayDetection(
                        reachable=True,
                        api_type="unified",
                        supported=True,
                        model=_string_or_none(device_info.get("model")),
                        manufacturer=_string_or_none(device_info.get("manufacturer")),
                        name=_string_or_none(
                            device_info.get("friendlyName") or device_info.get("name")
                        ),
                        error=None,
                    ),
                    payload,
                )

        if reachable_error:
            return (
                GatewayDetection(
                    reachable=True,
                    api_type="unified",
                    supported=True,
                    error=reachable_error,
                ),
                None,
            )

        return (
            GatewayDetection(
                reachable=False,
                api_type="unified",
                supported=True,
                error=_summarize_errors(errors, "Unified API was not reachable"),
            ),
            None,
        )

    async def _detect_nokia(self) -> GatewayDetection:
        try:
            response = await self._client.get(self._gateway_root_url() + self.NOKIA_STATUS_PATH)
        except (httpx.HTTPError, OSError) as exc:
            return GatewayDetection(
                reachable=False,
                api_type="nokia",
                supported=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not response.is_success:
            return GatewayDetection(
                reachable=False,
                api_type="nokia",
                supported=False,
                error=f"Nokia API returned HTTP {response.status_code}",
            )

        model = "Nokia 5G21"
        manufacturer = "Nokia"
        name = None
        try:
            info_response = await self._client.get(self._gateway_root_url() + self.NOKIA_INFO_PATH)
            app_status = _extract_first_mapping(info_response, "device_app_status")
            model = _string_or_none(app_status.get("ProductClass")) or model
            manufacturer = _string_or_none(app_status.get("ManufacturerOUI")) or manufacturer
            name = _string_or_none(app_status.get("Description"))
        except (httpx.HTTPError, OSError):
            pass

        return GatewayDetection(
            reachable=True,
            api_type="nokia",
            supported=False,
            model=model,
            manufacturer=manufacturer,
            name=name,
            error="Nokia gateway detected; reboot support is not implemented",
        )

    def _gateway_root_url(self) -> str:
        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.hostname:
            return self.base_url.split("/TMI/v1", 1)[0].rstrip("/")
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}"

    async def authenticate(self) -> str:
        if not self._password:
            raise GatewayAuthenticationError("Gateway password is not configured")

        errors: list[str] = []
        auth_problem = False
        for base_url in self._ordered_tmi_base_urls():
            try:
                response = await self._client.post(
                    _endpoint_url(base_url, self.AUTH_PATH),
                    json={"username": self.username, "password": self._password},
                    headers={"Content-Type": "application/json"},
                )
            except (httpx.HTTPError, OSError) as exc:
                errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
                continue

            if not response.is_success:
                auth_problem = True
                errors.append(f"{base_url}: login returned HTTP {response.status_code}")
                continue

            try:
                payload: dict[str, Any] = response.json()
            except ValueError:
                auth_problem = True
                errors.append(f"{base_url}: login response was not valid JSON")
                continue

            auth = payload.get("auth")
            token = auth.get("token") if isinstance(auth, dict) else None
            if isinstance(token, str) and token:
                self._active_tmi_base_url = base_url
                return token

            result = payload.get("result")
            message = result.get("message") if isinstance(result, dict) else None
            safe_message = message if isinstance(message, str) else "No token returned"
            auth_problem = True
            errors.append(f"{base_url}: {safe_message}")

        if errors:
            message = _summarize_errors(errors, "Gateway login failed")
            if auth_problem:
                raise GatewayAuthenticationError(message)
            raise GatewayUnavailableError(
                f"Could not reach the gateway login API: {message}"
            )

        raise GatewayUnavailableError("Could not reach the gateway login API")

    async def reboot(self) -> RebootResult:
        token = await self.authenticate()
        try:
            response = await self._client.post(
                _endpoint_url(self._active_tmi_base_url, self.REBOOT_PATH),
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.is_success:
                return RebootResult(
                    accepted=True,
                    message=f"Gateway accepted reboot request (HTTP {response.status_code})",
                )
            raise GatewayError(f"Gateway reboot failed with HTTP {response.status_code}")
        except (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # Some firmware drops the HTTP connection immediately while rebooting.
            logger.warning(
                "Gateway connection ended during reboot request; treating as uncertain acceptance: %s",
                type(exc).__name__,
            )
            return RebootResult(
                accepted=True,
                uncertain=True,
                message=(
                    "Gateway disconnected during the reboot request. The command may have "
                    "been accepted, so the watchdog entered reboot grace to avoid a loop."
                ),
            )
        except (httpx.ConnectError, OSError) as exc:
            raise GatewayUnavailableError(
                f"Could not connect to the gateway reboot API: {type(exc).__name__}"
            ) from exc

    def _ordered_tmi_base_urls(self) -> tuple[str, ...]:
        return (
            self._active_tmi_base_url,
            *(url for url in self._tmi_base_urls if url != self._active_tmi_base_url),
        )

    async def _fetch_wifi_config_payload(
        self,
        token: str,
    ) -> tuple[str, str, dict[str, Any] | list[Any]]:
        errors: list[str] = []
        for base_url in self._ordered_tmi_base_urls():
            for path in self.WIFI_CONFIG_PATHS:
                try:
                    response = await self._client.get(
                        _endpoint_url(base_url, path),
                        headers=_auth_headers(token),
                    )
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{base_url}{path}: {type(exc).__name__}: {exc}")
                    continue

                if not response.is_success:
                    errors.append(
                        f"{base_url}{path}: Wi-Fi config API returned HTTP {response.status_code}"
                    )
                    continue

                try:
                    payload = response.json()
                except ValueError:
                    errors.append(f"{base_url}{path}: Wi-Fi config API returned invalid JSON")
                    continue

                if not isinstance(payload, (dict, list)):
                    errors.append(f"{base_url}{path}: Wi-Fi config API returned non-object JSON")
                    continue

                self._active_tmi_base_url = base_url
                return base_url, path, payload

        raise GatewayUnavailableError(
            _summarize_errors(errors, "Wi-Fi configuration was not reachable")
        )

    async def _fetch_authenticated_json(
        self,
        token: str,
        paths: tuple[str, ...],
        *,
        label: str,
    ) -> tuple[str, dict[str, Any]]:
        errors: list[str] = []
        for base_url in self._ordered_tmi_base_urls():
            for path in paths:
                try:
                    response = await self._client.get(
                        _endpoint_url(base_url, path),
                        headers=_auth_headers(token),
                    )
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{base_url}{path}: {type(exc).__name__}: {exc}")
                    continue

                if not response.is_success:
                    errors.append(
                        f"{base_url}{path}: {label} API returned HTTP {response.status_code}"
                    )
                    continue

                try:
                    payload = response.json()
                except ValueError:
                    errors.append(f"{base_url}{path}: {label} API returned invalid JSON")
                    continue

                if not isinstance(payload, dict):
                    errors.append(f"{base_url}{path}: {label} API returned non-object JSON")
                    continue

                self._active_tmi_base_url = base_url
                return path, payload

        raise GatewayUnavailableError(
            _summarize_errors(errors, f"{label} was not reachable")
        )

    async def _apply_online_vendor_lookup(self, devices: list[dict[str, Any]]) -> None:
        vendors_by_oui: dict[str, str | None] = {}
        for device in devices:
            if device.get("vendor"):
                continue
            oui = device.get("mac_oui")
            if not isinstance(oui, str) or not oui:
                continue
            if oui not in vendors_by_oui:
                vendors_by_oui[oui] = await self._lookup_oui_vendor(oui)
            vendor = vendors_by_oui[oui]
            if vendor:
                device["vendor"] = vendor
                device["identification"] = _identify_client(device)

    async def _lookup_oui_vendor(self, oui: str) -> str | None:
        try:
            response = await self._client.get(
                f"https://api.macvendors.com/{oui.replace(':', '-')}",
                headers={"Accept": "text/plain"},
            )
        except (httpx.HTTPError, OSError):
            return None
        if response.status_code == 404 or not response.is_success:
            return None
        vendor = response.text.strip()
        return vendor or None


def _endpoint_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _empty_overview(detection: GatewayDetection) -> dict[str, Any]:
    return {
        "observed_at": utc_now().isoformat(),
        "detection": detection.to_dict(),
        "device": _device_from_detection(detection),
        "connection": {},
        "wifi": {},
        "radios": [],
        "system": {
            "temperature": None,
            "temperature_exposed": False,
        },
        "signal": {
            "score": None,
            "quality": "Unknown",
            "summary": "Gateway telemetry is not available yet",
            "metrics": [],
        },
        "sections": [],
    }


def _build_unified_overview(
    detection: GatewayDetection,
    payload: dict[str, Any],
    *,
    cell_payload: dict[str, Any] | None = None,
    cell_source: str | None = None,
) -> dict[str, Any]:
    redacted_payload = _redact_sensitive(payload)
    flattened = list(_flatten_leaves(redacted_payload))
    signal = _signal_summary(flattened)
    device = _device_summary(detection, flattened)
    connection = _field_summary(flattened, CONNECTION_FIELDS)
    wifi = _field_summary(flattened, WIFI_FIELDS)
    safe_cell_payload = _redact_sensitive(cell_payload) if cell_payload else None
    radios = _radio_summaries(redacted_payload, safe_cell_payload)
    active_radio_scores = [
        radio["score"]
        for radio in radios
        if radio.get("active") is not False and radio.get("score") is not None
    ]
    if active_radio_scores:
        signal["score"] = round(sum(active_radio_scores) / len(active_radio_scores))
        signal["quality"] = _quality_from_score(signal["score"])
        labels = ", ".join(radio["label"] for radio in radios if radio.get("active") is not False)
        signal["summary"] = f"Combined radio health across {labels}"
    signal["radio_scores"] = {
        radio["key"]: radio.get("score") for radio in radios if radio.get("score") is not None
    }
    _enrich_connection_from_radios(connection, radios)
    system = _system_summary(redacted_payload, safe_cell_payload)

    sections_payload = dict(redacted_payload)
    if safe_cell_payload:
        sections_payload["advanced_cell"] = safe_cell_payload

    return {
        "observed_at": utc_now().isoformat(),
        "detection": detection.to_dict(),
        "device": device,
        "connection": connection,
        "wifi": wifi,
        "radios": radios,
        "system": system,
        "telemetry": {
            "advanced_cell_available": bool(safe_cell_payload),
            "advanced_cell_source": cell_source,
        },
        "signal": signal,
        "sections": _sections_from_payload(sections_payload),
    }


def _radio_summaries(
    payload: dict[str, Any],
    cell_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    signal_root = _mapping_child(payload, ("signal",))
    cell_root = _mapping_child(cell_payload or {}, ("cell",)) or (cell_payload or {})
    definitions = (
        ("lte", "4G LTE", ("4g", "lte"), "EARFCN", "eNBID"),
        ("nr", "5G NR", ("5g", "nr", "nr5g"), "NR-ARFCN", "gNBID"),
    )
    radios: list[dict[str, Any]] = []
    for key, label, aliases, arfcn_label, node_label in definitions:
        basic = _mapping_child(signal_root, aliases)
        advanced = _mapping_child(cell_root, aliases)
        sector = _mapping_child(advanced, ("sector",))

        metrics: list[dict[str, Any]] = []
        for metric_definition in SIGNAL_METRICS:
            value, source_name = _radio_value(
                metric_definition["candidates"],
                (("cell.sector", sector), ("gateway.signal", basic), ("cell", advanced)),
            )
            if not _has_meaningful_value(value):
                continue
            number = _number_or_none(value)
            score = _metric_score(metric_definition["kind"], number)
            metrics.append(
                {
                    "key": metric_definition["key"],
                    "label": metric_definition["label"],
                    "value": number if number is not None else value,
                    "display": _format_metric_value(
                        value,
                        number,
                        metric_definition["unit"],
                    ),
                    "unit": metric_definition["unit"],
                    "score": score,
                    "rating": _rating_from_score(score),
                    "source": source_name,
                }
            )

        cqi, cqi_source = _radio_value(
            ("cqi", "channelqualityindicator"),
            (("cell", advanced), ("cell.sector", sector), ("gateway.signal", basic)),
        )
        if _has_meaningful_value(cqi):
            cqi_number = _number_or_none(cqi)
            cqi_score = _metric_score("cqi", cqi_number)
            metrics.append(
                {
                    "key": "cqi",
                    "label": "CQI",
                    "value": cqi_number if cqi_number is not None else cqi,
                    "display": _format_metric_value(cqi, cqi_number, ""),
                    "unit": "",
                    "score": cqi_score,
                    "rating": _rating_from_score(cqi_score),
                    "source": cqi_source,
                }
            )

        bands_value, _ = _radio_value(
            ("bands", "band"),
            (("gateway.signal", basic), ("cell.sector", sector), ("cell", advanced)),
        )
        bands = _string_list(bands_value)
        supported_value, _ = _radio_value(
            ("supportedbands", "supported_bands"),
            (("cell", advanced),),
        )
        supported_bands = _string_list(supported_value)
        status_value, _ = _radio_value(("status", "enabled"), (("cell", advanced),))
        status = _bool_or_none(status_value)
        antenna, _ = _radio_value(
            ("antennaused", "antenna_used", "antennamode", "antenna"),
            (("gateway.signal", basic), ("cell.sector", sector), ("cell", advanced)),
        )
        cell_id, _ = _radio_value(
            ("cid", "cellid", "cell_id"),
            (("gateway.signal", basic), ("cell.sector", sector), ("cell", advanced)),
        )
        node_candidates = (
            ("enbid", "e_nbid", "nbid") if key == "lte" else ("gnbid", "g_nbid", "nbid")
        )
        node_id, _ = _radio_value(
            node_candidates,
            (("gateway.signal", basic), ("cell.sector", sector), ("cell", advanced)),
        )
        arfcn, _ = _radio_value(
            ("nrarfcn", "nr_arfcn", "earfcn") if key == "nr" else ("earfcn", "lteearfcn"),
            (("cell", advanced), ("cell.sector", sector)),
        )

        cell = {
            "band": ", ".join(bands) if bands else None,
            "bands": bands,
            "bandwidth": _radio_scalar(("bandwidth", "channelbandwidth"), advanced, sector),
            "pci": _radio_scalar(("pci", "physicalcellid"), advanced, sector),
            "arfcn": _format_optional(arfcn),
            "arfcn_label": arfcn_label,
            "ecgi": _radio_scalar(("ecgi", "cgi"), advanced, sector),
            "tac": _radio_scalar(("tac", "trackingareacode"), advanced, sector),
            "mcc": _radio_scalar(("mcc", "mobilecountrycode"), advanced),
            "mnc": _radio_scalar(("mnc", "mobilenetworkcode"), advanced),
            "plmn": _radio_scalar(("plmn", "plmnname"), advanced),
            "cell_id": _format_optional(cell_id),
            "node_id": _format_optional(node_id),
            "node_label": node_label,
            "supported_bands": supported_bands,
        }
        cell = {field: value for field, value in cell.items() if _has_meaningful_value(value)}
        if "arfcn" not in cell:
            cell.pop("arfcn_label", None)
        if "node_id" not in cell:
            cell.pop("node_label", None)
        has_signal = any(metric["key"] in {"rsrp", "rsrq", "sinr", "rssi"} for metric in metrics)
        has_data = bool(metrics or cell or _has_meaningful_value(antenna))
        if not has_data:
            continue

        active = status if status is not None else has_signal
        score_values = [metric["score"] for metric in metrics if metric["score"] is not None]
        score = round(sum(score_values) / len(score_values)) if score_values else None
        radios.append(
            {
                "key": key,
                "label": label,
                "active": active,
                "status": status,
                "score": score,
                "quality": _quality_from_score(score),
                "antenna": _format_optional(antenna),
                "metrics": metrics,
                "cell": cell,
            }
        )
    return radios


def _mapping_child(mapping: dict[str, Any], candidates: tuple[str, ...]) -> dict[str, Any]:
    normalized_candidates = {_normalize_key(candidate) for candidate in candidates}
    for key, value in mapping.items():
        if _normalize_key(key) in normalized_candidates and isinstance(value, dict):
            return value
    return {}


def _radio_value(
    candidates: tuple[str, ...],
    sources: tuple[tuple[str, dict[str, Any]], ...],
) -> tuple[Any, str | None]:
    for source_name, source in sources:
        if not source:
            continue
        value = _find_mapping_value(source, candidates, exact=True)
        if _has_meaningful_value(value):
            return value, source_name
    return None, None


def _radio_scalar(candidates: tuple[str, ...], *sources: dict[str, Any]) -> str | None:
    value, _ = _radio_value(candidates, tuple(("cell", source) for source in sources))
    return _format_optional(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [
            _format_scalar(item)
            for item in value
            if _has_meaningful_value(item)
        ]
    if not _has_meaningful_value(value):
        return []
    text = _format_scalar(value)
    return [item.strip() for item in re.split(r"[,;/]", text) if item.strip()]


def _enrich_connection_from_radios(
    connection: dict[str, Any],
    radios: list[dict[str, Any]],
) -> None:
    active_keys = {
        str(radio.get("key"))
        for radio in radios
        if radio.get("active") is not False
    }
    if not connection.get("mode"):
        if {"lte", "nr"}.issubset(active_keys):
            connection["mode"] = "LTE + 5G NR"
        elif "nr" in active_keys:
            connection["mode"] = "5G NR"
        elif "lte" in active_keys:
            connection["mode"] = "4G LTE"

    preferred = next(
        (radio for radio in radios if radio.get("key") == "nr" and radio.get("active") is not False),
        None,
    ) or next((radio for radio in radios if radio.get("active") is not False), None)
    if not preferred:
        return
    cell = preferred.get("cell") if isinstance(preferred.get("cell"), dict) else {}
    for target, source in (
        ("band", "band"),
        ("pci", "pci"),
        ("tac", "tac"),
        ("cell_id", "cell_id"),
        ("mcc", "mcc"),
        ("mnc", "mnc"),
        ("plmn", "plmn"),
    ):
        if not connection.get(target) and cell.get(source):
            connection[target] = cell[source]
    arfcn = cell.get("arfcn")
    if arfcn:
        connection["nr_arfcn" if preferred.get("key") == "nr" else "earfcn"] = arfcn


def _system_summary(
    payload: dict[str, Any],
    cell_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    combined = list(_flatten_leaves(payload))
    if cell_payload:
        combined.extend(_flatten_leaves(cell_payload, ("advanced_cell",)))

    temperature_match = _find_exact_value(
        combined,
        (
            "temperaturec",
            "temperature_c",
            "devicetemperature",
            "cputemperature",
            "modemtemperature",
            "temperature",
        ),
    )
    temperature = None
    if temperature_match:
        path, raw_temperature = temperature_match
        number = _number_or_none(raw_temperature)
        if number is not None:
            source_text = ".".join(path)
            raw_text = str(raw_temperature).lower()
            if "fahrenheit" in source_text.lower() or " f" in raw_text:
                celsius = (number - 32) * 5 / 9
            elif number > 1000:
                celsius = number / 1000
            else:
                celsius = number
            temperature = {
                "celsius": round(celsius, 1),
                "fahrenheit": round((celsius * 9 / 5) + 32, 1),
                "display": f"{_format_number(round(celsius, 1))} C",
                "source": source_text,
            }

    time_root = _mapping_child(payload, ("time",))
    signal_root = _mapping_child(payload, ("signal",))
    generic = _mapping_child(signal_root, ("generic",))
    device_root = _mapping_child(payload, ("device",))
    uptime_value = _find_mapping_value(time_root, ("uptime", "up_time"), exact=True)
    uptime_seconds = _number_or_none(uptime_value)
    local_time = _find_mapping_value(time_root, ("localtime", "local_time"), exact=True)
    timezone_value = _find_mapping_value(
        time_root,
        ("localtimezone", "local_time_zone", "timezone"),
        exact=True,
    )

    summary: dict[str, Any] = {
        "temperature": temperature,
        "temperature_exposed": temperature is not None,
        "uptime_seconds": round(uptime_seconds) if uptime_seconds is not None else None,
        "uptime": _format_duration(uptime_seconds) if uptime_seconds is not None else None,
        "local_time": _format_optional(local_time),
        "timezone": _format_optional(timezone_value),
        "registration": _format_optional(
            _find_mapping_value(generic, ("registration",), exact=True)
        ),
        "roaming": _bool_or_none(_find_mapping_value(generic, ("roaming",), exact=True)),
        "ipv6": _bool_or_none(
            _find_mapping_value(generic, ("hasipv6", "has_ipv6"), exact=True)
        ),
        "gateway_enabled": _bool_or_none(
            _find_mapping_value(device_root, ("isenabled", "enabled"), exact=True)
        ),
        "mesh_supported": _bool_or_none(
            _find_mapping_value(device_root, ("ismeshsupported",), exact=True)
        ),
        "update_state": _format_optional(
            _find_mapping_value(device_root, ("updatestate",), exact=True)
        ),
    }
    return summary


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _build_wifi_config(
    payload: dict[str, Any] | list[Any],
    *,
    source: str | None,
) -> dict[str, Any]:
    radios = _wifi_radios_from_payload(payload)
    ssids = _wifi_ssids_from_payload(payload)
    first_ssid = next(
        (ssid["ssid"] for ssid in ssids if _has_meaningful_value(ssid.get("ssid"))),
        None,
    ) or next(
        (radio["ssid"] for radio in radios if _has_meaningful_value(radio.get("ssid"))),
        None,
    )
    enabled_values = [
        radio["radio_enabled"]
        for radio in radios
        if isinstance(radio.get("radio_enabled"), bool)
    ]
    broadcast_values = [
        ssid["broadcast_enabled"]
        for ssid in ssids
        if isinstance(ssid.get("broadcast_enabled"), bool)
    ]
    redacted_payload = _redact_sensitive(payload)

    return {
        "observed_at": utc_now().isoformat(),
        "supported": True,
        "source": source,
        "ssid": first_ssid,
        "radio_enabled": all(enabled_values) if enabled_values else None,
        "broadcast_enabled": all(broadcast_values) if broadcast_values else None,
        "ssids": ssids,
        "radios": radios,
        "sections": _sections_from_payload(
            redacted_payload if isinstance(redacted_payload, dict) else {"wifi": redacted_payload}
        ),
    }


def _wifi_radios_from_payload(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    radios: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, mapping in _wifi_radio_candidates(payload):
        if path and path[0] == "ssids":
            continue
        source = ".".join(path)
        if source in seen:
            continue
        seen.add(source)
        radio = _wifi_radio_from_mapping(path, mapping)
        if radio:
            radios.append(radio)
    return radios


def _wifi_ssids_from_payload(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    ssids: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        value = payload.get("ssids")
        if isinstance(value, list):
            for index, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    ssid = _wifi_ssid_from_mapping(("ssids", str(index)), item)
                    if ssid:
                        ssids.append(ssid)
    for path, mapping in _wifi_radio_candidates(payload):
        ssid = _wifi_ssid_from_mapping(path, mapping)
        if ssid and not any(existing["source"] == ssid["source"] for existing in ssids):
            ssids.append(ssid)
    return ssids


def _wifi_ssid_from_mapping(
    path: tuple[str, ...],
    mapping: dict[str, Any],
) -> dict[str, Any] | None:
    ssid = _find_mapping_value(mapping, WIFI_SSID_CANDIDATES, exact=True)
    broadcast = _bool_or_none(_find_mapping_value(mapping, WIFI_BROADCAST_CANDIDATES))
    enabled = _bool_or_none(_find_mapping_value(mapping, ("enabled",)))
    security = _find_mapping_value(mapping, ("encryptionVersion", "security", "encryption"))
    bands = _ssid_bands(mapping)

    if ssid is None and broadcast is None and enabled is None:
        return None

    return {
        "source": ".".join(path),
        "ssid": _format_scalar(ssid) if ssid is not None else None,
        "enabled": enabled,
        "broadcast_enabled": broadcast,
        "bands": bands,
        "security": _format_scalar(security) if security is not None else None,
        "guest": _bool_or_none(_find_mapping_value(mapping, ("guest",))),
    }


def _ssid_bands(mapping: dict[str, Any]) -> list[str]:
    bands: list[str] = []
    if _bool_or_none(mapping.get("2.4ghzSsid")) is True:
        bands.append("2.4 GHz")
    if _bool_or_none(mapping.get("5.0ghzSsid")) is True:
        bands.append("5 GHz")
    if _bool_or_none(mapping.get("6.0ghzSsid")) is True:
        bands.append("6 GHz")
    return bands


def _wifi_radio_candidates(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    candidates: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if isinstance(value, dict):
        normalized_keys = {_normalize_key(key) for key in value}
        has_wifi_value = (
            any(key in normalized_keys for key in WIFI_SSID_CANDIDATES)
            or any(key in normalized_keys for key in WIFI_RADIO_CANDIDATES)
            or any(key in normalized_keys for key in WIFI_BROADCAST_CANDIDATES)
            or "channel" in normalized_keys
        )
        path_text = _normalize_key(".".join(path))
        if has_wifi_value and (
            "wifi" in path_text
            or "wlan" in path_text
            or "radio" in path_text
            or "ap" in path_text
            or "24ghz" in path_text
            or "50ghz" in path_text
            or "60ghz" in path_text
            or any(key in normalized_keys for key in WIFI_SSID_CANDIDATES)
        ):
            candidates.append((path, value))
        for key, child in value.items():
            candidates.extend(_wifi_radio_candidates(child, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            candidates.extend(_wifi_radio_candidates(child, (*path, str(index))))
    return candidates


def _wifi_radio_from_mapping(
    path: tuple[str, ...],
    mapping: dict[str, Any],
) -> dict[str, Any] | None:
    ssid = _find_mapping_value(mapping, WIFI_SSID_CANDIDATES, exact=True)
    enabled = _bool_or_none(_find_mapping_value(mapping, WIFI_RADIO_CANDIDATES))
    broadcast = _bool_or_none(_find_mapping_value(mapping, WIFI_BROADCAST_CANDIDATES))
    channel = _find_mapping_value(mapping, ("channel", "wifi_channel"))
    band = _find_mapping_value(mapping, ("band", "radio", "frequency", "freq", "name"))
    security = _find_mapping_value(mapping, ("security", "encryption", "authmode"))

    if ssid is None and enabled is None and broadcast is None and channel is None:
        return None

    return {
        "source": ".".join(path),
        "band": _infer_wifi_band(path, band),
        "ssid": _format_scalar(ssid) if ssid is not None else None,
        "radio_enabled": enabled,
        "broadcast_enabled": broadcast,
        "channel": _format_scalar(channel) if channel is not None else None,
        "security": _format_scalar(security) if security is not None else None,
    }


def _infer_wifi_band(path: tuple[str, ...], value: Any) -> str | None:
    text = f"{' '.join(path)} {value or ''}".lower()
    if "2.4" in text or "2g" in text or "24" in text:
        return "2.4 GHz"
    if "5.0" in text or "5g" in text or "5ghz" in text or "50" in text:
        return "5 GHz"
    if value is not None:
        return _format_scalar(value)
    return None


def _set_wifi_ssid(value: Any, ssid: str) -> int:
    count = 0
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in WIFI_SSID_CANDIDATES and normalized != "bssid":
                value[key] = ssid
                count += 1
            else:
                count += _set_wifi_ssid(child, ssid)
    elif isinstance(value, list):
        for child in value:
            count += _set_wifi_ssid(child, ssid)
    return count


def _set_wifi_radio_enabled(value: Any, enabled: bool) -> int:
    count = 0
    if isinstance(value, dict):
        specific_radio_keys = set(WIFI_RADIO_CANDIDATES) - {"enabled"}
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in specific_radio_keys:
                value[key] = enabled
                count += 1
            else:
                count += _set_wifi_radio_enabled(child, enabled)
    elif isinstance(value, list):
        for child in value:
            count += _set_wifi_radio_enabled(child, enabled)
    return count


def _set_wifi_ssid_enabled(value: Any, enabled: bool) -> int:
    count = 0
    if isinstance(value, dict):
        has_ssid_name = any(_normalize_key(key) in WIFI_SSID_CANDIDATES for key in value)
        for key, child in value.items():
            normalized = _normalize_key(key)
            if has_ssid_name and normalized == "enabled":
                value[key] = enabled
                count += 1
            else:
                count += _set_wifi_ssid_enabled(child, enabled)
    elif isinstance(value, list):
        for child in value:
            count += _set_wifi_ssid_enabled(child, enabled)
    return count


def _set_wifi_broadcast_enabled(value: Any, enabled: bool) -> int:
    count = 0
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in WIFI_BROADCAST_CANDIDATES:
                value[key] = enabled
                count += 1
            else:
                count += _set_wifi_broadcast_enabled(child, enabled)
    elif isinstance(value, list):
        for child in value:
            count += _set_wifi_broadcast_enabled(child, enabled)
    return count


def _connected_devices_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates = _client_list_candidates(payload)
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()

    for _score, path, items in candidates:
        for item in items:
            if not isinstance(item, dict):
                continue
            device = _client_from_mapping(item, source=".".join(path))
            if device is None:
                continue
            identity_key = (
                device.get("mac_address")
                or device.get("ip_address")
                or device.get("hostname")
                or device["id"]
            )
            if identity_key in seen:
                continue
            seen.add(str(identity_key))
            devices.append(device)

    return devices


def _client_list_candidates(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[int, tuple[str, ...], list[Any]]]:
    candidates: list[tuple[int, tuple[str, ...], list[Any]]] = []
    if isinstance(value, list):
        score = sum(_client_mapping_score(item) for item in value if isinstance(item, dict))
        path_text = _normalize_key(".".join(path))
        if score > 0 and (
            "client" in path_text
            or "device" in path_text
            or "host" in path_text
            or "lan" in path_text
            or not path
        ):
            candidates.append((score, path or ("clients",), value))
        for index, child in enumerate(value, start=1):
            candidates.extend(_client_list_candidates(child, (*path, str(index))))
    elif isinstance(value, dict):
        for key, child in value.items():
            candidates.extend(_client_list_candidates(child, (*path, str(key))))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def _client_mapping_score(mapping: dict[str, Any]) -> int:
    flattened = _flatten_leaves(mapping)
    score = 0
    for path, value in flattened:
        if not _has_meaningful_value(value):
            continue
        normalized = _normalize_key(path[-1])
        if normalized in CLIENT_FIELD_CANDIDATES["mac_address"]:
            score += 5
        elif normalized in CLIENT_FIELD_CANDIDATES["ip_address"]:
            score += 3
        elif normalized in CLIENT_FIELD_CANDIDATES["hostname"]:
            score += 2
        elif normalized in CLIENT_FIELD_CANDIDATES["interface"]:
            score += 1
    return score


def _client_from_mapping(
    mapping: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    mac = _normalize_mac(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["mac_address"]))
    ip_address = _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["ip_address"]))
    hostname = _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["hostname"]))
    vendor = _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["vendor"]))
    model = _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["model"]))
    os_name = _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["os"]))

    if mac is None and ip_address is None and hostname is None:
        return None

    device: dict[str, Any] = {
        "id": _client_id(mac=mac, ip_address=ip_address, hostname=hostname),
        "source": source,
        "hostname": hostname,
        "ip_address": ip_address,
        "mac_address": _mask_mac(mac),
        "mac_oui": _mac_oui(mac),
        "interface": _string_or_none(
            _find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["interface"])
        )
        or _infer_client_interface(source),
        "ssid": _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["ssid"])),
        "band": _string_or_none(_find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["band"]))
        or _infer_client_band(source),
        "rssi": _format_optional(
            _find_deep_value(mapping, CLIENT_FIELD_CANDIDATES["rssi"])
        ),
        "vendor": vendor,
        "model": model,
        "os": os_name,
    }
    device["identification"] = _identify_client(device)
    return device


def _infer_client_interface(source: str) -> str | None:
    normalized = _normalize_key(source)
    if "ethernet" in normalized or "wired" in normalized:
        return "Ethernet"
    if "24ghz" in normalized or "50ghz" in normalized or "60ghz" in normalized or "wireless" in normalized:
        return "Wi-Fi"
    return None


def _infer_client_band(source: str) -> str | None:
    normalized = _normalize_key(source)
    if "24ghz" in normalized:
        return "2.4 GHz"
    if "50ghz" in normalized:
        return "5 GHz"
    if "60ghz" in normalized:
        return "6 GHz"
    return None


def _identify_client(device: dict[str, Any]) -> dict[str, Any]:
    hostname = str(device.get("hostname") or "")
    vendor = str(device.get("vendor") or "")
    model = str(device.get("model") or "")
    os_name = str(device.get("os") or "")
    text = " ".join([hostname, vendor, model, os_name])
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    if model:
        name = compact_device_name(vendor, model)
        return {
            "name": name,
            "confidence": 0.95,
            "method": "gateway_model",
            "detail": "Gateway telemetry included a model name",
        }

    pattern_guess = _device_guess_from_text(normalized)
    if pattern_guess:
        return pattern_guess

    if vendor:
        return {
            "name": vendor,
            "confidence": 0.45,
            "method": "vendor",
            "detail": "Vendor-level match only",
        }

    if hostname:
        return {
            "name": hostname,
            "confidence": 0.35,
            "method": "hostname",
            "detail": "Hostname only",
        }

    return {
        "name": "Unknown device",
        "confidence": 0.0,
        "method": "unknown",
        "detail": "No identifying fields were present",
    }


def _device_guess_from_text(text: str) -> dict[str, Any] | None:
    patterns: tuple[tuple[str, str, float], ...] = (
        (r"\biphone\s*(\d+\s*(?:pro max|pro|plus|mini)?)?\b", "Apple iPhone", 0.75),
        (r"\bipad\s*((?:pro|air|mini)?\s*\d*(?:th gen|generation)?)?\b", "Apple iPad", 0.75),
        (r"\bmacbook\s*(air|pro)?\b", "Apple MacBook", 0.7),
        (r"\bapple\s*watch\b", "Apple Watch", 0.7),
        (r"\bapple\s*tv\b", "Apple TV", 0.7),
        (r"\bhomepod\b", "Apple HomePod", 0.7),
        (r"\bairpods\b", "Apple AirPods", 0.65),
        (r"\bpixel\s*(\d+\s*(?:pro|a)?)?\b", "Google Pixel", 0.75),
        (r"\bgalaxy\s*((?:s|z|a|tab)\s*\d+\s*(?:ultra|plus|fe)?)?\b", "Samsung Galaxy", 0.7),
        (r"\broku\b", "Roku", 0.68),
        (r"\bchromecast\b", "Google Chromecast", 0.68),
        (r"\bnest\b", "Google Nest", 0.62),
        (r"\becho\b", "Amazon Echo", 0.62),
        (r"\bfire\s*(?:tv|stick)\b", "Amazon Fire TV", 0.68),
        (r"\bkindle\b", "Amazon Kindle", 0.68),
        (r"\bxbox\b", "Microsoft Xbox", 0.68),
        (r"\bplaystation\b|\bps5\b|\bps4\b", "Sony PlayStation", 0.68),
        (r"\bnintendo\b|\bswitch\b", "Nintendo Switch", 0.68),
        (r"\bring\b", "Ring device", 0.62),
        (r"\bwyze\b", "Wyze device", 0.62),
        (r"\bsonos\b", "Sonos speaker", 0.62),
        (r"\broomba\b", "iRobot Roomba", 0.62),
    )
    for pattern, base_name, confidence in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        suffix = ""
        if match.groups():
            suffix = " ".join(group for group in match.groups() if group).strip()
        name = compact_device_name(base_name, suffix)
        return {
            "name": name,
            "confidence": confidence + (0.15 if suffix else 0),
            "method": "hostname_pattern",
            "detail": "Matched model words from hostname or gateway label",
        }
    return None


def compact_device_name(*parts: str) -> str:
    cleaned = [_format_device_name_part(part.strip()) for part in parts if part and part.strip()]
    return " ".join(cleaned) if cleaned else "Unknown device"


def _format_device_name_part(value: str) -> str:
    if not value.islower():
        return value
    replacements = {
        "pro": "Pro",
        "max": "Max",
        "plus": "Plus",
        "mini": "Mini",
        "air": "Air",
        "ultra": "Ultra",
        "fe": "FE",
        "gen": "Gen",
        "generation": "Generation",
    }
    return " ".join(replacements.get(part, part) for part in value.split())


def _find_deep_value(mapping: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    normalized_candidates = tuple(_normalize_key(candidate) for candidate in candidates)
    for path, value in _flatten_leaves(mapping):
        if not _has_meaningful_value(value):
            continue
        normalized_key = _normalize_key(path[-1])
        if normalized_key in normalized_candidates:
            return value
    return None


def _find_mapping_value(
    mapping: dict[str, Any],
    candidates: tuple[str, ...],
    *,
    exact: bool = False,
) -> Any:
    normalized_candidates = tuple(_normalize_key(candidate) for candidate in candidates)
    for key, value in mapping.items():
        normalized = _normalize_key(key)
        if exact and normalized not in normalized_candidates:
            continue
        if not exact and not (
            normalized in normalized_candidates
            or any(candidate in normalized for candidate in normalized_candidates)
        ):
            continue
        if _has_meaningful_value(value):
            return value
    return None


def _normalize_mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = MAC_PATTERN.search(value)
    if match is None:
        return None
    compact = re.sub(r"[^0-9a-fA-F]", "", match.group(0)).upper()
    if len(compact) != 12:
        return None
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _mask_mac(mac: str | None) -> str | None:
    if mac is None:
        return None
    parts = mac.split(":")
    return ":".join((*parts[:3], "xx", "xx", "xx"))


def _mac_oui(mac: str | None) -> str | None:
    if mac is None:
        return None
    return ":".join(mac.split(":")[:3])


def _client_id(
    *,
    mac: str | None,
    ip_address: str | None,
    hostname: str | None,
) -> str:
    source = mac or ip_address or hostname or "unknown"
    return sha256(source.encode("utf-8")).hexdigest()[:16]


def _format_optional(value: Any) -> str | None:
    if not _has_meaningful_value(value):
        return None
    return _format_scalar(value)


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "enabled", "on"}:
            return True
        if normalized in {"false", "0", "no", "disabled", "off"}:
            return False
    return None


def _device_from_detection(detection: GatewayDetection) -> dict[str, str]:
    device: dict[str, str] = {}
    if detection.manufacturer:
        device["manufacturer"] = detection.manufacturer
    if detection.model:
        device["model"] = detection.model
    if detection.name:
        device["name"] = detection.name
    if detection.api_type:
        device["api"] = detection.api_type
    return device


def _device_summary(
    detection: GatewayDetection,
    flattened: list[tuple[tuple[str, ...], Any]],
) -> dict[str, Any]:
    device = _device_from_detection(detection)
    discovered = _field_summary(flattened, DEVICE_FIELDS)
    for key, value in discovered.items():
        device.setdefault(key, value)
    if detection.supported is not None:
        device["support"] = "Supported" if detection.supported else "Detected, limited support"
    return device


def _signal_summary(flattened: list[tuple[tuple[str, ...], Any]]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    used_paths: set[tuple[str, ...]] = set()
    score_parts: list[int] = []

    for definition in SIGNAL_METRICS:
        match = _find_value(flattened, definition["candidates"], used_paths=used_paths)
        if match is None:
            continue

        path, value = match
        used_paths.add(path)
        number = _number_or_none(value)
        metric_score = _metric_score(definition["kind"], number)
        if metric_score is not None:
            score_parts.append(metric_score)

        display = _format_metric_value(value, number, definition["unit"])
        metrics.append(
            {
                "key": definition["key"],
                "label": definition["label"],
                "value": value,
                "display": display,
                "unit": definition["unit"],
                "source": ".".join(path),
                "score": metric_score,
                "rating": _rating_from_score(metric_score),
            }
        )

    score = round(sum(score_parts) / len(score_parts)) if score_parts else None
    quality = _quality_from_score(score)
    return {
        "score": score,
        "quality": quality,
        "summary": _signal_summary_text(score, metrics),
        "metrics": metrics,
    }


def _field_summary(
    flattened: list[tuple[tuple[str, ...], Any]],
    fields: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    used_paths: set[tuple[str, ...]] = set()
    for key, _label, candidates in fields:
        match = _find_value(flattened, candidates, used_paths=used_paths)
        if match is None:
            continue
        path, value = match
        used_paths.add(path)
        summary[key] = _format_scalar(value)
    return summary


def _find_value(
    flattened: list[tuple[tuple[str, ...], Any]],
    candidates: tuple[str, ...],
    *,
    used_paths: set[tuple[str, ...]] | None = None,
) -> tuple[tuple[str, ...], Any] | None:
    normalized_candidates = tuple(_normalize_key(candidate) for candidate in candidates)
    for candidate in normalized_candidates:
        for path, value in flattened:
            if used_paths and path in used_paths:
                continue
            if not _has_meaningful_value(value):
                continue
            normalized_key = _normalize_key(path[-1] if path else "")
            normalized_path = _normalize_key(".".join(path))
            if candidate == normalized_key or candidate in normalized_path:
                return path, value
    return None


def _find_exact_value(
    flattened: list[tuple[tuple[str, ...], Any]],
    candidates: tuple[str, ...],
) -> tuple[tuple[str, ...], Any] | None:
    normalized_candidates = {_normalize_key(candidate) for candidate in candidates}
    for path, value in flattened:
        if not path or not _has_meaningful_value(value):
            continue
        if _normalize_key(path[-1]) in normalized_candidates:
            return path, value
    return None


def _redact_sensitive(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_sensitive(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item, key=key) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _flatten_leaves(
    value: Any,
    prefix: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        leaves: list[tuple[tuple[str, ...], Any]] = []
        for key, child in value.items():
            leaves.extend(_flatten_leaves(child, (*prefix, str(key))))
        return leaves

    if isinstance(value, list):
        if not value:
            return []
        if all(_is_scalar(item) for item in value):
            return [(prefix, ", ".join(_format_scalar(item) for item in value[:12]))]
        leaves = []
        for index, child in enumerate(value[:12], start=1):
            leaves.extend(_flatten_leaves(child, (*prefix, str(index))))
        return leaves

    if not prefix:
        return []
    return [(prefix, value)]


def _sections_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for key, value in payload.items():
        leaves = _flatten_leaves(value)
        items = [
            {
                "label": _humanize_path(path),
                "value": _format_scalar(leaf_value),
                "source": ".".join((str(key), *path)),
            }
            for path, leaf_value in leaves[:60]
            if _has_meaningful_value(leaf_value)
        ]
        if items:
            sections.append(
                {
                    "key": str(key),
                    "title": _humanize_key(str(key)),
                    "items": items,
                    "truncated": len(leaves) > len(items),
                }
            )
    return sections


def _metric_score(kind: str, value: float | None) -> int | None:
    if value is None:
        return None
    if kind == "sinr":
        return _threshold_score(value, (20, 100), (13, 80), (5, 55), (0, 35), -100)
    if kind == "rsrp":
        return _threshold_score(value, (-80, 100), (-90, 80), (-100, 60), (-110, 35), -200)
    if kind == "rsrq":
        return _threshold_score(value, (-10, 90), (-15, 65), (-20, 40), (-30, 20), -100)
    if kind == "rssi":
        return _threshold_score(value, (-65, 100), (-75, 80), (-85, 60), (-95, 35), -200)
    if kind == "bars":
        if value <= 5:
            return max(0, min(100, round((value / 5) * 100)))
        return max(0, min(100, round(value)))
    if kind == "cqi":
        return max(0, min(100, round((value / 15) * 100)))
    return None


def _threshold_score(
    value: float,
    excellent: tuple[float, int],
    good: tuple[float, int],
    fair: tuple[float, int],
    weak: tuple[float, int],
    floor: float,
) -> int:
    for threshold, score in (excellent, good, fair, weak):
        if value >= threshold:
            return score
    if value <= floor:
        return 0
    return 10


def _quality_from_score(score: int | None) -> str:
    if score is None:
        return "Unknown"
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    if score >= 30:
        return "Weak"
    return "Poor"


def _rating_from_score(score: int | None) -> str:
    return _quality_from_score(score).lower()


def _signal_summary_text(score: int | None, metrics: list[dict[str, Any]]) -> str:
    if score is None:
        return "No signal metrics were found in the gateway response"
    metric_names = ", ".join(metric["label"] for metric in metrics[:3])
    if score >= 85:
        return f"Cellular signal looks excellent across {metric_names}"
    if score >= 70:
        return f"Cellular signal looks healthy across {metric_names}"
    if score >= 50:
        return f"Cellular signal is usable, but {metric_names} could be better"
    return f"Cellular signal is weak; check placement using {metric_names}"


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = NUMBER_PATTERN.search(value)
    if match is None:
        return None
    return float(match.group(0))


def _format_metric_value(value: Any, number: float | None, unit: str) -> str:
    original = _format_scalar(value)
    if number is None or not unit:
        return original
    if unit.lower() in original.lower():
        return original
    return f"{_format_number(number)} {unit}"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _format_number(float(value))
    return str(value)


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _humanize_path(path: tuple[str, ...]) -> str:
    if not path:
        return "Value"
    cleaned = [part for part in path if not part.isdigit()]
    return " / ".join(_humanize_key(part) for part in cleaned[-3:]) or "Value"


def _humanize_key(key: str) -> str:
    spaced = CAMEL_BOUNDARY_PATTERN.sub(" ", str(key))
    spaced = spaced.replace("_", " ").replace("-", " ").replace(".", " ")
    spaced = re.sub(r"\s+", " ", spaced).strip()
    if not spaced:
        return "Value"
    upper_terms = {
        "apn",
        "api",
        "arfcn",
        "dns",
        "ip",
        "ipv4",
        "ipv6",
        "lte",
        "mcc",
        "mnc",
        "nr",
        "pci",
        "rsrp",
        "rsrq",
        "rssi",
        "sinr",
        "ssid",
        "tac",
        "wan",
        "wifi",
    }
    return " ".join(
        part.upper() if part.lower() in upper_terms else part.capitalize()
        for part in spaced.split(" ")
    )


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _candidate_tmi_base_urls(base_url: str) -> tuple[str, ...]:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.hostname:
        return (normalized,)

    path = parsed.path.rstrip("/") or "/TMI/v1"
    ports: list[int | None] = [parsed.port]
    if parsed.scheme == "http":
        # G5AR firmware exposes TMI v1 on plain HTTP port 80, while several
        # other TMHI gateways expose the same API on 8080.
        ports.extend([None, 8080])

    candidates: list[str] = []
    for port in ports:
        candidate = _format_base_url(parsed.scheme, parsed.hostname, port, path)
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _format_base_url(
    scheme: str,
    hostname: str,
    port: int | None,
    path: str,
) -> str:
    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{netloc}{path}"


def _summarize_errors(errors: list[str], fallback: str) -> str:
    if not errors:
        return fallback
    summary = "; ".join(errors[:3])
    if len(errors) > 3:
        summary = f"{summary}; {len(errors) - 3} more attempts failed"
    return summary


def _extract_mapping(response: httpx.Response, key: str) -> dict[str, Any]:
    if not response.is_success:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _extract_first_mapping(response: httpx.Response, key: str) -> dict[str, Any]:
    if not response.is_success:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
