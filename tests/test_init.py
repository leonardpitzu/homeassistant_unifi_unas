"""Setup, entities, coordinator and migration tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.unifi_unas.api import CannotConnect, InvalidAuth
from custom_components.unifi_unas.const import CONF_WOL_MAC, DOMAIN
from custom_components.unifi_unas.diagnostics import async_get_config_entry_diagnostics

from .conftest import ENTRY_DATA, MAC, POOL, load

HDD1 = f"{POOL}_sn000001"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, unique_id: str) -> str:
    registry = er.async_get(hass)
    platform = "binary_sensor" if unique_id.endswith(("problem", "online")) else "sensor"
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{MAC}_{unique_id}")
    assert entity_id, unique_id
    state = hass.states.get(entity_id)
    assert state
    return state.state


async def test_setup_creates_entities(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """The real payload yields the expected entities, IDs and states."""
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    expected = {
        "overall_status": "healthy",
        "at_risk_disk_count": "0",
        "average_disk_temperature": "45.5",
        "usage_percent": "38.4",
        "cpu_temperature": "75",
        "memory_percent": "77",
        "read_throughput": "3.02",
        "device_online": STATE_ON,
        "storage_problem": STATE_OFF,
        f"{POOL}_pool_status": "healthy",
        f"{POOL}_pool_capacity": "22331.72",
        f"{POOL}_pool_available": "13752.74",
        f"{POOL}_pool_problem": STATE_OFF,
        f"{HDD1}_drive_status": "optimal",
        f"{HDD1}_drive_temperature": "42.0",
        "cache_sn000005_drive_life_span": "90",
    }
    for unique_id, value in expected.items():
        assert _state(hass, unique_id) == value, unique_id

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    # 12 device + 6 pool + 6 x 4 HDD + 7 x 2 SSD sensors, 3 binary, 2 buttons, 1 select
    assert len(entries) == 12 + 6 + 24 + 14 + 3 + 2 + 1
    assert not registry.async_get_entity_id("sensor", DOMAIN, f"{MAC}_{HDD1}_drive_life_span")

    status = hass.states.get(registry.async_get_entity_id("sensor", DOMAIN, f"{MAC}_{HDD1}_drive_status"))
    assert status.attributes["raw_health"] == "optimal"
    assert status.attributes["model"] == "ST8000VN004-3CP101"
    fan = hass.states.get(registry.async_get_entity_id("select", DOMAIN, f"{MAC}_fan_mode"))
    assert fan.state == "Balance"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MAC)})
    assert (device.model, device.sw_version) == ("UNAS4W", "6.0.18 / Drive 4.4.30")

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_drive_appears(
    hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Drives that show up later get entities; firmware updates reach the device."""
    await _setup(hass, entry)
    storage = load("storage")
    storage["disks"].append({**storage["disks"][0], "serial": "NEW1", "slotId": "5"})
    client.async_get_storage.return_value = storage
    info = load("device_info")
    info["firmwareVersion"] = "6.1.0"
    client.async_get_device_info.return_value = info
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _state(hass, f"{POOL}_new1_drive_status") == "optimal"
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MAC)})
    assert device.sw_version == "6.1.0 / Drive 4.4.30"


