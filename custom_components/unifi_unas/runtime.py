"""Runtime-data typing and helpers for the UniFi Drive integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import UnifiUnasCoordinator

# PEP 695 aliases evaluate lazily, so the coordinator stays a type-only import.
type UnifiDriveConfigEntry = ConfigEntry[UnifiUnasCoordinator]


def coordinator_from_entry(entry: UnifiDriveConfigEntry) -> UnifiUnasCoordinator:
    """Return the loaded coordinator stored on ConfigEntry.runtime_data."""
    return entry.runtime_data


def coordinator_from_entry_or_none(
    entry: UnifiDriveConfigEntry | None,
) -> UnifiUnasCoordinator | None:
    """Return the loaded coordinator if runtime data is available."""
    if entry is None:
        return None

    coordinator = getattr(entry, "runtime_data", None)
    if _looks_like_unifi_unas_coordinator(coordinator):
        return cast("UnifiUnasCoordinator", coordinator)
    return None


def _looks_like_unifi_unas_coordinator(value: object) -> bool:
    """Return whether runtime data has the coordinator surface used by support paths."""
    return all(
        hasattr(value, attr)
        for attr in (
            "client",
            "data",
            "is_device_online",
            "last_update_success",
        )
    )
