"""Assembled sensor description tables for the UniFi Drive integration.

Each description lives next to the helper that produces its value, in the
`storage_*` module that owns that data. This module only stitches those
registries together in the order the entities should be created.
"""

from __future__ import annotations

from .sensor_types import (
    AggregateSensorDescription,
    DriveSensorDescription,
    PoolSensorDescription,
)
from .storage import (
    capacity as storage_capacity,
)
from .storage import (
    drives as storage_drives,
)
from .storage import (
    pools as storage_pools,
)
from .storage import (
    system as storage_system,
)
from .storage import (
    throughput as storage_throughput,
)

AGGREGATE_SENSOR_TYPES: tuple[AggregateSensorDescription, ...] = (
    *storage_throughput.AGGREGATE_SENSORS,
    *storage_capacity.AGGREGATE_SENSORS,
    *storage_pools.AGGREGATE_SENSORS,
    *storage_system.AGGREGATE_SENSORS,
)

POOL_SENSOR_TYPES: tuple[PoolSensorDescription, ...] = (
    *storage_pools.POOL_SENSORS,
    *storage_capacity.POOL_SENSORS,
)

DRIVE_SENSOR_TYPES: tuple[DriveSensorDescription, ...] = storage_drives.DRIVE_SENSORS

__all__ = [
    "AGGREGATE_SENSOR_TYPES",
    "DRIVE_SENSOR_TYPES",
    "POOL_SENSOR_TYPES",
    "AggregateSensorDescription",
    "DriveSensorDescription",
    "PoolSensorDescription",
]
