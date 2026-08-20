"""Discovery helpers for UniFi Drive / UNAS devices."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL

from .const import (
    CONF_WOL_ENABLED,
    CONF_WOL_MAC_ADDRESS,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
)
from .discovery_common import (
    clean_host_label as _clean_host_label,
)
from .discovery_common import (
    clean_text as _clean_text,
)
from .discovery_common import (
    device_key as _device_key,
)
from .discovery_common import (
    mac_from_eui64_ipv6 as _mac_from_eui64_ipv6,
)
from .discovery_common import (
    parse_bool as _parse_bool,
)
from .discovery_identity import discovery_host_key, discovery_mac_key

CONF_DISCOVERED_DEVICE = "discovered_device"
MANUAL_DISCOVERY_VALUE = "__manual__"
DISCOVERY_TIMEOUT = 10

_UNAS_MARKERS = (
    "unas",
    "unifi drive",
    "unifi-drive",
    "network attached storage",
)
_NON_API_ZEROCONF_TYPES = {
    "_device-info._tcp.local.",
    "_sftp-ssh._tcp.local.",
    "_smb._tcp.local.",
    "_ssh._tcp.local.",
    "_workstation._tcp.local.",
}
_ZEROCONF_SERVICE_SUFFIX_RE = re.compile(
    r"\._[^.]+\._(?:tcp|udp)\.local\.?$",
    re.IGNORECASE,
)


class _UnifiScanner(Protocol):
    """Protocol for the subset of the UniFi discovery scanner we use."""

    async def async_scan(
        self,
        *,
        timeout: int,
        consoles_only: bool = True,
    ) -> list[Any]:
        """Scan for UniFi OS consoles."""


@dataclass(frozen=True, slots=True)
class DiscoveredUnasDevice:
    """A discovered UniFi Drive / UNAS candidate."""

    key: str
    label: str
    host: str
    port: int = DEFAULT_PORT
    use_ssl: bool = DEFAULT_SSL
    verify_ssl: bool = DEFAULT_VERIFY_SSL
    hostname: str | None = None
    model: str | None = None
    platform: str | None = None
    product_name: str | None = None
    hw_addr: str | None = None
    wol_enabled: bool | None = None
    source: str = "unifi_discovery"
    identity_source: str = "host"
    confidence: int | None = None
    identity_conflicts: tuple[str, ...] = ()


def connection_defaults_from_discovery(
    device: DiscoveredUnasDevice,
) -> dict[str, Any]:
    """Return connection-form defaults for a discovered device."""
    return {
        CONF_HOST: device.host,
        CONF_PORT: device.port,
        CONF_SSL: device.use_ssl,
        CONF_VERIFY_SSL: device.verify_ssl,
    }


def feature_defaults_from_discovery(
    device: DiscoveredUnasDevice,
) -> dict[str, Any]:
    """Return feature-form defaults for a discovered device."""
    defaults: dict[str, Any] = {}
    if device.wol_enabled is not None and (device.hw_addr or not device.wol_enabled):
        defaults[CONF_WOL_ENABLED] = device.wol_enabled
    if device.hw_addr:
        defaults[CONF_WOL_MAC_ADDRESS] = device.hw_addr
    return defaults


def feature_defaults_from_system_payload(payload: Any) -> dict[str, Any]:
    """Return WOL feature defaults from UniFi OS system metadata."""
    if not isinstance(payload, dict):
        return {}

    wol_enabled: bool | None = None
    mac_address: str | None = None

    for container in _system_wol_containers(payload):
        if wol_enabled is None:
            wol_enabled = _mapping_bool(
                container,
                "wol",
                "wolEnabled",
                "wol_enabled",
                "wakeOnLan",
                "wakeOnLanEnabled",
                "wake_on_lan",
                "wake_on_lan_enabled",
                "enableWakeOnLan",
                "enable_wake_on_lan",
                "isWolEnabled",
                "isWakeOnLanEnabled",
            )
        if mac_address is None:
            mac_address = _mapping_text(
                container,
                "mac",
                "macAddress",
                "mac_address",
                "hwAddr",
                "hw_addr",
            )

    if wol_enabled is None:
        for container in _nested_wol_containers(payload):
            wol_enabled = _mapping_bool(
                container,
                "enabled",
                "value",
                "state",
            )
            if wol_enabled is not None:
                break

    defaults: dict[str, Any] = {}
    if wol_enabled is not None and (mac_address or not wol_enabled):
        defaults[CONF_WOL_ENABLED] = wol_enabled
    if mac_address:
        defaults[CONF_WOL_MAC_ADDRESS] = mac_address
    return defaults


def discovery_options(
    devices: tuple[DiscoveredUnasDevice, ...],
) -> dict[str, str]:
    """Return select options for discovered devices plus manual entry."""
    options = {MANUAL_DISCOVERY_VALUE: "Enter host manually"}
    options.update({device.key: device.label for device in devices})
    return options


async def async_discover_unas_devices(
    *,
    timeout: int = DISCOVERY_TIMEOUT,
    scanner_factory: Any | None = None,
) -> tuple[DiscoveredUnasDevice, ...]:
    """Scan the local network for UniFi Drive / UNAS devices."""
    if scanner_factory is None:
        try:
            scanner_factory = import_module("unifi_discovery").AIOUnifiScanner
        except ImportError:
            return ()

    scanner = scanner_factory()
    devices = await scanner.async_scan(timeout=timeout, consoles_only=True)
    return discovered_unas_devices_from_scan(devices)


def discovered_unas_devices_from_scan(
    devices: list[Any] | tuple[Any, ...],
) -> tuple[DiscoveredUnasDevice, ...]:
    """Return deduplicated UNAS candidates from raw UniFi discovery devices."""
    discovered: dict[str, DiscoveredUnasDevice] = {}
    hosts_seen: set[str] = set()

    for device in devices:
        if not _looks_like_unas_device(device):
            continue

        host = _device_host(device)
        if host is None:
            continue

        host_key = discovery_host_key(host)
        if host_key in hosts_seen:
            continue

        raw_hw_addr = _text_attr(device, "hw_addr", "mac_address")
        hw_addr = raw_hw_addr if discovery_mac_key(raw_hw_addr) else None
        identity_conflicts = (
            ("invalid_unifi_discovery_mac",)
            if raw_hw_addr is not None and hw_addr is None
            else ()
        )
        key = _device_key(host, hw_addr)
        if key in discovered:
            continue

        candidate = DiscoveredUnasDevice(
            key=key,
            label=_device_label(device, host),
            host=host,
            hostname=_text_attr(device, "hostname"),
            model=_text_attr(device, "model"),
            platform=_text_attr(device, "platform"),
            product_name=_text_attr(device, "product_name"),
            hw_addr=hw_addr,
            wol_enabled=_device_wol_enabled(device),
            identity_source="unifi_discovery_mac" if hw_addr else "host",
            confidence=_discovery_confidence(
                source="unifi_discovery",
                host=host,
                hw_addr=hw_addr,
                identity_conflicts=identity_conflicts,
            ),
            identity_conflicts=identity_conflicts,
        )
        discovered[key] = candidate
        hosts_seen.add(host_key)

    return tuple(sorted(discovered.values(), key=lambda item: item.label.lower()))


def discovered_unas_device_from_zeroconf(info: Any) -> DiscoveredUnasDevice | None:
    """Return a UNAS candidate from Home Assistant zeroconf discovery info."""
    properties = getattr(info, "properties", {}) or {}
    text = " ".join(
        part
        for part in (
            _clean_text(getattr(info, "name", None)),
            _clean_text(getattr(info, "hostname", None)),
            _clean_text(getattr(info, "type", None)),
            *(_clean_text(value) for value in _zeroconf_property_values(properties)),
        )
        if part
    ).lower()
    if not any(marker in text for marker in _UNAS_MARKERS):
        return None

    host = _zeroconf_host(info)
    if host is None:
        return None

    port = _zeroconf_api_port(info)
    hw_addr, identity_source, identity_conflicts = _zeroconf_hw_addr(
        info,
        properties,
        "mac",
        "macaddress",
        "mac_address",
        "hwaddr",
        "hw_addr",
    )
    wol_enabled = _zeroconf_bool_property(
        properties,
        "wol",
        "wol_enabled",
        "wake_on_lan",
        "wake_on_lan_enabled",
        "wakeonlan",
        "wake-on-lan",
        "magic_packet",
        "magic_packet_enabled",
    )
    hostname = _clean_host_label(getattr(info, "hostname", None))
    name = _zeroconf_service_instance_name(
        getattr(info, "name", None),
        getattr(info, "type", None),
    )
    product = _zeroconf_property(properties, "product_name", "product", "model")
    label = _zeroconf_label(
        product=product,
        name=name,
        hostname=hostname,
        host=host,
        hw_addr=hw_addr,
    )

    return DiscoveredUnasDevice(
        key=_device_key(host, hw_addr),
        label=label,
        host=host,
        port=port,
        use_ssl=port != 80,
        hostname=hostname,
        model=_zeroconf_property(properties, "model"),
        platform=_zeroconf_property(properties, "platform"),
        product_name=product,
        hw_addr=hw_addr,
        wol_enabled=wol_enabled,
        source="zeroconf",
        identity_source=identity_source,
        confidence=_discovery_confidence(
            source="zeroconf",
            host=host,
            hw_addr=hw_addr,
            identity_conflicts=identity_conflicts,
        ),
        identity_conflicts=identity_conflicts,
    )


def _looks_like_unas_device(device: Any) -> bool:
    """Return whether raw discovery metadata looks like a UNAS device."""
    parts = [
        _text_attr(device, "hostname"),
        _text_attr(device, "model"),
        _text_attr(device, "platform"),
        _text_attr(device, "product_name"),
    ]
    text = " ".join(part for part in parts if part).lower()
    return any(marker in text for marker in _UNAS_MARKERS)


def _device_host(device: Any) -> str | None:
    """Return the best host address exposed by the raw discovery device."""
    for attr in ("source_ip", "ip_address", "host"):
        value = _clean_text(getattr(device, attr, None))
        if value:
            return value

    for container_attr in ("ip_info", "addr_entry"):
        value = _host_from_container(getattr(device, container_attr, None))
        if value:
            return value

    return None


def _device_wol_enabled(device: Any) -> bool | None:
    """Return WOL-enabled state from known raw discovery attributes."""
    for attr in (
        "wol_enabled",
        "is_wol_enabled",
        "wake_on_lan_enabled",
        "wakeonlan",
        "wake_on_lan",
        "magic_packet_enabled",
    ):
        parsed = _parse_bool(getattr(device, attr, None))
        if parsed is not None:
            return parsed
    return None


def _host_from_container(value: Any) -> str | None:
    """Return a host string from optional nested discovery metadata."""
    if isinstance(value, dict):
        for key in ("ip", "address", "addr", "host"):
            host = _clean_text(value.get(key))
            if host:
                return host
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            host = _host_from_container(item)
            if host:
                return host
    return None


def _zeroconf_host(info: Any) -> str | None:
    """Return the first usable host from zeroconf discovery info."""
    service_type = _clean_text(getattr(info, "type", None))
    host = _clean_text(getattr(info, "host", None))

    if host and "._" not in host:
        return host

    hostname = _clean_host_label(getattr(info, "hostname", None))
    if hostname:
        return hostname

    if host and service_type:
        normalized = _zeroconf_service_instance_name(host, service_type)
        normalized = _clean_host_label(normalized)
        if normalized and "." in normalized:
            return normalized

    host = _clean_text(getattr(info, "ip_address", None))
    if host:
        return host

    addresses = getattr(info, "ip_addresses", None)
    if isinstance(addresses, (list, tuple)) and addresses:
        return _clean_text(addresses[0])
    return None



def _zeroconf_port(info: Any) -> int:
    """Return a sane port from zeroconf discovery info."""
    try:
        port = int(getattr(info, "port", DEFAULT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PORT
    if port < 1 or port > 65535:
        return DEFAULT_PORT
    return port


def _zeroconf_api_port(info: Any) -> int:
    """Return the UniFi Drive API port implied by zeroconf service data."""
    service_type = (_clean_text(getattr(info, "type", None)) or "").lower()
    if service_type in _NON_API_ZEROCONF_TYPES:
        return DEFAULT_PORT
    return _zeroconf_port(info)


def _zeroconf_hw_addr(
    info: Any,
    properties: Any,
    *keys: str,
) -> tuple[str | None, str, tuple[str, ...]]:
    """Return the advertised or EUI-64-derived zeroconf MAC identity."""
    advertised = _zeroconf_property(properties, *keys)
    advertised_mac = discovery_mac_key(advertised)
    derived = _zeroconf_mac_from_addresses(info)
    derived_mac = discovery_mac_key(derived)
    conflicts: list[str] = []

    if advertised and advertised_mac is None:
        conflicts.append("invalid_zeroconf_mac")
    if advertised_mac and derived_mac and advertised_mac != derived_mac:
        conflicts.append("zeroconf_mac_eui64_mismatch")

    if advertised_mac:
        return advertised, "zeroconf_property_mac", tuple(conflicts)
    if derived_mac:
        return derived, "zeroconf_eui64_mac", tuple(conflicts)
    return None, "host", tuple(conflicts)


def _zeroconf_mac_from_addresses(info: Any) -> str | None:
    """Derive a MAC address from a link-local IPv6 EUI-64 address if present."""
    for address in _zeroconf_addresses(info):
        if hw_addr := _mac_from_eui64_ipv6(address):
            return hw_addr
    return None


def _zeroconf_addresses(info: Any) -> tuple[Any, ...]:
    """Return address values exposed by Home Assistant zeroconf metadata."""
    addresses: list[Any] = []
    for attr in ("ip_addresses", "addresses"):
        value = getattr(info, attr, None)
        if isinstance(value, (list, tuple, set, frozenset)):
            addresses.extend(value)
        elif value is not None:
            addresses.append(value)
    for attr in ("host", "ip_address"):
        value = getattr(info, attr, None)
        if value is not None:
            addresses.append(value)
    return tuple(addresses)


def _zeroconf_property(properties: Any, *keys: str) -> str | None:
    """Return a normalized zeroconf property value."""
    if not isinstance(properties, dict):
        return None
    lowered = {_clean_property_key(key): value for key, value in properties.items()}
    for key in keys:
        value = _clean_text(lowered.get(key.lower()))
        if value:
            return value
    return None


def _zeroconf_bool_property(properties: Any, *keys: str) -> bool | None:
    """Return a boolean zeroconf property value."""
    if not isinstance(properties, dict):
        return None
    lowered = {_clean_property_key(key): value for key, value in properties.items()}
    for key in keys:
        parsed = _parse_bool(lowered.get(key.lower()))
        if parsed is not None:
            return parsed
    return None


def _zeroconf_property_values(properties: Any) -> tuple[Any, ...]:
    """Return zeroconf property values for marker matching."""
    if not isinstance(properties, dict):
        return ()
    return tuple(properties.values())


def _discovery_confidence(
    *,
    source: str,
    host: str,
    hw_addr: str | None,
    identity_conflicts: tuple[str, ...],
) -> int:
    """Return a bounded confidence score for diagnostics and dedupe decisions."""
    score = 40
    if source == "unifi_discovery":
        score += 20
    elif source == "zeroconf":
        score += 10
    if discovery_host_key(host):
        score += 10
    if discovery_mac_key(hw_addr):
        score += 30
    if identity_conflicts:
        score -= 25
    return max(0, min(score, 100))


def _system_wol_containers(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return likely system metadata containers for WOL state and MAC address."""
    containers: list[dict[str, Any]] = [payload]
    for key in (
        "hardware",
        "network",
        "ethernet",
        "lan",
        "settings",
        "power",
        "wakeOnLan",
        "wake_on_lan",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            containers.append(value)

    devices = payload.get("devices")
    if isinstance(devices, dict):
        unifi_os = devices.get("unifiOS")
        if isinstance(unifi_os, list):
            containers.extend(item for item in unifi_os if isinstance(item, dict))
    return tuple(containers)


def _nested_wol_containers(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return nested containers that specifically describe WOL settings."""
    containers: list[dict[str, Any]] = []
    for parent in _system_wol_containers(payload):
        for key in ("wol", "wakeOnLan", "wake_on_lan", "wake-on-lan"):
            value = parent.get(key)
            if isinstance(value, dict):
                containers.append(value)
    return tuple(containers)


def _mapping_text(payload: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-empty text value from a mapping."""
    for key in keys:
        value = _clean_text(payload.get(key))
        if value:
            return value
    return None


def _mapping_bool(payload: dict[str, Any], *keys: str) -> bool | None:
    """Return the first parseable boolean value from a mapping."""
    for key in keys:
        parsed = _parse_bool(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _clean_property_key(value: Any) -> str:
    """Return a lowercase zeroconf property key."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    return str(value).strip().lower()


def _device_label(device: Any, host: str) -> str:
    """Return a user-facing label for a discovered device."""
    product = _text_attr(device, "product_name", "model", "platform")
    hostname = _text_attr(device, "hostname")

    if product and hostname and product.lower() != hostname.lower():
        return f"{product} ({hostname}, {host})"
    if product:
        return f"{product} ({host})"
    if hostname:
        return f"{hostname} ({host})"
    return host


def _zeroconf_service_instance_name(name: Any, service_type: Any) -> str | None:
    """Return a readable zeroconf instance name without the service suffix."""
    instance = _clean_text(name)
    if instance is None:
        return None

    trimmed = instance.rstrip(".")
    service = (_clean_text(service_type) or "").strip(".")
    if service and trimmed.lower().endswith(f".{service}".lower()):
        trimmed = trimmed[: -(len(service) + 1)]
    else:
        trimmed = _ZEROCONF_SERVICE_SUFFIX_RE.sub("", trimmed)
    return _clean_text(trimmed.rstrip("."))


def _zeroconf_label(
    *,
    product: str | None,
    name: str | None,
    hostname: str | None,
    host: str,
    hw_addr: str | None,
) -> str:
    """Return a concise user-facing label for zeroconf discoveries."""
    label_name = product or name or hostname
    identity = discovery_mac_key(hw_addr) or _clean_host_label(host)
    if label_name and identity and label_name.lower() != identity.lower():
        return f"{label_name} ({identity})"
    return label_name or identity or host


def _text_attr(device: Any, *attrs: str) -> str | None:
    """Return the first non-empty text attribute from a raw object."""
    for attr in attrs:
        value = _clean_text(getattr(device, attr, None))
        if value:
            return value
    return None
