"""Snapshot settings write payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import DEFAULT_SNAPSHOT_LIMIT, MAX_SNAPSHOT_LIMIT, MIN_SNAPSHOT_LIMIT
from .snapshot_schedule import (
    _snapshot_schedule_api_value,
    _snapshot_schedule_days,
    _snapshot_schedule_first_run_time,
    _snapshot_schedule_monthdays,
    _snapshot_schedule_weekdays,
)
from .snapshot_values import _int_value


@dataclass(frozen=True, kw_only=True)
class SnapshotSettingsUpdate:
    """Requested snapshot settings changes for one target."""

    enabled: bool | None = None
    max_count: int | None = None
    schedule_enabled: bool | None = None
    schedule_frequency: str | None = None
    schedule_time: str | None = None
    schedule_weekdays: str | None = None
    schedule_monthdays: str | None = None

    @property
    def delete_required(self) -> bool:
        """Return whether this change should remove the snapshot setting."""
        return (
            self.enabled is False
            and self.max_count is None
            and self.schedule_enabled is None
            and self.schedule_frequency is None
            and self.schedule_time is None
            and self.schedule_weekdays is None
            and self.schedule_monthdays is None
        )


def _snapshot_settings_delete_required(
    update: SnapshotSettingsUpdate | None = None,
    *,
    enabled: bool | None = None,
    max_count: int | None = None,
    schedule_enabled: bool | None = None,
    schedule_frequency: str | None = None,
    schedule_time: str | None = None,
    schedule_weekdays: str | None = None,
    schedule_monthdays: str | None = None,
) -> bool:
    """Return whether this change should remove the snapshot setting."""
    update = update or SnapshotSettingsUpdate(
        enabled=enabled,
        max_count=max_count,
        schedule_enabled=schedule_enabled,
        schedule_frequency=schedule_frequency,
        schedule_time=schedule_time,
        schedule_weekdays=schedule_weekdays,
        schedule_monthdays=schedule_monthdays,
    )
    return update.delete_required


def _snapshot_settings_write_body(
    target: dict[str, Any],
    update: SnapshotSettingsUpdate | None = None,
    *,
    enabled: bool | None = None,
    max_count: int | None = None,
    schedule_enabled: bool | None = None,
    schedule_frequency: str | None = None,
    schedule_time: str | None = None,
    schedule_weekdays: str | None = None,
    schedule_monthdays: str | None = None,
) -> dict[str, Any]:
    """Return the UniFi snapshot-settings write payload."""
    update = update or SnapshotSettingsUpdate(
        enabled=enabled,
        max_count=max_count,
        schedule_enabled=schedule_enabled,
        schedule_frequency=schedule_frequency,
        schedule_time=schedule_time,
        schedule_weekdays=schedule_weekdays,
        schedule_monthdays=schedule_monthdays,
    )
    target_enabled = (
        bool(target.get("enabled")) if update.enabled is None else update.enabled
    )
    current_max_count = _int_value(target.get("max_count"))
    if update.max_count is None:
        if current_max_count and current_max_count >= MIN_SNAPSHOT_LIMIT:
            max_snapshots = current_max_count
        elif target_enabled:
            max_snapshots = DEFAULT_SNAPSHOT_LIMIT
        else:
            max_snapshots = MIN_SNAPSHOT_LIMIT
    else:
        max_snapshots = int(update.max_count)

    max_snapshots = min(max(max_snapshots, MIN_SNAPSHOT_LIMIT), MAX_SNAPSHOT_LIMIT)
    schedule = _snapshot_settings_schedule_body(
        target,
        update,
    )

    return {
        "name": "",
        "enabled": bool(target_enabled),
        "schedule": schedule,
        "maxSnapshots": max_snapshots,
    }


def _snapshot_settings_schedule_body(
    target: dict[str, Any],
    update: SnapshotSettingsUpdate | None = None,
    *,
    schedule_enabled: bool | None = None,
    schedule_frequency: str | None = None,
    schedule_time: str | None = None,
    schedule_weekdays: str | None = None,
    schedule_monthdays: str | None = None,
) -> dict[str, Any]:
    """Return the UniFi snapshot-settings schedule payload."""
    update = update or SnapshotSettingsUpdate(
        schedule_enabled=schedule_enabled,
        schedule_frequency=schedule_frequency,
        schedule_time=schedule_time,
        schedule_weekdays=schedule_weekdays,
        schedule_monthdays=schedule_monthdays,
    )
    frequency = str(
        update.schedule_frequency or target.get("schedule_frequency") or "Never"
    )
    api_frequency = _snapshot_schedule_api_value(frequency)
    schedule_is_enabled = (
        bool(target.get("schedule_enabled"))
        if update.schedule_enabled is None
        else update.schedule_enabled
    )
    if api_frequency == "never":
        schedule_is_enabled = False
    elif update.schedule_frequency is not None:
        schedule_is_enabled = True

    first_run_time = _snapshot_schedule_first_run_time(
        update.schedule_time or target.get("schedule_time")
    )
    weekdays = "*"
    monthdays = ""
    if api_frequency == "weekly":
        weekdays = (
            _snapshot_schedule_days(update.schedule_weekdays, minimum=0, maximum=6)
            or _snapshot_schedule_weekdays(target)
            or "1"
        )
    elif api_frequency == "monthly":
        weekdays = ""
        monthdays = (
            _snapshot_schedule_days(update.schedule_monthdays, minimum=1, maximum=31)
            or _snapshot_schedule_monthdays(target)
            or "1"
        )

    return {
        "interval": 60,
        "weekdays": weekdays,
        "monthdays": monthdays,
        "enable": bool(schedule_is_enabled),
        "firstRunTime": first_run_time,
        "lastRunTime": first_run_time,
    }
