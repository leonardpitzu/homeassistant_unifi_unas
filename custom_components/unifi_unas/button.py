"""Power buttons for the UniFi Drive / UNAS integration."""

from __future__ import annotations

import asyncio
import socket

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import InvalidAuth, UnifiDriveError
from .const import CONF_WOL_BROADCAST, CONF_WOL_MAC, CONF_WOL_PORT, DEFAULT_WOL_BROADCAST, DEFAULT_WOL_PORT
from .coordinator import UnifiDriveConfigEntry, UnifiDriveCoordinator
from .entity import UnifiDriveEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up restart / shut down and, when configured, Wake-on-LAN."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        PowerButton(coordinator, "reboot", "restart", ButtonDeviceClass.RESTART),
        PowerButton(coordinator, "shutdown", "shutdown", None),
    ]
    if mac := entry.options.get(CONF_WOL_MAC):
        entities.append(
            WakeOnLanButton(
                coordinator,
                mac,
                entry.options.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST),
                entry.options.get(CONF_WOL_PORT, DEFAULT_WOL_PORT),
            )
        )
    async_add_entities(entities)


class PowerButton(UnifiDriveEntity, ButtonEntity):
    """Restart or power off the console (needs a local account, not an API key)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: UnifiDriveCoordinator,
        key: str,
        translation_key: str,
        device_class: ButtonDeviceClass | None,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, key)
        self._attr_translation_key = translation_key
        self._attr_device_class = device_class
        self._action = coordinator.client.async_reboot if key == "reboot" else coordinator.client.async_poweroff

    async def async_press(self) -> None:
        """Send the power action."""
        try:
            await self._action()
        except InvalidAuth as err:
            raise HomeAssistantError(
                "The UniFi account is not allowed to do this (API keys cannot; use a local admin account)"
            ) from err
        except UnifiDriveError as err:
            raise HomeAssistantError(f"UniFi Drive power action failed: {err}") from err


class WakeOnLanButton(UnifiDriveEntity, ButtonEntity):
    """Send a magic packet; available while the console is off."""

    _attr_translation_key = "wake_on_lan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: UnifiDriveCoordinator, mac: str, broadcast: str, port: int) -> None:
        """Initialize."""
        super().__init__(coordinator, "wake_on_lan")
        self._packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
        self._target = (broadcast, port)

    @property
    def available(self) -> bool:
        """Always available: waking a powered-off NAS is the point."""
        return True

    async def async_press(self) -> None:
        """Broadcast the magic packet a few times."""
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol, family=socket.AF_INET, allow_broadcast=True
            )
        except OSError as err:
            raise HomeAssistantError(f"Could not open a UDP socket: {err}") from err
        try:
            for _ in range(3):
                transport.sendto(self._packet, self._target)
                await asyncio.sleep(0.05)
        except OSError as err:
            raise HomeAssistantError(f"Could not send the Wake-on-LAN packet: {err}") from err
        finally:
            transport.close()
