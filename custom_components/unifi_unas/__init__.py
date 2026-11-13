"""The UniFi Drive / UNAS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UnifiDriveClient, base_url
from .const import CONF_WOL_BROADCAST, CONF_WOL_MAC, CONF_WOL_PORT, PLATFORMS
from .coordinator import UnifiDriveConfigEntry, UnifiDriveCoordinator
from .entity import CURRENT_KEYS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: UnifiDriveConfigEntry) -> bool:
    """Set up a UniFi Drive console from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, False)
    client = UnifiDriveClient(
        async_get_clientsession(hass, verify_ssl=verify_ssl),
        base_url(entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_SSL]),
        api_key=entry.data.get(CONF_API_KEY),
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        verify_ssl=verify_ssl,
    )
    coordinator = UnifiDriveCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # A powered-off NAS is expected when Wake-on-LAN is configured: set up
        # anyway so the Start button exists; data entities follow once it is up.
        if CONF_WOL_MAC not in entry.options:
            raise
        _LOGGER.info("UniFi Drive is unreachable; continuing for Wake-on-LAN")
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UnifiDriveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: UnifiDriveConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 entries (upstream layout) to the lean v2 layout.

    Drops discovery/snapshot/feature-flag keys, carries Wake-on-LAN over only
    when it was enabled, lets the old 30 s default poll fall back to the new
    default, and removes registry entries for entities v2 no longer provides.
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        data_keys = (CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL, CONF_API_KEY, CONF_USERNAME, CONF_PASSWORD)
        data = {k: entry.data[k] for k in data_keys if k in entry.data}
        old = {**entry.data, **entry.options}
        options = {k: old[k] for k in (CONF_SCAN_INTERVAL, CONF_WOL_BROADCAST, CONF_WOL_PORT) if k in old}
        if old.get(CONF_SCAN_INTERVAL) == 30:
            options.pop(CONF_SCAN_INTERVAL)
        if old.get("wol_enabled") and old.get(CONF_WOL_MAC):
            options[CONF_WOL_MAC] = old[CONF_WOL_MAC]

        registry = er.async_get(hass)
        prefix = f"{entry.unique_id or entry.entry_id}_"
        removed = 0
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if not _is_current_unique_id(reg_entry.unique_id.removeprefix(prefix)):
                registry.async_remove(reg_entry.entity_id)
                removed += 1
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
        _LOGGER.info("Migrated UniFi Drive entry to v2, removed %s obsolete entities", removed)
    return True


# v1 pool/drive keys that v2 dropped. Needed because some end in a current key
# (``pool_average_drive_temperature`` ends in ``drive_temperature``).
_V1_NESTED_KEYS = frozenset(
    {
        "pool_average_drive_temperature",
        "pool_drive_count",
        "pool_maintenance_active",
        "pool_raid_level",
        "pool_sync_progress",
        "pool_usage_percent",
        "drive_model",
    }
)


def _is_current_unique_id(suffix: str) -> bool:
    """Return whether a unique-ID suffix belongs to an entity v2 still creates.

    Device-level keys must match exactly; pool and drive keys end
    ``<pool>_<key>`` / ``<group>_<drive>_<key>``, and the longest matching key
    decides. Only cache SSDs report a remaining life, so HDD life-span entities
    (always unknown) are dropped.
    """
    if suffix in CURRENT_KEYS.device:
        return True
    matches = [key for key in CURRENT_KEYS.nested | _V1_NESTED_KEYS if suffix.endswith(f"_{key}")]
    if not matches:
        return False
    key = max(matches, key=len)
    if key == "drive_life_span":
        return suffix.startswith("cache_")
    return key in CURRENT_KEYS.nested
