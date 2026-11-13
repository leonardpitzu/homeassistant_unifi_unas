"""Minimal async client for the local UniFi OS / UniFi Drive HTTP API."""

from __future__ import annotations

import asyncio
from ipaddress import IPv6Address, ip_address
from typing import Any

from aiohttp import ClientError, ClientSession

LOGIN_PATH = "/api/auth/login"
SYSTEM_PATH = "/api/system"
REBOOT_PATH = "/api/system/reboot"
POWEROFF_PATH = "/api/system/poweroff"
STORAGE_PATH = "/proxy/drive/api/v2/storage"
DEVICE_INFO_PATH = "/proxy/drive/api/v2/systems/device-info"
NETWORK_IO_PATH = "/proxy/drive/api/v2/systems/network-io"
FAN_CONTROL_PATH = "/proxy/drive/api/v2/systems/fan-control"

REQUEST_TIMEOUT = 15


class UnifiDriveError(Exception):
    """Base error for the UniFi Drive client."""


class CannotConnect(UnifiDriveError):
    """The device could not be reached or answered with a server error."""


class InvalidAuth(UnifiDriveError):
    """Credentials were rejected or lack permission for the endpoint."""


def base_url(host: str, port: int, use_ssl: bool) -> str:
    """Return the console base URL, bracketing IPv6 literals."""
    host = host.strip().strip("/").strip("[]")
    try:
        if isinstance(ip_address(host), IPv6Address):
            host = f"[{host}]"
    except ValueError:
        pass
    scheme = "https" if use_ssl else "http"
    default_port = 443 if use_ssl else 80
    return f"{scheme}://{host}" if port == default_port else f"{scheme}://{host}:{port}"


class UnifiDriveClient:
    """Talk to one UniFi Drive console with an API key or a local account."""

    def __init__(
        self,
        session: ClientSession,
        url: str,
        *,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = False,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.url = url
        self._api_key = (api_key or "").strip() or None
        self._username = (username or "").strip()
        self._password = password or ""
        # A local account wins when both are configured: it can also reach the
        # UniFi OS core endpoints (power actions) that Drive API keys cannot.
        self._use_account = bool(self._username and self._password)
        if not self._use_account and not self._api_key:
            raise InvalidAuth("An API key or a username and password is required")
        self._ssl = verify_ssl if url.startswith("https") else True
        self._token: str | None = None
        self._csrf: str | None = None
        self._login_lock = asyncio.Lock()

    async def async_get_system(self) -> dict[str, Any]:
        """Return the UniFi OS system document (readable without auth)."""
        return await self._get(SYSTEM_PATH)

    async def async_get_storage(self) -> dict[str, Any]:
        """Return the Drive storage document (pools, disks, cache slots)."""
        return await self._get(STORAGE_PATH)

    async def async_get_device_info(self) -> dict[str, Any]:
        """Return Drive device info (cpu, memory, versions, startup time)."""
        return await self._get(DEVICE_INFO_PATH)

    async def async_get_network_io(self) -> dict[str, Any]:
        """Return Drive network throughput."""
        return await self._get(NETWORK_IO_PATH)

    async def async_get_fan_control(self) -> dict[str, Any]:
        """Return the fan-control document."""
        return await self._get(FAN_CONTROL_PATH)

    async def async_set_fan_profile(self, profile: str) -> None:
        """Set the fan profile (API value, e.g. ``quiet``)."""
        await self._request("PUT", FAN_CONTROL_PATH, {"profile": profile})

    async def async_reboot(self) -> None:
        """Reboot the console."""
        await self._request("POST", REBOOT_PATH)

    async def async_poweroff(self) -> None:
        """Power the console off."""
        await self._request("POST", POWEROFF_PATH)

    async def _get(self, path: str) -> dict[str, Any]:
        data = await self._request("GET", path)
        if not isinstance(data, dict):
            raise CannotConnect(f"Expected a JSON object from {path}")
        return data

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """Send one request, logging in (again) once when a session expires."""
        if self._use_account and self._token is None:
            await self._async_login()
        try:
            return await self._send(method, path, body)
        except InvalidAuth:
            if not self._use_account:
                raise
            self._token = None
            await self._async_login()
            return await self._send(method, path, body)

    async def _send(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        headers = {"Accept": "application/json"}
        if self._use_account:
            if self._token:
                headers["Cookie"] = f"TOKEN={self._token}"
            if self._csrf:
                headers["X-CSRF-Token"] = self._csrf
        else:
            headers["X-API-Key"] = self._api_key or ""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, self.url + path, json=body, headers=headers, ssl=self._ssl
                ) as resp:
                    if csrf := resp.headers.get("X-Updated-CSRF-Token") or resp.headers.get("X-CSRF-Token"):
                        self._csrf = csrf
                    if resp.status in (401, 403):
                        raise InvalidAuth(f"{path} returned HTTP {resp.status}")
                    if resp.status >= 400:
                        raise CannotConnect(f"{path} returned HTTP {resp.status}")
                    if resp.content_type != "application/json":
                        await resp.read()
                        return None
                    return await resp.json()
        except (TimeoutError, ClientError) as err:
            raise CannotConnect(f"{method} {path} failed: {type(err).__name__}") from err

    async def _async_login(self) -> None:
        """Log in with the local account and keep the TOKEN cookie."""
        async with self._login_lock:
            if self._token is not None:
                return
            payload = {"username": self._username, "password": self._password, "rememberMe": True}
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    async with self._session.post(
                        self.url + LOGIN_PATH,
                        json=payload,
                        headers={"Accept": "application/json"},
                        ssl=self._ssl,
                    ) as resp:
                        if resp.status in (400, 401, 403):
                            raise InvalidAuth("Invalid username or password")
                        if resp.status >= 400:
                            raise CannotConnect(f"Login returned HTTP {resp.status}")
                        self._csrf = resp.headers.get("X-Updated-CSRF-Token") or resp.headers.get(
                            "X-CSRF-Token", self._csrf
                        )
                        # Parse the raw header: UniFi's cookie attributes are not
                        # always accepted by aiohttp's cookie parser.
                        for raw in resp.headers.getall("Set-Cookie", []):
                            name, _, value = raw.split(";", 1)[0].strip().partition("=")
                            if name == "TOKEN" and value:
                                self._token = value
                                break
                        else:
                            raise InvalidAuth("Login did not return a session token")
            except (TimeoutError, ClientError) as err:
                raise CannotConnect(f"Login failed: {type(err).__name__}") from err
