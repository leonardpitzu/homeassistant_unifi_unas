"""Helpers for discovery identity and config-entry dedupe."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any

from homeassistant.const import CONF_HOST

from .const import (
    CONF_DISCOVERY_CONFIDENCE,
    CONF_DISCOVERY_HOST_ALIASES,
    CONF_DISCOVERY_IDENTITY_CONFLICTS,
    CONF_DISCOVERY_IDENTITY_SOURCE,
    CONF_DISCOVERY_LAST_SEEN,
    CONF_DISCOVERY_MAC_ADDRESS,
    CONF_WOL_MAC_ADDRESS,
    DEFAULT_PORT,
)
from .entry_options import merged_entry_data_options
from .wake_on_lan import normalize_mac_address

DISCOVERY_FLOW_CONTEXT_MAC = "unifi_unas_discovery_mac"
DISCOVERY_FLOW_CONTEXT_HOSTS = "unifi_unas_discovery_hosts"
_DEFAULT_VALIDATED_IDENTITY_SOURCE = "validated_system"
_DISCOVERY_LAST_SEEN_UPDATE_INTERVAL = timedelta(minutes=5)


def discovery_host_key(host: object) -> str:
    """Return a stable host key for discovered-device dedupe."""
    if host in (None, ""):
        return ""
    normalized = str(host).strip().lower().rstrip(".")
    if normalized.startswith("[") and "]" in normalized:
        normalized = normalized[1 : normalized.index("]")]
    try:
        return ip_address(normalized).compressed.lower()
    except ValueError:
        return normalized


def discovered_device_host_keys(device: Any) -> set[str]:
    """Return normalized host aliases that can identify a discovered device."""
    hosts = {discovery_host_key(getattr(device, "host", ""))}
    if hostname := getattr(device, "hostname", None):
        hosts.add(discovery_host_key(hostname))
    hosts.discard("")
    return hosts


def entry_discovery_host_keys(entry: Any) -> set[str]:
    """Return normalized host aliases known for an existing config entry."""
    keys: set[str] = set()
    current = merged_entry_data_options(entry)
    keys.add(discovery_host_key(current.get(CONF_HOST, "")))

    aliases = current.get(CONF_DISCOVERY_HOST_ALIASES)
    if isinstance(aliases, (list, tuple, set)):
        keys.update(discovery_host_key(alias) for alias in aliases)

    unique_id = str(getattr(entry, "unique_id", "") or "")
    if ":" in unique_id and not discovery_mac_key(unique_id):
        host, _, port = unique_id.rpartition(":")
        if port.isdecimal():
            keys.add(discovery_host_key(host))

    keys.discard("")
    return keys


def discovery_mac_key(mac_address: object) -> str | None:
    """Return a normalized MAC key for discovered-device dedupe."""
    if mac_address in (None, ""):
        return None
    try:
        return normalize_mac_address(str(mac_address))
    except ValueError:
        return None


def entry_discovery_mac_keys(entry: Any) -> set[str]:
    """Return normalized MAC aliases known for an existing config entry."""
    keys: set[str] = set()
    current = merged_entry_data_options(entry)
    if mac := discovery_mac_key(current.get(CONF_DISCOVERY_MAC_ADDRESS)):
        keys.add(mac)
    if mac := discovery_mac_key(current.get(CONF_WOL_MAC_ADDRESS)):
        keys.add(mac)
    if mac := discovery_mac_key(getattr(entry, "unique_id", None)):
        keys.add(mac)
    return keys


def discovery_identity_defaults_from_device(device: Any) -> dict[str, Any]:
    """Return non-option identity defaults from discovery metadata."""
    defaults: dict[str, Any] = {}
    if mac := discovery_mac_key(getattr(device, "hw_addr", None)):
        defaults[CONF_DISCOVERY_MAC_ADDRESS] = mac
    if hosts := discovered_device_host_keys(device):
        defaults[CONF_DISCOVERY_HOST_ALIASES] = sorted(hosts)
    source = discovery_identity_token(getattr(device, "identity_source", None))
    if source == "host" and defaults.get(CONF_DISCOVERY_MAC_ADDRESS):
        source = "discovery_mac"
    if source:
        defaults[CONF_DISCOVERY_IDENTITY_SOURCE] = source
    confidence = discovery_confidence_score(getattr(device, "confidence", None))
    if confidence is not None:
        defaults[CONF_DISCOVERY_CONFIDENCE] = confidence
    if conflicts := discovery_identity_conflict_codes(
        getattr(device, "identity_conflicts", None)
    ):
        defaults[CONF_DISCOVERY_IDENTITY_CONFLICTS] = conflicts
    return defaults


def discovery_flow_context_from_device(device: Any) -> dict[str, Any]:
    """Return non-sensitive context that can identify a zeroconf flow."""
    context: dict[str, Any] = {}
    if mac := discovery_mac_key(getattr(device, "hw_addr", None)):
        context[DISCOVERY_FLOW_CONTEXT_MAC] = mac
    if hosts := discovered_device_host_keys(device):
        context[DISCOVERY_FLOW_CONTEXT_HOSTS] = sorted(hosts)
    return context


def entry_matches_discovery_flow_context(
    entry: Any,
    context: Mapping[str, Any],
) -> bool:
    """Return whether an existing entry matches a pending discovery flow."""
    if (
        (mac := discovery_mac_key(context.get(DISCOVERY_FLOW_CONTEXT_MAC)))
        and mac in entry_discovery_mac_keys(entry)
    ):
        return True

    flow_hosts = context.get(DISCOVERY_FLOW_CONTEXT_HOSTS)
    if isinstance(flow_hosts, (list, tuple, set)):
        host_keys = {discovery_host_key(host) for host in flow_hosts}
        host_keys.discard("")
        if host_keys & entry_discovery_host_keys(entry):
            return True

    return False


def apply_discovery_identity_defaults(
    data: dict[str, Any],
    info: dict[str, Any],
    existing_defaults: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist a stable discovery MAC separately from editable WOL options."""
    updated = dict(data)
    existing_defaults = existing_defaults or {}
    mac_address = discovery_mac_key(
        existing_defaults.get(CONF_DISCOVERY_MAC_ADDRESS)
    )
    if mac_address is None and isinstance(info.get("feature_defaults"), dict):
        mac_address = discovery_mac_key(
            info["feature_defaults"].get(CONF_WOL_MAC_ADDRESS)
        )
    if mac_address is None:
        mac_address = discovery_mac_key(data.get(CONF_WOL_MAC_ADDRESS))
    if mac_address:
        updated[CONF_DISCOVERY_MAC_ADDRESS] = mac_address

    host_aliases = _host_aliases_from_defaults(data)
    host_aliases.update(_host_aliases_from_defaults(existing_defaults))
    host_aliases.add(discovery_host_key(data.get(CONF_HOST, "")))
    host_aliases.add(discovery_host_key(info.get("host", "")))
    host_aliases.discard("")
    if host_aliases:
        updated[CONF_DISCOVERY_HOST_ALIASES] = sorted(host_aliases)

    source = discovery_identity_token(
        existing_defaults.get(CONF_DISCOVERY_IDENTITY_SOURCE)
    )
    if source is None:
        source = _DEFAULT_VALIDATED_IDENTITY_SOURCE
    updated[CONF_DISCOVERY_IDENTITY_SOURCE] = source

    confidence = discovery_confidence_score(
        existing_defaults.get(CONF_DISCOVERY_CONFIDENCE)
    )
    if confidence is None:
        confidence = 80 if mac_address else 50
    updated[CONF_DISCOVERY_CONFIDENCE] = confidence

    conflicts = set(
        discovery_identity_conflict_codes(
            existing_defaults.get(CONF_DISCOVERY_IDENTITY_CONFLICTS)
        )
    )
    conflicts.update(discovery_identity_conflicts_for_data(updated))
    if conflicts:
        updated[CONF_DISCOVERY_IDENTITY_CONFLICTS] = sorted(conflicts)
    else:
        updated.pop(CONF_DISCOVERY_IDENTITY_CONFLICTS, None)

    updated[CONF_DISCOVERY_LAST_SEEN] = discovery_timestamp(now)
    return updated


