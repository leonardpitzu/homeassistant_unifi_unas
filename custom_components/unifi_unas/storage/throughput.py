"""Throughput extraction helper functions."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorStateClass

from .sensor_types import AggregateSensorDescription
from .storage_common import _first_number, _text
from .system_metadata import normalized_token as _normalized_token

THROUGHPUT_DISK_LIST_KEYS = ("disks", "drives", "hdds")
THROUGHPUT_CONTAINER_KEYS = ("storage", "storageInfo", "storage_info", "data", "result")


def _read_throughput_mb_s(data: dict[str, Any]) -> float | None:
    """Return read throughput in MB/s."""
    return _throughput_mb_s(data, direction="read")


def _write_throughput_mb_s(data: dict[str, Any]) -> float | None:
    """Return write throughput in MB/s."""
    return _throughput_mb_s(data, direction="write")


def _throughput_mb_s(data: dict[str, Any], *, direction: str) -> float | None:
    """Extract throughput and normalize to MB/s."""
    key_hints = _throughput_key_hints(direction)
    unit_hints = _throughput_unit_hints()
    result = _throughput_value_from_nested(data, key_hints, unit_hints)
    disk_result = _throughput_from_disks_mb_s(data, direction=direction)
    result = _prefer_non_zero_throughput(result, disk_result)
    return round(result, 2) if result is not None else None


def _throughput_unit_hints() -> dict[str, float]:
    """Return supported throughput unit multipliers."""
    return {
        "B/s": 1 / (1000 * 1000),
        "KB/s": 1 / 1000,
        "KiB/s": 1024 / (1000 * 1000),
        "MB/s": 1.0,
        "MiB/s": 1024 * 1024 / (1000 * 1000),
        "GB/s": 1000.0,
        "GiB/s": (1024 * 1024 * 1024) / (1000 * 1000),
    }


def _throughput_value_from_nested(
    data: Any,
    key_hints: tuple[str, ...],
    unit_hints: dict[str, float],
) -> float | None:
    """Search nested mappings and lists for throughput values."""
    return _prefer_non_zero_throughput(
        *_throughput_values_from_nested(data, key_hints, unit_hints),
    )


def _throughput_values_from_nested(
    data: Any,
    key_hints: tuple[str, ...],
    unit_hints: dict[str, float],
) -> list[float]:
    """Return nested throughput candidates in payload order."""
    values: list[float] = []
    if isinstance(data, dict):
        for key, child in data.items():
            key_text = str(key)
            norm = _normalized_token(key_text)
            parsed = _throughput_value_from_mapping_hints(
                key_hints,
                norm,
                child,
                unit_hints,
            )
            if parsed is not None:
                values.append(parsed)

            if norm in {"disks", "drives"} and isinstance(child, list):
                continue

            values.extend(
                _throughput_values_from_nested(
                    child,
                    key_hints,
                    unit_hints,
                )
            )
        return values

    if isinstance(data, list):
        for item in data:
            values.extend(
                _throughput_values_from_nested(
                    data=item,
                    key_hints=key_hints,
                    unit_hints=unit_hints,
                )
            )
    return values


def _prefer_non_zero_throughput(*values: float | None) -> float | None:
    """Return the first non-zero throughput, preserving zero as a valid idle state."""
    first_zero: float | None = None
    for value in values:
        if value is None:
            continue
        if value != 0:
            return value
        if first_zero is None:
            first_zero = value
    return first_zero


def _throughput_value_from_mapping_hints(
    key_hints: tuple[str, ...],
    key_norm: str,
    value: Any,
    unit_hints: dict[str, float],
) -> float | None:
    """Parse nested field if the key matches throughput hints."""
    if any(hint in key_norm for hint in key_hints):
        return _parse_throughput_value(value, unit_hints, key_norm=key_norm)
    return None


def _throughput_key_hints(direction: str) -> tuple[str, ...]:
    """Return normalized key hints for throughput extraction."""
    if direction == "read":
        return (
            "readthroughput",
            "readspeed",
            "readrate",
            "readbandwidth",
            "readmbps",
            "readmibs",
            "readkbps",
            "rxspeed",
            "rxrate",
            "rxthroughput",
            "networkread",
            "transmitkbps",
        )
    return (
        "writethroughput",
        "writespeed",
        "writerate",
        "writebandwidth",
        "writembps",
        "writemibs",
        "writekbps",
        "txspeed",
        "txrate",
        "txthroughput",
        "networkwrite",
        "receivekbps",
    )


def _parse_throughput_value(
    value: Any,
    unit_hints: dict[str, float],
    *,
    key_norm: str = "",
) -> float | None:
    """Parse numeric or structured throughput value and return MB/s."""
    if isinstance(value, (int, float)):
        return _parse_throughput_numeric(float(value), key_norm=key_norm)
    if isinstance(value, str):
        return _parse_throughput_string(value, key_norm=key_norm, unit_hints=unit_hints)
    if isinstance(value, dict):
        return _parse_throughput_dict(value, key_norm=key_norm, unit_hints=unit_hints)
    return None


def _parse_throughput_numeric(value: float, *, key_norm: str = "") -> float:
    """Parse scalar throughput values with optional kB/s hint."""
    if "kbps" in key_norm:
        return value / 1000
    return value


def _parse_throughput_string(
    text: str,
    *,
    key_norm: str,
    unit_hints: dict[str, float],
) -> float | None:
    """Parse string throughput values in the form '<number> <unit>'."""
    stripped = text.strip()
    # Examples: "31.48 MB/s", "1200 KB/s"
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)?$", stripped)
    if not match:
        return None

    amount = float(match.group(1))
    unit_token = match.group(2)
    if unit_token is None:
        return _parse_throughput_numeric(amount, key_norm=key_norm)

    unit = unit_token.replace(" ", "")
    factor = unit_hints.get(unit)
    if factor is None:
        return amount
    return amount * factor


def _parse_throughput_dict(
    value: dict[str, Any],
    *,
    key_norm: str,
    unit_hints: dict[str, float],
) -> float | None:
    """Parse throughput dictionaries with amount + unit fields."""
    amount = _first_number(value, ("value", "rate", "speed", "throughput"))
    if amount is None:
        return None

    unit_text = (
        _text(value.get("unit"))
        or _text(value.get("units"))
        or "MB/s"
    ).replace(" ", "")
    factor = unit_hints.get(unit_text)
    if factor is None:
        return amount
    return amount * factor


def _throughput_from_disks_mb_s(data: dict[str, Any], *, direction: str) -> float | None:
    """Aggregate throughput from per-disk fields if present."""
    per_direction_keys = {
        "read": ("readKBPS", "read_kbps", "readKBs", "read_kbs"),
        "write": ("writeKBPS", "write_kbps", "writeKBs", "write_kbs"),
    }
    keys = per_direction_keys[direction]

    for disks in _throughput_disk_lists(data):
        result = _throughput_from_disk_list(disks, keys=keys)
        if result is not None:
            return result
    return None


def _throughput_disk_lists(data: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Return candidate disk lists ordered from direct to nested payloads."""
    disk_lists: list[list[dict[str, Any]]] = []
    for key in THROUGHPUT_DISK_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            disks = [item for item in value if isinstance(item, dict)]
            if disks:
                disk_lists.append(disks)

    for key in THROUGHPUT_CONTAINER_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    disk_lists.extend(_throughput_disk_lists(item))
        elif isinstance(value, dict):
            disk_lists.extend(_throughput_disk_lists(value))
    return disk_lists


def _throughput_from_disk_list(
    disks: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
) -> float | None:
    """Aggregate throughput from one disk list if it has per-disk fields."""
    values_mb_s: list[float] = []
    for disk in disks:
        for key in keys:
            value = disk.get(key)
            if value is None:
                continue
            try:
                # KB/s -> MB/s
                values_mb_s.append(float(value) / 1000)
                break
            except (TypeError, ValueError):
                continue

    if not values_mb_s:
        return None
    return sum(values_mb_s)


AGGREGATE_SENSORS: tuple[AggregateSensorDescription, ...] = (
    AggregateSensorDescription(
        key="read_throughput",
        translation_key="read_throughput",
        native_unit_of_measurement="MB/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_read_throughput_mb_s,
    ),
    AggregateSensorDescription(
        key="write_throughput",
        translation_key="write_throughput",
        native_unit_of_measurement="MB/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_write_throughput_mb_s,
    ),
)
