"""System action operations for the UniFi Drive API client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .api_errors import InvalidAuth
from .const import POWEROFF_PATH, REBOOT_PATH

_LOGGER = logging.getLogger(__name__)


class ApiSystemMixin:
    """Power/reboot operations split from the main API client class."""

    _authenticated: bool

    if TYPE_CHECKING:
        @property
        def poweroff_permission_hint(self) -> bool | None: ...
        async def _ensure_authenticated(self) -> None: ...
        async def async_login(self) -> None: ...
        async def _request_no_json(self, method: str, path: str) -> None: ...

    async def async_poweroff(self) -> None:
        """Power off the UniFi OS console / UNAS."""
        await self._async_system_power_action(POWEROFF_PATH, "poweroff")

    async def async_reboot(self) -> None:
        """Reboot the UniFi OS console / UNAS."""
        await self._async_system_power_action(REBOOT_PATH, "reboot")

    async def _async_system_power_action(self, path: str, action: str) -> None:
        """Run a UniFi OS system power action."""
        await self._ensure_authenticated()
        permission_hint = self.poweroff_permission_hint
        if permission_hint is False:
            raise InvalidAuth(
                f"The configured UniFi account does not advertise {action} permission"
            )

        try:
            await self._request_no_json("POST", path)
        except InvalidAuth as err:
            _LOGGER.debug("UNAS session expired before %s; retrying login once", action)
            self._authenticated = False
            await self.async_login()
            permission_hint = self.poweroff_permission_hint
            if permission_hint is False:
                raise InvalidAuth(
                    f"The configured UniFi account does not advertise {action} permission"
                ) from err
            await self._request_no_json("POST", path)
