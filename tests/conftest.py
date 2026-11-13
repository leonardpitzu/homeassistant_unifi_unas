"""Shared fixtures for the UniFi Drive / UNAS tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_unas.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "aa:bb:cc:dd:ee:ff"
POOL = "c50257da_ade9_48f1_a080_6285f8ccd342"
ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 443,
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
    CONF_API_KEY: "test-key",
}


def load(name: str) -> dict[str, Any]:
    """Load a JSON fixture (sanitized real UNAS 4 responses)."""
    result: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return result


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/unifi_unas."""


@pytest.fixture
def client() -> Generator[AsyncMock]:
    """Patch the API client used by the integration and the config flow."""
    with (
        patch("custom_components.unifi_unas.UnifiDriveClient", autospec=True) as setup_cls,
        patch("custom_components.unifi_unas.config_flow.UnifiDriveClient", new=setup_cls),
    ):
        mock = setup_cls.return_value
        mock.url = "https://192.0.2.10"
        mock.async_get_system.return_value = load("system")
        mock.async_get_storage.return_value = load("storage")
        mock.async_get_device_info.return_value = load("device_info")
        mock.async_get_network_io.return_value = load("network_io")
        mock.async_get_fan_control.return_value = load("fan_control")
        yield mock


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a v2 config entry."""
    return MockConfigEntry(
        domain=DOMAIN, title="UniFi Drive (192.0.2.10)", unique_id=MAC, data=ENTRY_DATA, version=2
    )