def discovery_observation_entry_data(
    entry: Any,
    device: Any,
    *,
    extra_conflicts: tuple[str, ...] = (),
    trusted: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return entry data updated with a discovery observation."""
    data = dict(getattr(entry, "data", {}) or {})
    if trusted:
        data = apply_discovery_identity_defaults(
            data,
            {"host": getattr(device, "host", "")},
            discovery_identity_defaults_from_device(device),
            now=now,
        )
    else:
        data[CONF_DISCOVERY_LAST_SEEN] = discovery_timestamp(now)
        data[CONF_DISCOVERY_IDENTITY_SOURCE] = "conflicting_discovery"
        confidence = discovery_confidence_score(getattr(device, "confidence", None))
        if confidence is not None:
            data[CONF_DISCOVERY_CONFIDENCE] = confidence

    conflicts = set(
        discovery_identity_conflict_codes(data.get(CONF_DISCOVERY_IDENTITY_CONFLICTS))
    )
    conflicts.update(
        discovery_identity_conflict_codes(getattr(device, "identity_conflicts", None))
    )
    conflicts.update(discovery_identity_conflict_codes(extra_conflicts))
    conflicts.update(discovery_identity_conflicts_for_data(data))
    if conflicts:
        data[CONF_DISCOVERY_IDENTITY_CONFLICTS] = sorted(conflicts)
    else:
        data.pop(CONF_DISCOVERY_IDENTITY_CONFLICTS, None)
    return data


def should_write_discovery_identity_update(
    *,
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
    now: datetime | None = None,
    update_interval: timedelta | None = None,
) -> bool:
    """Return whether an incoming discovery payload should be persisted."""
    if update_interval is None:
        update_interval = _DISCOVERY_LAST_SEEN_UPDATE_INTERVAL

    existing_values = dict(existing or {})
    incoming_values = dict(incoming or {})

    if _discoveries_without_last_seen(existing_values) != _discoveries_without_last_seen(
        incoming_values
    ):
        return True

    previous_seen = _discovery_timestamp_to_utc_datetime(
        normalize_discovery_timestamp(existing_values.get(CONF_DISCOVERY_LAST_SEEN))
    )
    next_seen = _discovery_timestamp_to_utc_datetime(
        normalize_discovery_timestamp(incoming_values.get(CONF_DISCOVERY_LAST_SEEN))
    )
    if previous_seen is None or next_seen is None:
        return True

    now_dt = now or datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.astimezone(UTC)
    if next_seen > now_dt:
        next_seen = now_dt

    return (next_seen - previous_seen) >= update_interval


def _discoveries_without_last_seen(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return metadata fields except the high-frequency last-seen timestamp."""
    metadata = dict(values)
    metadata.pop(CONF_DISCOVERY_LAST_SEEN, None)
    return metadata


def _discovery_timestamp_to_utc_datetime(
    value: str | None,
) -> datetime | None:
    """Return a timezone-aware UTC datetime from normalized string input."""
    if value is None:
        return None
    if value == "":
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def discovery_identity_conflicts_for_entry(entry: Any) -> tuple[str, ...]:
    """Return safe conflict codes for stored config-entry identity hints."""
    current = merged_entry_data_options(entry)
    conflicts = set(
        discovery_identity_conflict_codes(
            current.get(CONF_DISCOVERY_IDENTITY_CONFLICTS)
        )
    )
    conflicts.update(discovery_identity_conflicts_for_data(current))

    unique_id = str(getattr(entry, "unique_id", "") or "")
    unique_id_mac = discovery_mac_key(unique_id)
    discovery_mac = discovery_mac_key(current.get(CONF_DISCOVERY_MAC_ADDRESS))
    if unique_id_mac and discovery_mac and unique_id_mac != discovery_mac:
        conflicts.add("unique_id_discovery_mac_mismatch")

    return tuple(sorted(conflicts))


def discovery_identity_conflicts_for_data(data: dict[str, Any]) -> tuple[str, ...]:
    """Return safe conflict codes for one merged config identity mapping."""
    conflicts: set[str] = set()
    discovery_mac = discovery_mac_key(data.get(CONF_DISCOVERY_MAC_ADDRESS))
    wol_mac = discovery_mac_key(data.get(CONF_WOL_MAC_ADDRESS))
    if discovery_mac and wol_mac and discovery_mac != wol_mac:
        conflicts.add("discovery_mac_wol_mac_mismatch")
    return tuple(sorted(conflicts))


def discovery_timestamp(now: datetime | None = None) -> str:
    """Return an ISO UTC timestamp for discovery observations."""
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_discovery_timestamp(value: Any) -> str | None:
    """Return a normalized ISO UTC discovery timestamp."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _host_aliases_from_defaults(defaults: dict[str, Any] | None) -> set[str]:
    """Return normalized host aliases carried by discovery defaults."""
    aliases = (defaults or {}).get(CONF_DISCOVERY_HOST_ALIASES)
    if not isinstance(aliases, (list, tuple, set)):
        return set()
    return {alias for item in aliases if (alias := discovery_host_key(item))}


def discovery_identity_token(value: Any) -> str | None:
    """Return a diagnostics-safe identity source token."""
    if value in (None, ""):
        return None
    text = str(value).strip().lower().replace("-", "_")
    if not text or any(not (char.isalnum() or char == "_") for char in text):
        return None
    return text[:80]


def discovery_identity_conflict_codes(value: Any) -> tuple[str, ...]:
    """Return sanitized identity conflict codes."""
    if value in (None, ""):
        return ()
    values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
    conflicts = {
        conflict
        for item in values
        if (conflict := discovery_identity_token(item)) is not None
    }
    return tuple(sorted(conflicts))


def discovery_confidence_score(value: Any) -> int | None:
    """Return a bounded discovery confidence score."""
    try:
        confidence = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(confidence, 100))


def zeroconf_discovery_unique_id(device: Any) -> str:
    """Return the device fallback unique ID for zeroconf discoveries."""
    if mac_key := discovery_mac_key(getattr(device, "hw_addr", None)):
        return mac_key
    try:
        port = int(getattr(device, "port", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    host = discovery_host_key(getattr(device, "host", ""))
    return f"{host}:{port}"
