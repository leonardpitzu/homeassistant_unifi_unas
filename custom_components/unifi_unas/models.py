"""Parse UniFi Drive API documents into one immutable snapshot per poll.

Everything an entity shows is computed here once, so entity properties are
plain attribute reads. Payload shapes (Drive 4.x, UniFi OS 5-6):

- ``storage``: ``pools[]`` (``id``, ``number``, ``status``, ``capacity``,
  ``usage`` in bytes, ``raidGroups[].progress``, ``cache.status``),
  ``disks[]`` (pool members, linked by ``poolId``) and ``cacheSlots[]``
  (SSD cache), both with ``slotId``, ``type``, ``serial``, ``state``,
  ``healthScore``, ``temperature``, ``powerOnHours``, ``size``, ...
- ``device_info``: ``cpu.{temperature,currentload}``,
  ``memory.{total,available}``, ``startupTime``, ``firmwareVersion``,
  ``version`` (Drive app), ``model``
- ``network_io``: ``transmitKBPS`` / ``receiveKBPS``
- ``fan``: ``currentProfile``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import FAN_ALIASES

GIB = 1024**3
CACHE_KEY = "cache"
_HEALTHY = {"fullyoperational", "nodataprotectionyet", "healthy", "optimal", "ok", "normal", "online"}
_PROBLEM_HINTS = ("degraded", "critical", "fail", "error", "offline", "risk", "fault", "bad", "missing")


@dataclass(frozen=True, slots=True)
class Drive:
    """One physical drive (pool member or cache SSD)."""

    key: str
    group_name: str
    name: str
    status: str | None
    raw_health: str | None
    at_risk: bool
    temperature: float | None
    power_on_hours: int | None
    life_span: int | None
    capacity_gib: float | None
    bad_sectors: int | None
    uncorrectable_sectors: int | None
    media_type: str | None
    model: str | None
    firmware: str | None


@dataclass(frozen=True, slots=True)
class Pool:
    """One storage pool."""

    key: str
    name: str
    status: str | None
    raw_status: str | None
    capacity: int | None
    usage: int | None
    rebuild_progress: float | None
    drives: tuple[Drive, ...]

    @property
    def capacity_gib(self) -> float | None:
        return _gib(self.capacity)

    @property
    def used_gib(self) -> float | None:
        return _gib(self.usage)

    @property
    def available_gib(self) -> float | None:
        if self.capacity is None or self.usage is None:
            return None
        return _gib(max(0, self.capacity - self.usage))

    @property
    def at_risk_drive_count(self) -> int:
        return sum(drive.at_risk for drive in self.drives)

    @property
    def problem(self) -> bool:
        return self.status == "degraded" or self.at_risk_drive_count > 0


@dataclass(frozen=True, slots=True)
class UnasData:
    """Everything one poll learned about the console."""

    pools: dict[str, Pool]
    cache_drives: tuple[Drive, ...]
    cache_status: str | None
    cpu_temperature: float | None
    cpu_percent: float | None
    memory_percent: float | None
    started_at: datetime | None
    read_mb_s: float | None
    write_mb_s: float | None
    fan_mode: str | None
    os_version: str | None
    drive_version: str | None
    model: str | None
    drives: dict[str, Drive] = field(init=False)

    def __post_init__(self) -> None:
        all_drives = [d for pool in self.pools.values() for d in pool.drives] + list(self.cache_drives)
        object.__setattr__(self, "drives", {d.key: d for d in all_drives})

    @property
    def overall_status(self) -> str | None:
        statuses = [pool.status for pool in self.pools.values() if pool.status]
        if not statuses:
            return None
        if "degraded" in statuses:
            return "degraded"
        return "healthy" if all(s == "healthy" for s in statuses) else statuses[0]

    @property
    def at_risk_disk_count(self) -> int:
        return sum(drive.at_risk for drive in self.drives.values())

    @property
    def storage_problem(self) -> bool:
        return (
            self.overall_status == "degraded" or self.cache_status == "degraded" or self.at_risk_disk_count > 0
        )

    @property
    def average_disk_temperature(self) -> float | None:
        temps = [d.temperature for p in self.pools.values() for d in p.drives if d.temperature is not None]
        return round(sum(temps) / len(temps), 1) if temps else None

    @property
    def ssd_wear(self) -> float | None:
        wear = [100 - d.life_span for d in self.drives.values() if d.life_span is not None]
        return round(sum(wear) / len(wear), 1) if wear else None

    @property
    def usage_percent(self) -> float | None:
        capacity = sum(p.capacity or 0 for p in self.pools.values())
        usage = sum(p.usage or 0 for p in self.pools.values())
        return round(usage / capacity * 100, 1) if capacity else None

    @property
    def uptime(self) -> str | None:
        """Compact uptime such as ``3d 7h`` (``45m`` under an hour)."""
        if self.started_at is None:
            return None
        minutes = max(0, int((datetime.now(UTC) - self.started_at).total_seconds() // 60))
        hours = minutes // 60
        if not hours:
            return f"{minutes}m"
        parts = []
        for label, size in (("y", 8760), ("mo", 720), ("d", 24), ("h", 1)):
            if hours >= size:
                count, hours = divmod(hours, size)
                parts.append(f"{count}{label}")
        return " ".join(parts[:3])

    @property
    def sw_version(self) -> str | None:
        if self.os_version and self.drive_version:
            return f"{self.os_version} / Drive {self.drive_version}"
        return self.os_version or self.drive_version


def parse(
    storage: dict[str, Any],
    device_info: dict[str, Any] | None,
    network_io: dict[str, Any] | None,
    fan: dict[str, Any] | None,
) -> UnasData:
    """Build a snapshot from the raw API documents."""
    info = device_info or {}
    cpu = _dict(info.get("cpu"))
    memory = _dict(info.get("memory"))
    disks = _dicts(storage.get("disks"))

    pools: dict[str, Pool] = {}
    cache_status: str | None = None
    for index, raw in enumerate(_dicts(storage.get("pools"))):
        pool_id = _text(raw.get("id"))
        key = _slug(pool_id) if pool_id else f"pool_{index + 1}"
        name = f"Pool {raw.get('number') or index + 1}"
        members = [d for d in disks if pool_id and d.get("poolId") == pool_id]
        pools[key] = Pool(
            key=key,
            name=name,
            status=_health(raw.get("status")),
            raw_status=_text(raw.get("status")),
            capacity=_int(raw.get("capacity")),
            usage=_int(raw.get("usage")),
            rebuild_progress=_rebuild_progress(raw),
            drives=tuple(_drive(d, key, name, i) for i, d in enumerate(members)),
        )
        cache_status = cache_status or _health(_dict(raw.get("cache")).get("status"))

    total = _num(memory.get("total"))
    available = _num(memory.get("available"))
    load = _num(cpu.get("currentload"))
    return UnasData(
        pools=pools,
        cache_drives=tuple(
            _drive(d, CACHE_KEY, "Cache", i) for i, d in enumerate(_dicts(storage.get("cacheSlots")))
        ),
        cache_status=cache_status,
        # Whole numbers on purpose: tenths changed on every poll and were the
        # bulk of this integration's recorder writes.
        cpu_temperature=_int(cpu.get("temperature")),
        cpu_percent=None if load is None else round(load * 100 if load <= 1 else load),
        memory_percent=round((total - available) / total * 100) if total and available is not None else None,
        started_at=_timestamp(info.get("startupTime")),
        read_mb_s=_kbps_to_mb_s((network_io or {}).get("transmitKBPS")),
        write_mb_s=_kbps_to_mb_s((network_io or {}).get("receiveKBPS")),
        fan_mode=FAN_ALIASES.get(str((fan or {}).get("currentProfile", "")).lower()),
        os_version=_text(info.get("firmwareVersion")),
        drive_version=_text(info.get("version")),
        model=_text(info.get("model")),
    )


def _drive(raw: dict[str, Any], group_key: str, group_name: str, index: int) -> Drive:
    serial = _text(raw.get("serial"))
    media = _text(raw.get("type"))
    score = _num(raw.get("healthScore"))
    state = _text(raw.get("state"))
    if score is not None:
        status: str | None = "optimal" if score >= 5 else "at_risk"
    else:
        status = "optimal" if _health(state) == "healthy" else state
    life = _num(raw.get("lifeSpan"))
    return Drive(
        key=f"{group_key}_{_slug(serial) if serial else f'drive_{index + 1}'}",
        group_name=group_name,
        name=f"{media or 'Drive'} {raw.get('slotId') or index + 1}",
        status=status,
        raw_health=state,
        at_risk=status == "at_risk" or bool(raw.get("riskReasons")),
        temperature=_round(raw.get("temperature")),
        power_on_hours=_int(raw.get("powerOnHours")),
        life_span=None if life is None else round(min(100.0, max(0.0, life))),
        capacity_gib=_gib(_int(raw.get("size"))),
        bad_sectors=_int(raw.get("badSectorCount")),
        uncorrectable_sectors=_int(raw.get("uncorrectableSectorCount")),
        media_type=media,
        model=_text(raw.get("model")),
        firmware=_text(raw.get("firmware")),
    )


def _rebuild_progress(pool: dict[str, Any]) -> float | None:
    """Highest progress of the pool's data RAID groups (0 when idle)."""
    values = [
        _num(group.get("progress"))
        for group in _dicts(pool.get("raidGroups"))
        if not group.get("isSSDCache")
    ]
    known = [v for v in values if v is not None]
    return round(max(known), 1) if known else None


def _health(value: Any) -> str | None:
    """Map a raw status onto ``healthy`` / ``degraded``, else keep it."""
    if (text := _text(value)) is None:
        return None
    token = re.sub(r"[^a-z0-9]", "", text.lower())
    if token in _HEALTHY:
        return "healthy"
    if any(hint in token for hint in _PROBLEM_HINTS):
        return "degraded"
    return text


def _slug(value: str) -> str:
    return "_".join(filter(None, re.split(r"[^a-z0-9]+", value.lower())))


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return str(value).strip() or None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(round(number))


def _round(value: Any) -> float | None:
    number = _num(value)
    return None if number is None else round(number, 1)


def _gib(value: int | None) -> float | None:
    return None if value is None else round(value / GIB, 2)


def _kbps_to_mb_s(value: Any) -> float | None:
    number = _num(value)
    return None if number is None else round(number / 1000, 2)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
