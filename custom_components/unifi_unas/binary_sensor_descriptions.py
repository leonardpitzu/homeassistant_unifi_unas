"""Assembled binary-sensor description tables for the UniFi Drive integration.

Descriptions backed by storage data live next to their helpers in
`storage_pools`. Only `device_online` is declared here: it has no storage
helper, because the platform reads connectivity straight off the coordinator.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from .sensor_types import (
    AggregateBinarySensorDescription,
    PoolBinarySensorDescription,
)
from .storage import pools as storage_pools

_DEVICE_ONLINE = AggregateBinarySensorDescription(
    key="device_online",
    translation_key="device_online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    value_fn=lambda data: True,
)

AGGREGATE_BINARY_SENSOR_TYPES: tuple[AggregateBinarySensorDescription, ...] = (
    _DEVICE_ONLINE,
    *storage_pools.AGGREGATE_BINARY_SENSORS,
)

POOL_BINARY_SENSOR_TYPES: tuple[PoolBinarySensorDescription, ...] = (
    storage_pools.POOL_BINARY_SENSORS
)

__all__ = [
    "AGGREGATE_BINARY_SENSOR_TYPES",
    "POOL_BINARY_SENSOR_TYPES",
    "AggregateBinarySensorDescription",
    "PoolBinarySensorDescription",
]
