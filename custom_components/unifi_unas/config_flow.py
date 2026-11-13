"""Config flow for the UniFi Drive / UNAS integration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import CannotConnect, InvalidAuth, UnifiDriveClient, base_url
from .const import (
    CONF_WOL_BROADCAST,
    CONF_WOL_MAC,
    CONF_WOL_PORT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WOL_BROADCAST,
    DEFAULT_WOL_PORT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_CONNECTION_KEYS = (CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL)
_CREDENTIAL_KEYS = (CONF_API_KEY, CONF_USERNAME, CONF_PASSWORD)


def normalize_mac(value: str) -> str | None:
    """Return a MAC address as lower-case colon-separated hex, or None."""
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(compact) != 12:
        return None
    return ":".join(compact[i : i + 2] for i in range(0, 12, 2)).lower()


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.Coerce(int),
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, True)): bool,
            vol.Required(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, False)): bool,
        }
    )


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_API_KEY): _PASSWORD,
            vol.Optional(CONF_USERNAME): str,
            vol.Optional(CONF_PASSWORD): _PASSWORD,
        }
    )


def _reconfigure_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Connection fields plus credentials; secrets are never echoed back."""
    return _connection_schema(defaults).extend(
        {
            vol.Optional(CONF_API_KEY): _PASSWORD,
            vol.Optional(CONF_USERNAME, description={"suggested_value": defaults.get(CONF_USERNAME, "")}): str,
            vol.Optional(CONF_PASSWORD): _PASSWORD,
        }
    )


def _merge_reconfigure(current: Mapping[str, Any], user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a reconfigure form to the entry data.

    A blank API key or password keeps the stored one; a cleared username
    removes the local account (and its password).
    """
    data = {**current, **{key: user_input[key] for key in _CONNECTION_KEYS}}
    if api_key := str(user_input.get(CONF_API_KEY) or "").strip():
        data[CONF_API_KEY] = api_key
    if username := str(user_input.get(CONF_USERNAME) or "").strip():
        data[CONF_USERNAME] = username
        if password := user_input.get(CONF_PASSWORD):
            data[CONF_PASSWORD] = password
    else:
        data.pop(CONF_USERNAME, None)
        data.pop(CONF_PASSWORD, None)
    return data


async def _async_validate(hass: HomeAssistant, data: Mapping[str, Any]) -> str:
    """Check connectivity and credentials; return the device MAC (unique ID)."""
    client = UnifiDriveClient(
        async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL]),
        base_url(data[CONF_HOST], data[CONF_PORT], data[CONF_SSL]),
        api_key=data.get(CONF_API_KEY),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    system = await client.async_get_system()
    await client.async_get_storage()
    if (mac := normalize_mac(str(system.get("mac", "")))) is None:
        raise CannotConnect("The device did not report a MAC address")
    return mac


async def _async_try(hass: HomeAssistant, data: Mapping[str, Any]) -> tuple[str | None, dict[str, str]]:
    """Validate and map client errors onto form errors."""
    try:
        return await _async_validate(hass, data), {}
    except InvalidAuth:
        return None, {"base": "invalid_auth"}
    except CannotConnect:
        return None, {"base": "cannot_connect"}


class UnifiDriveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a UniFi Drive console."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for host and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac, errors = await _async_try(self.hass, user_input)
            if mac:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(updates={k: user_input[k] for k in _CONNECTION_KEYS})
                return self.async_create_entry(title=f"UniFi Drive ({user_input[CONF_HOST]})", data=user_input)
        schema = _connection_schema(user_input or {}).extend(_credentials_schema().schema)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change connection settings or add, replace or remove credentials."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _merge_reconfigure(entry.data, user_input)
            mac, errors = await _async_try(self.hass, data)
            if mac:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_reconfigure_schema(user_input or entry.data), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**{k: v for k, v in entry.data.items() if k not in _CREDENTIAL_KEYS}, **user_input}
            mac, errors = await _async_try(self.hass, data)
            if mac:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(step_id="reauth_confirm", data_schema=_credentials_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return UnifiDriveOptionsFlow()


class UnifiDriveOptionsFlow(OptionsFlow):
    """Polling interval and Wake-on-LAN settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input.get(CONF_WOL_MAC, "").strip()
            if mac and (mac := normalize_mac(mac)) is None:
                errors[CONF_WOL_MAC] = "invalid_mac"
            else:
                options = {**user_input, CONF_WOL_MAC: mac}
                if not mac:
                    options.pop(CONF_WOL_MAC)
                return self.async_create_entry(data=options)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Optional(CONF_WOL_MAC, description={"suggested_value": current.get(CONF_WOL_MAC, "")}): str,
                vol.Required(
                    CONF_WOL_BROADCAST, default=current.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
                ): str,
                vol.Required(CONF_WOL_PORT, default=current.get(CONF_WOL_PORT, DEFAULT_WOL_PORT)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
