"""Sensors for the UniFi Drive / UNAS integration.

Recorder cost matters here: only values worth a long-term trend carry a
``state_class``, and the few attributes are static per drive/pool, so a
poll only writes rows for states that actually changed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import UnifiDriveConfigEntry, UnifiDriveCoordinator
from .entity import DriveEntity, PoolEntity, UnifiDriveEntity
from .models import Drive, Pool, UnasData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class UnasSensorDescription[T](SensorEntityDescription):
    """Sensor description reading one value from a snapshot object."""

    value_fn: Callable[[T], StateType]
    attrs_fn: Callable[[T], dict[str, Any]] | None = None
    label: str = ""


_TEMPERATURE: dict[str, Any] = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    "state_class": SensorStateClass.MEASUREMENT,
}
_GIB: dict[str, Any] = {
    "device_class": SensorDeviceClass.DATA_SIZE,
    "native_unit_of_measurement": UnitOfInformation.GIBIBYTES,
    "suggested_display_precision": 2,
}
_THROUGHPUT: dict[str, Any] = {
    "device_class": SensorDeviceClass.DATA_RATE,
    "native_unit_of_measurement": UnitOfDataRate.MEGABYTES_PER_SECOND,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 2,
    "entity_category": EntityCategory.DIAGNOSTIC,
}

DEVICE_SENSORS: tuple[UnasSensorDescription[UnasData], ...] = (
    UnasSensorDescription(key="overall_status", translation_key="overall_status", value_fn=lambda d: d.overall_status),
    UnasSensorDescription(
        key="at_risk_disk_count", translation_key="at_risk_disk_count", value_fn=lambda d: d.at_risk_disk_count
    ),
    UnasSensorDescription(
        key="average_disk_temperature",
        translation_key="average_disk_temperature",
        suggested_display_precision=1,
        value_fn=lambda d: d.average_disk_temperature,
        **_TEMPERATURE,
    ),
    UnasSensorDescription(key="cache_status", translation_key="cache_status", value_fn=lambda d: d.cache_status),
    UnasSensorDescription(
        key="ssd_wear",
        translation_key="ssd_wear",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.ssd_wear,
    ),
    UnasSensorDescription(
        key="usage_percent",
        translation_key="usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.usage_percent,
    ),
    UnasSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        suggested_display_precision=0,
        value_fn=lambda d: d.cpu_temperature,
        **_TEMPERATURE,
    ),
    UnasSensorDescription(
        key="cpu_percent",
        translation_key="cpu_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.cpu_percent,
    ),
    UnasSensorDescription(
        key="memory_percent",
        translation_key="memory_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.memory_percent,
    ),
    UnasSensorDescription(
        key="system_uptime_readable",
        translation_key="uptime",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.uptime,
    ),
    UnasSensorDescription(
        key="read_throughput", translation_key="read_throughput", value_fn=lambda d: d.read_mb_s, **_THROUGHPUT
    ),
    UnasSensorDescription(
        key="write_throughput", translation_key="write_throughput", value_fn=lambda d: d.write_mb_s, **_THROUGHPUT
    ),
)

POOL_SENSORS: tuple[UnasSensorDescription[Pool], ...] = (
    UnasSensorDescription(
        key="pool_status",
        label="Status",
        value_fn=lambda p: p.status,
        attrs_fn=lambda p: {"raw_status": p.raw_status},
    ),
    UnasSensorDescription(
        key="pool_at_risk_drive_count", label="At-Risk Drive Count", value_fn=lambda p: p.at_risk_drive_count
    ),
    UnasSensorDescription(
        key="pool_rebuild_progress",
        label="Rebuild Progress",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda p: p.rebuild_progress,
    ),
    UnasSensorDescription(key="pool_capacity", label="Capacity", value_fn=lambda p: p.capacity_gib, **_GIB),
    UnasSensorDescription(key="pool_used", label="Used", value_fn=lambda p: p.used_gib, **_GIB),
    UnasSensorDescription(key="pool_available", label="Available", value_fn=lambda p: p.available_gib, **_GIB),
)

DRIVE_SENSORS: tuple[UnasSensorDescription[Drive], ...] = (
    UnasSensorDescription(
        key="drive_status",
        label="Status",
        value_fn=lambda d: d.status,
        attrs_fn=lambda d: {
            "raw_health": d.raw_health,
            "media_type": d.media_type,
            "model": d.model,
            "firmware": d.firmware,
        },
    ),
    UnasSensorDescription(key="drive_temperature", label="Temperature", value_fn=lambda d: d.temperature, **_TEMPERATURE),
    UnasSensorDescription(
        key="drive_power_on_hours",
        label="Power-On Hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.power_on_hours,
    ),
    UnasSensorDescription(
        key="drive_life_span",
        label="Remaining Life",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.life_span,
    ),
    UnasSensorDescription(
        key="drive_capacity",
        label="Capacity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.capacity_gib,
        **_GIB,
    ),
    UnasSensorDescription(
        key="drive_bad_sectors",
        label="Bad Sectors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.bad_sectors,
    ),
    UnasSensorDescription(
        key="drive_uncorrectable_sectors",
        label="Uncorrectable Sectors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.uncorrectable_sectors,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors; pool and drive sensors appear as the payload shows them."""
    coordinator = entry.runtime_data
    async_add_entities(DeviceSensor(coordinator, desc) for desc in DEVICE_SENSORS)
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        if (data := coordinator.data) is None:
            return
        entities: list[SensorEntity] = []
        for pool in data.pools.values():
            if pool.key not in known:
                known.add(pool.key)
                entities.extend(PoolSensor(coordinator, pool, desc) for desc in POOL_SENSORS)
        for drive in data.drives.values():
            if drive.key not in known:
                known.add(drive.key)
                entities.extend(
                    DriveSensor(coordinator, drive, desc)
                    for desc in DRIVE_SENSORS
                    if desc.key != "drive_life_span" or drive.life_span is not None
                )
        if entities:
            async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class DeviceSensor(UnifiDriveEntity, SensorEntity):
    """Console-level sensor."""

    entity_description: UnasSensorDescription[UnasData]

    def __init__(self, coordinator: UnifiDriveCoordinator, description: UnasSensorDescription[UnasData]) -> None:
        """Initialize."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value from the current snapshot."""
        return self.entity_description.value_fn(self.coordinator.data)


class PoolSensor(PoolEntity, SensorEntity):
    """Per-pool sensor."""

    entity_description: UnasSensorDescription[Pool]

    def __init__(self, coordinator: UnifiDriveCoordinator, pool: Pool, description: UnasSensorDescription[Pool]) -> None:
        """Initialize."""
        super().__init__(coordinator, pool, description.key, description.label)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value for this pool."""
        return self.entity_description.value_fn(pool) if (pool := self.pool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return static pool attributes, if any."""
        if (fn := self.entity_description.attrs_fn) and (pool := self.pool):
            return fn(pool)
        return None


class DriveSensor(DriveEntity, SensorEntity):
    """Per-drive sensor."""

    entity_description: UnasSensorDescription[Drive]

    def __init__(
        self, coordinator: UnifiDriveCoordinator, drive: Drive, description: UnasSensorDescription[Drive]
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, drive, description.key, description.label)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value for this drive."""
        return self.entity_description.value_fn(drive) if (drive := self.drive) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return static drive attributes, if any."""
        if (fn := self.entity_description.attrs_fn) and (drive := self.drive):
            return fn(drive)
        return None
