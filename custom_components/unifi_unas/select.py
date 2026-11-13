"""Fan profile select for the UniFi Drive / UNAS integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import UnifiDriveError
from .const import FAN_PROFILES
from .coordinator import UnifiDriveConfigEntry, UnifiDriveCoordinator
from .entity import UnifiDriveEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fan profile select."""
    async_add_entities([FanModeSelect(entry.runtime_data)])


class FanModeSelect(UnifiDriveEntity, SelectEntity):
    """Native UniFi Drive fan profile."""

    _attr_translation_key = "fan_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(FAN_PROFILES)

    def __init__(self, coordinator: UnifiDriveCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "fan_mode")

    @property
    def available(self) -> bool:
        """Unavailable when the fan profile could not be read."""
        return super().available and self.coordinator.data.fan_mode is not None

    @property
    def current_option(self) -> str | None:
        """Return the active profile."""
        return self.coordinator.data.fan_mode

    async def async_select_option(self, option: str) -> None:
        """Apply a profile and refresh."""
        try:
            await self.coordinator.client.async_set_fan_profile(FAN_PROFILES[option])
        except UnifiDriveError as err:
            raise HomeAssistantError(f"Could not set the fan profile: {err}") from err
        await self.coordinator.async_request_refresh()
