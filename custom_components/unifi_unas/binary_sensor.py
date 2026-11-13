"""Binary sensors for the UniFi Drive / UNAS integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UnifiDriveConfigEntry, UnifiDriveCoordinator
from .entity import PoolEntity, UnifiDriveEntity
from .models import Pool

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities([OnlineSensor(coordinator), StorageProblemSensor(coordinator)])
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        if (data := coordinator.data) is None:
            return
        new = [pool for key, pool in data.pools.items() if key not in known]
        known.update(pool.key for pool in new)
        if new:
            async_add_entities(PoolProblemSensor(coordinator, pool) for pool in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class OnlineSensor(UnifiDriveEntity, BinarySensorEntity):
    """Whether the console answers; stays available to report ``off``."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "device_online"

    def __init__(self, coordinator: UnifiDriveCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "device_online")

    @property
    def available(self) -> bool:
        """Always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the last poll succeeded."""
        return self.coordinator.last_update_success


class StorageProblemSensor(UnifiDriveEntity, BinarySensorEntity):
    """Any pool or the cache degraded, or any drive at risk."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "storage_problem"

    def __init__(self, coordinator: UnifiDriveCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "storage_problem")

    @property
    def is_on(self) -> bool:
        """Return whether storage needs attention."""
        return self.coordinator.data.storage_problem


class PoolProblemSensor(PoolEntity, BinarySensorEntity):
    """The pool is degraded or has a drive at risk."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: UnifiDriveCoordinator, pool: Pool) -> None:
        """Initialize."""
        super().__init__(coordinator, pool, "pool_problem", "Problem")

    @property
    def is_on(self) -> bool | None:
        """Return whether this pool needs attention."""
        return pool.problem if (pool := self.pool) else None
