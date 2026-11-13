"""Tests for the HTTP client."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.unifi_unas.api import (
    DEVICE_INFO_PATH,
    FAN_CONTROL_PATH,
    LOGIN_PATH,
    REBOOT_PATH,
    STORAGE_PATH,
    CannotConnect,
    InvalidAuth,
    UnifiDriveClient,
    base_url,
)

URL = "https://nas"
JSON = {"Content-Type": "application/json"}


def _client(hass: HomeAssistant, mock: AiohttpClientMocker, **kwargs: str) -> UnifiDriveClient:
    return UnifiDriveClient(async_get_clientsession(hass), URL, **kwargs)


def test_base_url() -> None:
    """Default ports are omitted and IPv6 hosts are bracketed."""
    assert base_url("10.0.0.2", 443, True) == "https://10.0.0.2"
    assert base_url(" nas.lan/ ", 8443, True) == "https://nas.lan:8443"
    assert base_url("fe80::1", 80, False) == "http://[fe80::1]"


def test_credentials_required() -> None:
    """A client without any credential is rejected up front."""
    with pytest.raises(InvalidAuth):
        UnifiDriveClient(None, URL)  # type: ignore[arg-type]


async def test_api_key_requests(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """API-key requests carry the key header and parse JSON."""
    aioclient_mock.get(URL + STORAGE_PATH, json={"pools": []}, headers=JSON)
    aioclient_mock.put(URL + FAN_CONTROL_PATH, headers={"Content-Type": "text/plain"}, text="ok")
    client = _client(hass, aioclient_mock, api_key=" key ")
    assert await client.async_get_storage() == {"pools": []}
    await client.async_set_fan_profile("quiet")
    assert aioclient_mock.mock_calls[0][3]["X-API-Key"] == "key"


async def test_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """HTTP and transport failures map onto the client errors."""
    aioclient_mock.get(URL + STORAGE_PATH, status=401)
    aioclient_mock.get(URL + DEVICE_INFO_PATH, status=500)
    aioclient_mock.get(URL + FAN_CONTROL_PATH, exc=aiohttp.ClientError())
    aioclient_mock.post(URL + REBOOT_PATH, json=[1], headers=JSON)
    client = _client(hass, aioclient_mock, api_key="key")
    with pytest.raises(InvalidAuth):
        await client.async_get_storage()
    with pytest.raises(CannotConnect):
        await client.async_get_device_info()
    with pytest.raises(CannotConnect):
        await client.async_get_fan_control()
    await client.async_reboot()


async def test_non_object_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A JSON document that is not an object is unexpected."""
    aioclient_mock.get(URL + STORAGE_PATH, json=[1], headers=JSON)
    with pytest.raises(CannotConnect):
        await _client(hass, aioclient_mock, api_key="key").async_get_storage()


async def test_account_login_and_relogin(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A local account logs in once, sends the cookie and logs in again on 401."""
    aioclient_mock.post(
        URL + LOGIN_PATH,
        headers={"Set-Cookie": "TOKEN=abc; Path=/; SameSite=Strict", "X-Updated-CSRF-Token": "csrf"},
    )
    aioclient_mock.get(URL + STORAGE_PATH, status=401)
    client = _client(hass, aioclient_mock, username="admin", password="pw", api_key="ignored")
    with pytest.raises(InvalidAuth):
        await client.async_get_storage()
    logins = [call for call in aioclient_mock.mock_calls if str(call[1]).endswith(LOGIN_PATH)]
    assert len(logins) == 2
    storage_call = next(call for call in aioclient_mock.mock_calls if str(call[1]).endswith(STORAGE_PATH))
    assert storage_call[3]["Cookie"] == "TOKEN=abc"
    assert storage_call[3]["X-CSRF-Token"] == "csrf"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"status": 401}, InvalidAuth),
        ({"status": 500}, CannotConnect),
        ({"headers": {"Set-Cookie": "OTHER=1"}}, InvalidAuth),
        ({"exc": TimeoutError()}, CannotConnect),
    ],
)
async def test_login_failures(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs: dict, error: type[Exception]
) -> None:
    """Login failures are reported as auth or connection errors."""
    aioclient_mock.post(URL + LOGIN_PATH, **kwargs)
    with pytest.raises(error):
        await _client(hass, aioclient_mock, username="admin", password="pw").async_poweroff()
