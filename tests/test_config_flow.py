"""Config, reconfigure, reauth and options flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_unas.api import CannotConnect, InvalidAuth
from custom_components.unifi_unas.config_flow import normalize_mac
from custom_components.unifi_unas.const import CONF_WOL_BROADCAST, CONF_WOL_MAC, CONF_WOL_PORT, DOMAIN

from .conftest import ENTRY_DATA, MAC


def test_normalize_mac() -> None:
    """MAC addresses in common spellings normalize; junk is rejected."""
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == MAC
    assert normalize_mac("aabb.ccdd.eeff") == MAC
    assert normalize_mac("nope") is None


async def test_user_flow(hass: HomeAssistant, client: AsyncMock) -> None:
    """A valid host and key create an entry keyed by the device MAC."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "UniFi Drive (192.0.2.10)"
    assert result["result"].unique_id == MAC
    assert result["data"] == ENTRY_DATA


@pytest.mark.parametrize(
    ("method", "error", "reason"),
    [
        ("async_get_system", CannotConnect("x"), "cannot_connect"),
        ("async_get_storage", InvalidAuth("x"), "invalid_auth"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, client: AsyncMock, method: str, error: Exception, reason: str
) -> None:
    """Connection and auth failures are shown on the form, then recover."""
    getattr(client, method).side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": reason}
    getattr(client, method).side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_without_mac(hass: HomeAssistant, client: AsyncMock) -> None:
    """A device that hides its MAC cannot be identified."""
    client.async_get_system.return_value = {}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """The same device cannot be added twice; its host is refreshed instead."""
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**ENTRY_DATA, CONF_HOST: "nas.lan"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "nas.lan"


async def test_reconfigure(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Reconfigure changes the host but refuses a different device."""
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    client.async_get_system.return_value = {"mac": "11:22:33:44:55:66"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**_connection(), CONF_HOST: "other"})
    assert result["reason"] == "wrong_device"

    client.async_get_system.return_value = {"mac": MAC}
    result = await entry.start_reconfigure_flow(hass)
    client.async_get_storage.side_effect = CannotConnect("x")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**_connection(), CONF_HOST: "nas2"})
    assert result["errors"] == {"base": "cannot_connect"}
    client.async_get_storage.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**_connection(), CONF_HOST: "nas2"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "nas2"
    assert entry.data[CONF_API_KEY] == "test-key"


async def test_reauth(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Reauth swaps the credentials and keeps the connection."""
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    client.async_get_storage.side_effect = InvalidAuth("x")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "new"})
    assert result["errors"] == {"base": "invalid_auth"}
    client.async_get_storage.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "pw"}
    )
    assert result["reason"] == "reauth_successful"
    assert CONF_API_KEY not in entry.data
    assert entry.data[CONF_USERNAME] == "admin"
    assert entry.data[CONF_HOST] == "192.0.2.10"


async def test_options(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry) -> None:
    """Options validate the Wake-on-LAN MAC and drop it when empty."""
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    options = {CONF_SCAN_INTERVAL: 120, CONF_WOL_MAC: "junk", CONF_WOL_BROADCAST: "192.0.2.255", CONF_WOL_PORT: 7}
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["errors"] == {CONF_WOL_MAC: "invalid_mac"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**options, CONF_WOL_MAC: "AA-BB-CC-DD-EE-FF"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WOL_MAC] == MAC

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**options, CONF_WOL_MAC: ""})
    assert CONF_WOL_MAC not in entry.options


def _connection() -> dict[str, object]:
    return {k: v for k, v in ENTRY_DATA.items() if k != CONF_API_KEY}
