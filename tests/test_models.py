"""Tests for payload parsing."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from custom_components.unifi_unas.models import UnasData, parse

from .conftest import POOL, load


def _parse(storage: dict | None = None, **overrides: object) -> UnasData:
    docs = {
        "device_info": load("device_info"),
        "network_io": load("network_io"),
        "fan": load("fan_control"),
    }
    docs.update(overrides)
    return parse(storage or load("storage"), docs["device_info"], docs["network_io"], docs["fan"])


def test_real_payload() -> None:
    """A captured UNAS 4 payload parses into the values the dashboard shows."""
    data = _parse()
    assert data.overall_status == "healthy"
    assert data.cache_status == "healthy"
    assert data.at_risk_disk_count == 0
    assert data.storage_problem is False
    assert data.average_disk_temperature == 45.5
    assert data.ssd_wear == 11.0
    assert data.usage_percent == 38.4
    assert (data.cpu_temperature, data.cpu_percent, data.memory_percent) == (75, 61, 77)
    assert (data.read_mb_s, data.write_mb_s) == (3.02, 1.79)
    assert data.fan_mode == "Balance"
    assert data.model == "UNAS4W"
    assert data.sw_version == "6.0.18 / Drive 4.4.30"

    pool = data.pools[POOL]
    assert (pool.name, pool.status, pool.raw_status) == ("Pool 1", "healthy", "fullyOperational")
    assert (pool.capacity_gib, pool.used_gib, pool.available_gib) == (22331.72, 8578.98, 13752.74)
    assert pool.rebuild_progress == 0.0
    assert pool.problem is False
    assert [d.name for d in pool.drives] == ["HDD 1", "HDD 2", "HDD 3", "HDD 4"]

    hdd = data.drives[f"{POOL}_sn000001"]
    assert (hdd.status, hdd.raw_health, hdd.temperature, hdd.power_on_hours) == ("optimal", "optimal", 42.0, 17324)
    assert (hdd.life_span, hdd.capacity_gib, hdd.bad_sectors) == (None, 7452.04, 0)
    ssd = data.drives["cache_sn000005"]
    assert (ssd.group_name, ssd.name, ssd.life_span, ssd.capacity_gib) == ("Cache", "SSD 1", 90, 1863.02)


def test_problems_are_detected() -> None:
    """Degraded pools, at-risk drives and risk reasons raise the problem flags."""
    storage = load("storage")
    storage["pools"][0]["status"] = "degraded"
    storage["pools"][0]["raidGroups"][0]["progress"] = 42.5
    storage["disks"][0]["healthScore"] = 3
    storage["cacheSlots"][1]["riskReasons"] = ["wear"]
    data = _parse(storage)
    pool = data.pools[POOL]
    assert pool.status == "degraded"
    assert pool.rebuild_progress == 42.5
    assert pool.at_risk_drive_count == 1
    assert pool.problem is True
    assert data.drives[f"{POOL}_sn000001"].status == "at_risk"
    assert data.at_risk_disk_count == 2
    assert data.overall_status == "degraded"
    assert data.storage_problem is True


def test_status_mapping() -> None:
    """Unknown statuses pass through; problem words map to degraded."""
    storage = load("storage")
    storage["pools"][0]["status"] = "expanding"
    storage["pools"][0]["cache"]["status"] = "cacheFailure"
    del storage["disks"][0]["healthScore"]
    storage["disks"][0]["state"] = "rebuilding"
    data = _parse(storage)
    assert data.overall_status == "expanding"
    assert data.cache_status == "degraded"
    assert data.storage_problem is True
    assert data.drives[f"{POOL}_sn000001"].status == "rebuilding"


def test_sparse_payload() -> None:
    """Missing optional documents and fields degrade to None, never raise."""
    storage = {"pools": [{"status": "fullyOperational"}, "junk"], "disks": "junk", "cacheSlots": [{"healthScore": True}]}
    data = parse(storage, None, None, None)
    pool = data.pools["pool_1"]
    assert (pool.capacity_gib, pool.available_gib, pool.rebuild_progress) == (None, None, None)
    assert data.usage_percent is None
    assert data.average_disk_temperature is None
    assert data.ssd_wear is None
    assert data.cpu_temperature is data.cpu_percent is data.memory_percent is None
    assert data.uptime is None
    assert data.sw_version is None
    assert data.fan_mode is None
    assert data.drives["cache_drive_1"].name == "Drive 1"
    assert parse({}, None, None, None).overall_status is None


def test_versions_and_load_formats() -> None:
    """Percent loads pass through; a single version is used as-is."""
    info = copy.deepcopy(load("device_info"))
    info["cpu"]["currentload"] = 37.2
    del info["version"]
    info["startupTime"] = "not-a-date"
    data = _parse(device_info=info)
    assert data.cpu_percent == 37
    assert data.sw_version == "6.0.18"
    assert data.started_at is None
    info["startupTime"] = 1234
    assert _parse(device_info=info).started_at is None


def test_uptime_format() -> None:
    """Uptime renders the three most significant units."""
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    cases = {
        timedelta(minutes=5): "5m",
        timedelta(hours=8, minutes=59): "8h",
        timedelta(days=3, hours=7): "3d 7h",
        timedelta(days=400, hours=5): "1y 1mo 5d",
    }
    for delta, expected in cases.items():
        info = load("device_info")
        info["startupTime"] = (now - delta).isoformat().replace("+00:00", "")
        with patch("custom_components.unifi_unas.models.datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            assert _parse(device_info=info).uptime == expected
