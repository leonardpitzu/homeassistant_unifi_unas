"""Storage capacity and usage helper functions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfInformation

from .sensor_types import AggregateSensorDescription, PoolSensorDescription
from .storage_common import _bytes_to_gib, _dict_values, _first_number, _percentage, _sum_known
from .storage_pools import _pools

CAPACITY_KEYS = (
    "capacity",
    "total",
    "totalBytes",
    "totalSize",
    "totalCapacity",
    "capacityBytes",
    "size",
    "usableCapacity",
    "usableSize",
    "volumeSize",
)
USAGE_KEYS = (
    "usage",
    "used",
    "usedBytes",
    "usedSize",
    "usedCapacity",
    "usedSpace",
    "usedSpaceBytes",
    "usedStorage",
)
AVAILABLE_KEYS = (
    "available",
    "availableBytes",
    "availableSize",
    "availableCapacity",
    "free",
    "freeBytes",
    "freeSize",
    "freeSpace",
    "freeSpaceBytes",
    "remaining",
    "remainingBytes",
)
AGGREGATE_CAPACITY_KEYS = (
    "totalStorage",
    "totalStorageBytes",
    "storageTotalBytes",
    "storageTotal",
)
AGGREGATE_USAGE_KEYS = (
    "usedStorage",
    "usedStorageBytes",
    "storageUsedBytes",
    "storageUsed",
)
AGGREGATE_AVAILABLE_KEYS = (
    "availableStorage",
    "availableStorageBytes",
    "storageAvailableBytes",
    "storageAvailable",
)
STORAGE_CONTAINER_KEYS = (
    "storage",
    "capacity",
    "summary",
    "stats",
    "space",
    "volume",
    "usage",
)


def _storage_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return a storage number from direct or common nested payload containers."""
    direct = _first_number(data, keys)
    if direct is not None:
        return direct

    for nested in _dict_values(data, STORAGE_CONTAINER_KEYS):
        value = _first_number(nested, keys)
        if value is not None:
            return value
    return None


def _aggregate_storage_number(
    data: dict[str, Any],
    *,
    aggregate_keys: tuple[str, ...],
) -> float | None:
    """Return aggregate storage bytes without using generic root metadata keys."""
    direct = _first_number(data, aggregate_keys)
    if direct is not None:
        return direct

    for nested in _dict_values(data, STORAGE_CONTAINER_KEYS):
        value = _first_number(nested, aggregate_keys)
        if value is not None:
            return value
    return None


def _pool_capacity(pool: dict[str, Any]) -> float | None:
    """Return pool capacity in bytes."""
    return _storage_number(pool, CAPACITY_KEYS)


def _pool_usage(pool: dict[str, Any]) -> float | None:
    """Return pool usage in bytes."""
    direct_usage = _storage_number(pool, USAGE_KEYS)
    if direct_usage is not None:
        return direct_usage

    capacity = _pool_capacity(pool)
    available = _storage_number(pool, AVAILABLE_KEYS)
    if capacity is None or available is None:
        return None
    return max(0.0, capacity - available)


def _pool_available(pool: dict[str, Any]) -> float | None:
    """Return pool available capacity in bytes."""
    direct_available = _storage_number(pool, AVAILABLE_KEYS)
    if direct_available is not None:
        return direct_available

    capacity = _pool_capacity(pool)
    usage = _storage_number(pool, USAGE_KEYS)
    if capacity is None or usage is None:
        return None
    return max(0.0, capacity - usage)


def _aggregate_capacity(data: dict[str, Any]) -> float | None:
    """Return aggregate capacity in bytes."""
    direct = _aggregate_storage_number(
        data,
        aggregate_keys=AGGREGATE_CAPACITY_KEYS,
    )
    if direct is not None:
        return direct

    values = [_pool_capacity(pool) for pool in _pools(data)]
    return _sum_known(values)


def _aggregate_usage(data: dict[str, Any]) -> float | None:
    """Return aggregate usage in bytes."""
    direct = _aggregate_storage_number(
        data,
        aggregate_keys=AGGREGATE_USAGE_KEYS,
    )
    if direct is not None:
        return direct

    values = [_pool_usage(pool) for pool in _pools(data)]
    return _sum_known(values)


def _aggregate_available(data: dict[str, Any]) -> float | None:
    """Return aggregate available capacity in bytes."""
    direct = _aggregate_storage_number(
        data,
        aggregate_keys=AGGREGATE_AVAILABLE_KEYS,
    )
    if direct is not None:
        return direct

    values = [_pool_available(pool) for pool in _pools(data)]
    summed_available = _sum_known(values)
    if summed_available is not None:
        return summed_available

    capacity = _aggregate_capacity(data)
    usage = _aggregate_usage(data)
    if capacity is None or usage is None:
        return None
    return max(0.0, capacity - usage)


AGGREGATE_SENSORS: tuple[AggregateSensorDescription, ...] = (
    AggregateSensorDescription(
        key="total_storage",
        translation_key="total_storage",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: _bytes_to_gib(_aggregate_capacity(data)),
    ),
    AggregateSensorDescription(
        key="used_storage",
        translation_key="used_storage",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: _bytes_to_gib(_aggregate_usage(data)),
    ),
    AggregateSensorDescription(
        key="available_storage",
        translation_key="available_storage",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: _bytes_to_gib(_aggregate_available(data)),
    ),
    AggregateSensorDescription(
        key="usage_percent",
        translation_key="usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: _percentage(_aggregate_usage(data), _aggregate_capacity(data)),
    ),
)

POOL_SENSORS: tuple[PoolSensorDescription, ...] = (
    PoolSensorDescription(
        key="pool_capacity",
        name="Capacity",
        translation_key="pool_capacity",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda pool: _bytes_to_gib(_pool_capacity(pool)),
    ),
    PoolSensorDescription(
        key="pool_used",
        name="Used",
        translation_key="pool_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda pool: _bytes_to_gib(_pool_usage(pool)),
    ),
    PoolSensorDescription(
        key="pool_available",
        name="Available",
        translation_key="pool_available",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda pool: _bytes_to_gib(_pool_available(pool)),
    ),
    PoolSensorDescription(
        key="pool_usage_percent",
        name="Usage",
        translation_key="pool_usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda pool: _percentage(_pool_usage(pool), _pool_capacity(pool)),
    ),
)