async def test_outage_handling(
    hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """One failed poll keeps data; the second marks entities unavailable."""
    await _setup(hass, entry)
    client.async_get_storage.side_effect = CannotConnect("down")
    client.async_get_fan_control.side_effect = InvalidAuth("no")

    async def tick() -> None:
        freezer.tick(timedelta(seconds=61))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    await tick()
    assert _state(hass, "overall_status") == "healthy"
    assert _state(hass, "device_online") == STATE_ON
    await tick()
    assert _state(hass, "overall_status") == STATE_UNAVAILABLE
    assert _state(hass, "device_online") == STATE_OFF

    client.async_get_storage.side_effect = None
    await tick()
    assert _state(hass, "overall_status") == "healthy"
    fan = er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_fan_mode")
    assert hass.states.get(fan).state == STATE_UNAVAILABLE


async def test_auth_failure_starts_reauth(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Rejected credentials start a reauth flow."""
    client.async_get_storage.side_effect = InvalidAuth("bad key")
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_offline_at_startup(hass: HomeAssistant, client: AsyncMock) -> None:
    """Without Wake-on-LAN an offline NAS retries; with it, setup continues."""
    client.async_get_storage.side_effect = CannotConnect("off")
    plain = MockConfigEntry(domain=DOMAIN, unique_id=MAC, data=ENTRY_DATA, version=2)
    await _setup(hass, plain)
    assert plain.state is ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_remove(plain.entry_id)

    wol = MockConfigEntry(
        domain=DOMAIN, unique_id=MAC, data=ENTRY_DATA, options={CONF_WOL_MAC: "aa:bb:cc:dd:ee:ff"}, version=2
    )
    await _setup(hass, wol)
    assert wol.state is ConfigEntryState.LOADED
    start = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{MAC}_wake_on_lan")
    assert hass.states.get(start).state != STATE_UNAVAILABLE

    transport = MagicMock()
    with patch("asyncio.BaseEventLoop.create_datagram_endpoint", return_value=(transport, None)):
        await hass.services.async_call("button", "press", {"entity_id": start}, blocking=True)
    assert transport.sendto.call_count == 3
    assert transport.sendto.call_args[0][0] == b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16

    with (
        patch("asyncio.BaseEventLoop.create_datagram_endpoint", side_effect=OSError("no")),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call("button", "press", {"entity_id": start}, blocking=True)
    transport.sendto.side_effect = OSError("unreachable")
    with (
        patch("asyncio.BaseEventLoop.create_datagram_endpoint", return_value=(transport, None)),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call("button", "press", {"entity_id": start}, blocking=True)


async def test_power_buttons(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Restart and shut down call the API and surface permission errors."""
    await _setup(hass, entry)
    registry = er.async_get(hass)
    restart = registry.async_get_entity_id("button", DOMAIN, f"{MAC}_reboot")
    shutdown = registry.async_get_entity_id("button", DOMAIN, f"{MAC}_shutdown")
    await hass.services.async_call("button", "press", {"entity_id": restart}, blocking=True)
    client.async_reboot.assert_awaited_once()

    for error in (InvalidAuth("no"), CannotConnect("down")):
        client.async_poweroff.side_effect = error
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call("button", "press", {"entity_id": shutdown}, blocking=True)


async def test_fan_select(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Selecting a profile sends the API value; failures are surfaced."""
    await _setup(hass, entry)
    fan = er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_fan_mode")
    await hass.services.async_call("select", "select_option", {"entity_id": fan, "option": "Quiet"}, blocking=True)
    client.async_set_fan_profile.assert_awaited_once_with("quiet")

    client.async_set_fan_profile.side_effect = CannotConnect("HTTP 500")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("select", "select_option", {"entity_id": fan, "option": "Cooling"}, blocking=True)


async def test_diagnostics_are_redacted(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Diagnostics carry the raw payload without credentials or identifiers."""
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["api_key"] == "**REDACTED**"
    assert diag["raw"]["storage"]["disks"][0]["serial"] == "**REDACTED**"
    assert diag["raw"]["device_info"]["networkInterfaces"][0]["mac"] == "**REDACTED**"
    assert diag["raw"]["storage"]["disks"][0]["temperature"] == 42


async def test_options_reload(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Changing options reloads with the new polling interval."""
    await _setup(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 120})
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(seconds=120)


async def test_migrate_v1(hass: HomeAssistant, client: AsyncMock) -> None:
    """v1 entries lose obsolete keys and entities, keeping everything current."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        version=1,
        data={**ENTRY_DATA, "username": "", "password": "", "discovery_mac_address": MAC, "discovery_confidence": 85},
        options={
            "scan_interval": 30,
            "fan_control_enabled": True,
            "snapshot_buttons_enabled": False,
            "wol_enabled": True,
            CONF_WOL_MAC: "aa:bb:cc:dd:ee:ff",
            "wol_port": 9,
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    kept = {
        "sensor": ["overall_status", f"{POOL}_pool_used", f"{HDD1}_drive_status", "cache_sn000005_drive_life_span"],
        "button": ["wake_on_lan"],
    }
    dropped = {
        "sensor": [
            "pool_count",
            "system_ip",
            f"{POOL}_pool_usage_percent",
            f"{POOL}_pool_drive_count",
            f"{HDD1}_drive_model",
            f"{HDD1}_drive_life_span",
        ],
        "binary_sensor": ["maintenance_active"],
        "update": ["unifi_os_update"],
        "button": ["backup_task1"],
    }
    for group in (kept, dropped):
        for platform, keys in group.items():
            for key in keys:
                registry.async_get_or_create(platform, DOMAIN, f"{MAC}_{key}", config_entry=entry)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert dict(entry.data) == {**ENTRY_DATA, "username": "", "password": ""}
    assert dict(entry.options) == {CONF_WOL_MAC: "aa:bb:cc:dd:ee:ff", "wol_port": 9}
    for platform, keys in kept.items():
        for key in keys:
            assert registry.async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}"), key
    for platform, keys in dropped.items():
        for key in keys:
            assert not registry.async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}"), key


async def test_migrate_keeps_custom_interval_and_drops_disabled_wol(hass: HomeAssistant, client: AsyncMock) -> None:
    """A non-default interval survives; a disabled Wake-on-LAN MAC does not."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        version=1,
        data=ENTRY_DATA,
        options={"scan_interval": 300, "wol_enabled": False, CONF_WOL_MAC: "aa:bb:cc:dd:ee:ff"},
    )
    await _setup(hass, entry)
    assert dict(entry.options) == {"scan_interval": 300}


async def test_migrate_from_future_fails(hass: HomeAssistant, client: AsyncMock) -> None:
    """Downgrades are refused."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, data=ENTRY_DATA, version=3)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
