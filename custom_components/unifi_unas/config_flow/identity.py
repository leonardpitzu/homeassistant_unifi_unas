"""Config-flow identity and reconfigure guard helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import (
    CONF_WOL_ENABLED,
    CONF_WOL_MAC_ADDRESS,
    DOMAIN,
)

OFFLINE_SETUP_STATES = {"setup_error", "setup_retry"}


def _entry_info(
    data: dict[str, Any],
    *,
    unique_id: str | None = None,
    unique_ids: tuple[str, ...] = (),
    device_scoped_unique_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return config entry title and unique ID."""
    host = data[CONF_HOST].lower()
    port = int(data[CONF_PORT])
    resolved_unique_id = unique_id or f"{host}:{port}"
    resolved_unique_ids: list[str] = []
    for item in (resolved_unique_id, *unique_ids):
        if item in (None, ""):
            continue
        if item not in resolved_unique_ids:
            resolved_unique_ids.append(item)
    return {
        "title": f"UniFi Drive ({data[CONF_HOST]})",
        "unique_id": resolved_unique_id,
        "unique_ids": tuple(resolved_unique_ids),
        "device_scoped_unique_ids": tuple(
            item for item in device_scoped_unique_ids if item not in (None, "")
        ),
        "host": host,
        "port": port,
    }


def _entry_unique_id_matches(
    entry_unique_id: str | None,
    info: dict[str, Any],
) -> bool:
    """Return whether validation info matches an existing config entry ID."""
    if not entry_unique_id:
        return False
    device_scoped_ids = set(info.get("device_scoped_unique_ids") or ())
    if device_scoped_ids:
        return entry_unique_id in device_scoped_ids
    return entry_unique_id == info.get("unique_id")


def _entry_matches_validated_device(entry: Any, info: dict[str, Any]) -> bool:
    """Return whether validated connection info still points to the same entry."""
    entry_unique_id = getattr(entry, "unique_id", None)
    if not entry_unique_id:
        return False

    entry_unique_id = str(entry_unique_id)
    device_scoped_ids = set(info.get("device_scoped_unique_ids") or ())

    if entry_unique_id in device_scoped_ids:
        return True
    if not device_scoped_ids and entry_unique_id == info.get("unique_id"):
        return True
    return _entry_unique_id_matches_connection_fallback(entry_unique_id, entry, info)


def _feature_reconfigure_would_reload_offline_without_wol(
    hass: HomeAssistant,
    entry: Any,
    data: dict[str, Any],
) -> bool:
    """Return whether feature-only reconfigure would reload an offline entry unsafely."""
    if bool(data.get(CONF_WOL_ENABLED)) and data.get(CONF_WOL_MAC_ADDRESS):
        return False

    hass_data = getattr(hass, "data", {})
    if not isinstance(hass_data, dict):
        return False
    domain_data = hass_data.get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return False

    coordinator = getattr(entry, "runtime_data", None) or domain_data.get(
        getattr(entry, "entry_id", None)
    )
    if coordinator is None:
        return _entry_state_value(entry) in OFFLINE_SETUP_STATES
    return getattr(coordinator, "is_device_online", True) is False


def _entry_state_value(entry: Any) -> str:
    """Return a config-entry state value without depending on HA enum imports."""
    state = getattr(entry, "state", None)
    return str(getattr(state, "value", state)).lower()


def _any_unique_id_configured(hass: HomeAssistant, info: dict[str, Any]) -> bool:
    """Return whether any current device-scoped or legacy connection ID is configured."""
    device_scoped_ids = set(info.get("device_scoped_unique_ids") or ())
    unique_ids = device_scoped_ids or {info["unique_id"]}

    for entry in hass.config_entries.async_entries(DOMAIN):
        entry_unique_id = getattr(entry, "unique_id", None)
        if entry_unique_id in unique_ids:
            return True
        if entry_unique_id and _entry_unique_id_matches_connection_fallback(
            str(entry_unique_id),
            entry,
            info,
        ):
            return True

    return False


def _entry_unique_id_matches_connection_fallback(
    entry_unique_id: str,
    entry: Any,
    info: dict[str, Any],
) -> bool:
    """Return whether an old host:port entry ID matches the validated connection."""
    connection_unique_id = _connection_unique_id_from_info(info)
    if connection_unique_id is None:
        return False
    return (
        entry_unique_id.lower() == connection_unique_id
        and _entry_connection_matches_info(entry, info)
    )


def _connection_unique_id_from_info(info: dict[str, Any]) -> str | None:
    """Return the legacy host:port unique ID represented by validation info."""
    host = info.get("host")
    if not isinstance(host, str) or not host:
        return None
    port = _port_int_or_none(info.get("port"))
    if port is None:
        return None
    return f"{host.lower()}:{port}"


def _entry_connection_matches_info(entry: Any, info: dict[str, Any]) -> bool:
    """Return whether entry data points to the validated connection."""
    data = getattr(entry, "data", {})
    if not isinstance(data, dict):
        return False

    entry_host = data.get(CONF_HOST)
    info_host = info.get("host")
    if not isinstance(entry_host, str) or not isinstance(info_host, str):
        return False

    entry_port = _port_int_or_none(data.get(CONF_PORT))
    info_port = _port_int_or_none(info.get("port"))
    if entry_port is None or info_port is None:
        return False

    return entry_host.lower() == info_host.lower() and entry_port == info_port


def _port_int_or_none(value: object) -> int | None:
    """Return a config-flow port value as int when it has a supported shape."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
