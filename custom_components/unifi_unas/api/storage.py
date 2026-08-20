"""Storage/system read operations for the UniFi Drive API client."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .api_errors import CannotConnect, InvalidAuth, UnexpectedResponse
from .const import DRIVE_DEVICE_INFO_PATH, DRIVE_STORAGE_PATH, NETWORK_IO_PATH, SYSTEM_PATH
from .security import safe_error_text

_LOGGER = logging.getLogger(__name__)


class ApiStorageMixin:
    """Storage reads split from the main API client class."""

    _authenticated: bool
    _last_fan_mode: str | None
    _system_info: dict[str, Any] | None
    _use_api_key_auth: bool

    if TYPE_CHECKING:
        async def _ensure_authenticated(self) -> None: ...
        async def async_login(self) -> None: ...
        async def _request_json(self, method: str, path: str) -> dict[str, Any]: ...
        def _extract_fan_mode(self, payload: Any) -> str | None: ...

    async def async_check_connection(self) -> dict[str, Any]:
        """Validate credentials and return storage data."""
        if self._use_api_key_auth:
            self._authenticated = True
        else:
            await self.async_login()
        return await self.async_get_storage()

    async def _optional_json(self, path: str, label: str) -> dict[str, Any] | None:
        """Fetch a best-effort metadata endpoint, returning None on failure."""
        try:
            return await self._request_json("GET", path)
        except (CannotConnect, InvalidAuth, UnexpectedResponse) as err:
            _LOGGER.debug("Could not read %s: %s", label, safe_error_text(err))
            return None

    async def async_get_storage(self, *, refresh_system: bool = True) -> dict[str, Any]:
        """Return UniFi Drive storage information.

        The three metadata endpoints do not depend on each other, so they are
        fetched concurrently instead of in series. `/api/system` only changes on
        a firmware update, so callers may skip it and reuse the cached payload.
        """
        await self._ensure_authenticated()
        try:
            data = await self._request_json("GET", DRIVE_STORAGE_PATH)
        except InvalidAuth:
            _LOGGER.debug("UNAS session expired; retrying login once")
            self._authenticated = False
            await self.async_login()
            data = await self._request_json("GET", DRIVE_STORAGE_PATH)

        if mode := self._extract_fan_mode(data):
            self._last_fan_mode = mode

        include_system = refresh_system or self._system_info is None

        async def _system_metadata() -> dict[str, Any] | None:
            if not include_system:
                return self._system_info
            return await self._optional_json(SYSTEM_PATH, "UniFi OS system metadata")

        network_io, device_info, system_data = await asyncio.gather(
            self._optional_json(NETWORK_IO_PATH, "UniFi Drive network I/O metadata"),
            self._optional_json(
                DRIVE_DEVICE_INFO_PATH, "UniFi Drive device-info metadata"
            ),
            _system_metadata(),
        )

        if system_data is not None:
            self._system_info = system_data
            data["_system"] = system_data
        if network_io is not None:
            data["_network_io"] = network_io
        if device_info is not None:
            data["_device_info"] = device_info
        return data
