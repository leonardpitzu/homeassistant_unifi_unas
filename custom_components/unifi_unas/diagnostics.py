"""Diagnostics for the UniFi Drive / UNAS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_WOL_MAC
from .coordinator import UnifiDriveConfigEntry

TO_REDACT = {
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_WOL_MAC,
    "address",
    "mac",
    "serial",
    "fabricId",
    "fabricName",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: UnifiDriveConfigEntry) -> dict[str, Any]:
    """Return the entry and the last raw API responses, redacted."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data({"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "raw": async_redact_data(coordinator.raw, TO_REDACT),
    }
