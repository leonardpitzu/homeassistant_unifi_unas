"""Shared entity plumbing for the UniFi Drive / UNAS integration."""

from __future__ import annotations

from typing import NamedTuple

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnifiDriveCoordinator
from .models import Drive, Pool


class CurrentKeys(NamedTuple):
    """Unique-ID keys this version creates (used to prune old entities)."""

    device: frozenset[str]
    nested: frozenset[str]


CURRENT_KEYS = CurrentKeys(
    device=frozenset(
        {
            "overall_status",
            "at_risk_disk_count",
            "average_disk_temperature",
            "cache_status",
            "ssd_wear",
            "usage_percent",
            "cpu_temperature",
            "cpu_percent",
            "memory_percent",
            "system_uptime_readable",
            "read_throughput",
            "write_throughput",
            "device_online",
            "storage_problem",
            "fan_mode",
            "reboot",
            "shutdown",
            "wake_on_lan",
        }
    ),
    nested=frozenset(
        {
            "pool_status",
            "pool_at_risk_drive_count",
            "pool_rebuild_progress",
            "pool_capacity",
            "pool_used",
            "pool_available",
            "pool_problem",
            "drive_status",
            "drive_temperature",
            "drive_power_on_hours",
            "drive_life_span",
            "drive_capacity",
            "drive_bad_sectors",
            "drive_uncorrectable_sectors",
        }
    ),
)


class UnifiDriveEntity(CoordinatorEntity[UnifiDriveCoordinator]):
    """Base entity bound to the console device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnifiDriveCoordinator, key: str) -> None:
        """Initialize with a unique-ID key below the device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            manufacturer="Ubiquiti",
            name=coordinator.config_entry.title,
            configuration_url=coordinator.client.url,
        )
        # Only set what is known: a None here would wipe the registry value
        # when the NAS is off at startup.
        if (data := coordinator.data) is not None:
            if data.model:
                self._attr_device_info["model"] = data.model
            if data.sw_version:
                self._attr_device_info["sw_version"] = data.sw_version


class PoolEntity(UnifiDriveEntity):
    """Entity bound to one storage pool."""

    def __init__(self, coordinator: UnifiDriveCoordinator, pool: Pool, key: str, label: str) -> None:
        """Initialize for ``pool``."""
        super().__init__(coordinator, f"{pool.key}_{key}")
        self._pool_key = pool.key
        self._attr_name = f"{pool.name} {label}"

    @property
    def pool(self) -> Pool | None:
        """Return this pool in the current snapshot."""
        return self.coordinator.data.pools.get(self._pool_key)

    @property
    def available(self) -> bool:
        """Unavailable when the pool vanished from the payload."""
        return super().available and self.pool is not None


class DriveEntity(UnifiDriveEntity):
    """Entity bound to one drive."""

    def __init__(self, coordinator: UnifiDriveCoordinator, drive: Drive, key: str, label: str) -> None:
        """Initialize for ``drive``."""
        super().__init__(coordinator, f"{drive.key}_{key}")
        self._drive_key = drive.key
        self._attr_name = f"{drive.group_name} {drive.name} {label}"

    @property
    def drive(self) -> Drive | None:
        """Return this drive in the current snapshot."""
        return self.coordinator.data.drives.get(self._drive_key)

    @property
    def available(self) -> bool:
        """Unavailable when the drive vanished from the payload."""
        return super().available and self.drive is not None
