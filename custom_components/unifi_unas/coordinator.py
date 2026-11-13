"""Polling coordinator for the UniFi Drive / UNAS integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnect, InvalidAuth, UnifiDriveClient, UnifiDriveError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import UnasData, parse

_LOGGER = logging.getLogger(__name__)

type UnifiDriveConfigEntry = ConfigEntry[UnifiDriveCoordinator]


class UnifiDriveCoordinator(DataUpdateCoordinator[UnasData]):
    """Fetch every endpoint once per poll and parse it into one snapshot."""

    config_entry: UnifiDriveConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UnifiDriveConfigEntry, client: UnifiDriveClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.device_id = entry.unique_id or entry.entry_id
        # Same rule as the client: a local account wins over an API key.
        self.has_account = bool(str(entry.data.get(CONF_USERNAME) or "").strip() and entry.data.get(CONF_PASSWORD))
        # Last raw responses, kept for diagnostics only.
        self.raw: dict[str, Any] = {}
        self._failures = 0

    async def _async_update_data(self) -> UnasData:
        try:
            storage, device_info, network_io, fan = await asyncio.gather(
                self.client.async_get_storage(),
                self._optional(self.client.async_get_device_info()),
                self._optional(self.client.async_get_network_io()),
                self._optional(self.client.async_get_fan_control()),
            )
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CannotConnect as err:
            # Ride out a single blip on the last good snapshot so one dropped
            # request does not flap every entity through "unavailable".
            self._failures += 1
            if self._failures == 1 and self.data is not None:
                _LOGGER.debug("Poll failed once, keeping last data: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err

        self._failures = 0
        self.raw = {"storage": storage, "device_info": device_info, "network_io": network_io, "fan": fan}
        data = parse(storage, device_info, network_io, fan)
        self._sync_device_versions(data)
        return data

    @staticmethod
    async def _optional(request: Any) -> dict[str, Any] | None:
        """Await a secondary endpoint; its failure must not fail the poll."""
        try:
            result: dict[str, Any] = await request
        except UnifiDriveError:
            return None
        return result

    def _sync_device_versions(self, data: UnasData) -> None:
        """Keep the device's firmware version current after updates."""
        if not (version := data.sw_version):
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier((DOMAIN, self.device_id), self.config_entry.entry_id)
        if device is not None and device.sw_version != version:
            registry.async_update_device(device.id, sw_version=version)
