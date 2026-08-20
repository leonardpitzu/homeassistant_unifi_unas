"""Common storage helper primitives."""

from __future__ import annotations

import re
from typing import Any

BYTES_PER_GIB = 1024**3
HEALTHY_STATUSES = {
    "fullyoperational",
    "nodataprotectionyet",
    "healthy",
    "ok",
    "normal",
    "online",
}
DEGRADED_STATUSES = {"degraded", "critical", "failed", "error", "offline"}
POOL_MAINTENANCE_HINTS = {
    "sync",
    "synced",
    "syncing",
    "rebuild",
    "rebuilding",
    "resilver",
    "resilvering",
    "initializing",
    "formatting",
    "expanding",
    "repairing",
}
DISK_PROBLEM_HINTS = {
    "atrisk",
    "risk",
    "degraded",
    "critical",
    "failed",
    "failure",
    "bad",
    "error",
    "warning",
    "unhealthy",
    "fault",
    "offline",
}
UUID_LIKE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _slug(value: str) -> str:
    """Return a simple slug for unique IDs."""
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in normalized.split("_") if part) or "pool"


def _text(value: Any) -> str | None:
    """Return a stripped string value or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _looks_like_machine_identifier(value: str) -> bool:
    """Return whether a string looks like a UUID/hash-like machine identifier."""
    stripped = value.strip()
    if UUID_LIKE_RE.fullmatch(stripped):
        return True

    compact = "".join(char for char in stripped.lower() if char.isalnum())
    return len(compact) >= 24 and all(char in "0123456789abcdef" for char in compact)


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return the first numeric value for the provided keys."""
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _dict_values(data: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return dictionary values for the provided keys."""
    values: list[dict[str, Any]] = []
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            values.append(value)
    return values


def _sum_known(values: list[float | None]) -> float | None:
    """Sum numeric values; return None if no values are known."""
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _bytes_to_gib(value: float | None) -> float | None:
    """Convert bytes to GiB."""
    if value is None:
        return None
    return round(value / BYTES_PER_GIB, 2)


def _percentage(used: float | None, total: float | None) -> float | None:
    """Return usage percentage."""
    if used is None or total is None or total == 0:
        return None
    return round((used / total) * 100, 1)


def _normalize_percent(value: float | None) -> float | None:
    """Normalize numeric progress values to the range 0-100."""
    if value is None:
        return None
    if value <= 1:
        value = value * 100
    if value < 0:
        value = 0
    if value > 100:
        value = 100
    return round(value, 1)
