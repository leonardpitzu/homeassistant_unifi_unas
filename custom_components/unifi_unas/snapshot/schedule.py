"""Schedule parsing and formatting helpers for UniFi Drive snapshots."""

from __future__ import annotations

import re
from typing import Any

from .const import SNAPSHOT_SCHEDULE_API_VALUES
from .snapshot_values import _first_int_value, _int_value, _value_from_dict

SCHEDULE_TIME_RE = re.compile(
    r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?::\d{1,2})?\s*"
    r"(?P<suffix>[ap]m)?\s*$",
    re.IGNORECASE,
)


def _snapshot_schedule_api_value(option: str) -> str:
    """Return API value for a schedule option."""
    normalized = str(option).strip().lower()
    for label, values in SNAPSHOT_SCHEDULE_API_VALUES.items():
        if normalized == label.lower() or normalized in values:
            return str(values[0])
    return normalized


def _snapshot_schedule_option(value: Any) -> str | None:
    """Return HA option label for a schedule API value."""
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    for label, values in SNAPSHOT_SCHEDULE_API_VALUES.items():
        if normalized == label.lower() or normalized in values:
            return str(label)
    return str(value)


def _snapshot_schedule_frequency(
    schedule: dict[str, Any],
    enabled: bool | None,
) -> str | None:
    """Return normalized schedule frequency from a UniFi schedule dict."""
    if enabled is False:
        return "Never"

    value = _value_from_dict(schedule, ("frequency", "period", "repeat", "type"))
    option = _snapshot_schedule_option(value)
    if option:
        return option

    monthdays = str(
        _value_from_dict(schedule, ("monthdays", "monthDays", "month_days")) or ""
    ).strip()
    if monthdays and monthdays != "*":
        return "Monthly"

    weekdays = str(
        _value_from_dict(schedule, ("weekdays", "weekDays", "week_days")) or ""
    ).strip()
    if weekdays and weekdays != "*":
        return "Weekly"

    interval = _int_value(schedule.get("interval"))
    if interval == 60:
        return "Daily"
    if enabled is not True:
        return "Never"
    if enabled is True:
        return "Daily"
    return None


def _snapshot_schedule_weekdays(target: dict[str, Any]) -> str | None:
    """Return an existing weekly selector value when present."""
    return _snapshot_existing_schedule_days(
        target.get("schedule_weekdays"),
        minimum=0,
        maximum=6,
    )


def _snapshot_schedule_monthdays(target: dict[str, Any]) -> str | None:
    """Return an existing monthly selector value when present."""
    return _snapshot_existing_schedule_days(
        target.get("schedule_monthdays"),
        minimum=1,
        maximum=31,
    )


def _snapshot_existing_schedule_days(
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> str | None:
    """Return valid existing schedule days, ignoring malformed API values."""
    if value in (None, ""):
        return None

    days: list[str] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part or part == "*":
            continue
        day = _int_value(part)
        if day is None or day < minimum or day > maximum:
            continue
        text = str(day)
        if text not in days:
            days.append(text)
    return ",".join(days) or None


def _snapshot_first_schedule_day(
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    """Return the first valid day from a UniFi comma-list."""
    days = _snapshot_existing_schedule_days(
        value,
        minimum=minimum,
        maximum=maximum,
    )
    if days is None:
        return None
    return int(days.split(",", 1)[0])


def _snapshot_schedule_days(
    value: str | None,
    *,
    minimum: int,
    maximum: int,
) -> str | None:
    """Return a normalized comma-separated schedule day list."""
    if value is None:
        return None

    parts = [part.strip() for part in str(value).split(",")]
    days: list[str] = []
    for part in parts:
        day = _int_value(part)
        if day is None or day < minimum or day > maximum:
            raise ValueError(
                f"Schedule day values must be between {minimum} and {maximum}"
            )
        text = str(day)
        if text not in days:
            days.append(text)

    if not days:
        raise ValueError("Schedule day list cannot be empty")
    return ",".join(days)


def _snapshot_schedule_time(schedule: dict[str, Any]) -> str | None:
    """Return HH:MM schedule time when present."""
    text = _value_from_dict(
        schedule,
        (
            "firstRunTime",
            "first_run_time",
            "time",
            "at",
            "startTime",
            "start_time",
        ),
    )
    if text:
        try:
            hour, minute = _schedule_time_parts(text)
        except ValueError:
            return None
        return f"{hour:02d}:{minute:02d}"

    hour_value = _first_int_value(schedule, ("hour", "hourOfDay", "hour_of_day"))
    minute_value = _first_int_value(schedule, ("minute",))
    if hour_value is None:
        return None
    hour = hour_value
    minute = minute_value or 0
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _snapshot_schedule_first_run_time(value: Any) -> str:
    """Return UniFi firstRunTime text, falling back for malformed stored values."""
    try:
        hour, minute = _schedule_time_parts(str(value or "00:00"))
    except ValueError:
        hour, minute = 0, 0
    return f"{hour}:{minute:02d}"


def _schedule_time_parts(value: Any) -> tuple[int, int]:
    """Parse a schedule time string into hour and minute."""
    match = SCHEDULE_TIME_RE.fullmatch(str(value))
    if match is None:
        raise ValueError("Time must include hour and minute")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    suffix = (match.group("suffix") or "").lower()

    if suffix and (hour < 1 or hour > 12):
        raise ValueError("12-hour time is outside 1:00..12:59")
    if suffix == "am" and hour == 12:
        hour = 0
    elif suffix == "pm" and hour < 12:
        hour += 12

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Time is outside 00:00..23:59")
    return hour, minute
