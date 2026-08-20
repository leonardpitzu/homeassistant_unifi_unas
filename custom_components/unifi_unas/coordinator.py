"""Data coordinator for the UniFi Drive integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UnifiUnasApiClient
from .api.errors import (
    CannotConnect,
    InvalidAuth,
    UnexpectedResponse,
    UnsupportedFeature,
)
from .const import (
    CONF_FAN_CONTROL_ENABLED,
    CONF_SNAPSHOT_BUTTONS_ENABLED,
    DEFAULT_FAN_CONTROL_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNAPSHOT_BUTTONS_ENABLED,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .entry_options import entry_bool, entry_int
from .entry_reload import EntryReloadSignature
from .security import safe_error_text
from .snapshot.inventory import (
    SNAPSHOT_INVENTORY_REASON_CONNECTION,
    SNAPSHOT_INVENTORY_REASON_PERMISSION,
    SNAPSHOT_INVENTORY_REASON_UNEXPECTED_RESPONSE,
    SNAPSHOT_INVENTORY_REASON_UNKNOWN,
    SNAPSHOT_INVENTORY_REASON_UNSUPPORTED,
)
from .snapshot.repairs import (
    async_clear_snapshot_issues,
    async_create_snapshot_read_issue,
    async_update_snapshot_read_issue,
)
from .snapshot.types import snapshot_target_key, snapshot_target_type

if TYPE_CHECKING:
    from .runtime import UnifiDriveConfigEntry

_LOGGER = logging.getLogger(__name__)
_SNAPSHOT_INVENTORY_UNAVAILABLE_MARKER = "not available on this system"
_SNAPSHOT_INVENTORY_REFRESH_INTERVAL = timedelta(minutes=10)
_CONNECTION_FAILURES_BEFORE_OFFLINE = 2
# Firmware versions, fan mode, backup tasks and snapshot settings only change on
# user action, so they are polled on their own slower cadence.
_SLOW_REFRESH_INTERVAL = timedelta(minutes=10)
_OPTIONAL_REFRESH_BUDGET_RATIO = 0.5
_MIN_OPTIONAL_REFRESH_BUDGET = 10.0


class UnifiUnasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate polling of UniFi Drive storage data."""

    config_entry: UnifiDriveConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: UnifiUnasApiClient,
        entry: UnifiDriveConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.config_entry = entry
        self.fan_control_enabled = entry_bool(
            entry,
            CONF_FAN_CONTROL_ENABLED,
            DEFAULT_FAN_CONTROL_ENABLED,
        )
        self.snapshot_buttons_enabled = entry_bool(
            entry,
            CONF_SNAPSHOT_BUTTONS_ENABLED,
            DEFAULT_SNAPSHOT_BUTTONS_ENABLED,
        )
        self.is_device_online = True
        self.fan_mode: str | None = None
        self.backup_tasks: list[dict[str, Any]] = []
        self.snapshot_settings: list[dict[str, Any]] = []
        self.snapshot_inventory: dict[str, dict[str, Any]] = {}
        self.snapshot_inventory_errors: dict[str, str] = {}
        self.snapshot_inventory_skip_reasons: dict[str, str] = {}
        self.snapshot_target_missing_counts: dict[str, dict[str, Any]] = {}
        self.entry_reload_signature: EntryReloadSignature | None = None
        self._connection_failure_count = 0
        self._connection_transient_logged = False
        self._connection_offline_logged = False
        self._snapshot_inventory_last_refresh: datetime | None = None
        self._snapshot_inventory_refresh_requested = False
        self._snapshot_inventory_target_keys: set[str] = set()
        self._first_refresh_core_only = False
        self._last_slow_refresh: datetime | None = None
        self._slow_refresh_requested = False
        interval = entry_int(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        interval = max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, interval))

        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

    async def async_config_entry_first_refresh(self) -> None:
        """Fetch core data first so entities can be registered quickly."""
        self._first_refresh_core_only = True
        try:
            await super().async_config_entry_first_refresh()
        finally:
            self._first_refresh_core_only = False

    async def async_refresh_optional_features(self) -> None:
        """Refresh optional local endpoints after core entities exist."""
        if not isinstance(self.data, dict):
            return

        await self._async_refresh_optional_features(include_slow=True)
        self._mark_slow_refreshed(datetime.now(UTC))
        self.async_set_updated_data(self.data)

    async def async_request_refresh(self) -> None:
        """Refresh everything: an explicit request follows a user action."""
        self.request_slow_refresh()
        await super().async_request_refresh()

    def request_slow_refresh(self) -> None:
        """Force the next poll to include the slow-changing endpoints."""
        self._slow_refresh_requested = True

    def _slow_refresh_due(self, now: datetime) -> bool:
        """Return whether the slow-changing endpoints should be polled again.

        The pending request is consumed up front so a request raised while the
        poll is in flight survives for the next one.
        """
        due = (
            self._slow_refresh_requested
            or self._last_slow_refresh is None
            or now - self._last_slow_refresh >= _SLOW_REFRESH_INTERVAL
        )
        if due:
            self._slow_refresh_requested = False
        return due

    def _mark_slow_refreshed(self, now: datetime) -> None:
        """Record that the slow-changing endpoints were just polled."""
        self._last_slow_refresh = now

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch storage data from the UNAS."""
        now = datetime.now(UTC)
        slow_due = self._slow_refresh_due(now)
        try:
            storage = await self.client.async_get_storage(refresh_system=slow_due)
            self._handle_connection_recovered()
            self._connection_failure_count = 0
            self.is_device_online = True
        except CannotConnect as err:
            return self._handle_connection_failure(err)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("Invalid UniFi Drive credentials") from err
        except UnexpectedResponse as err:
            raise UpdateFailed(safe_error_text(err)) from err

        if self._first_refresh_core_only:
            return storage

        # Optional endpoints must never make a poll outrun its own interval.
        budget = max(
            _MIN_OPTIONAL_REFRESH_BUDGET,
            self.update_interval.total_seconds() * _OPTIONAL_REFRESH_BUDGET_RATIO
            if self.update_interval
            else _MIN_OPTIONAL_REFRESH_BUDGET,
        )
        try:
            async with asyncio.timeout(budget):
                await self._async_refresh_optional_features(include_slow=slow_due)
        except TimeoutError:
            _LOGGER.debug(
                "Optional UniFi Drive endpoints exceeded the %.0fs refresh budget",
                budget,
            )

        if slow_due:
            self._mark_slow_refreshed(now)
        return storage

    async def _async_refresh_optional_features(self, *, include_slow: bool) -> None:
        """Refresh optional endpoints without blocking core storage data.

        Fan mode, backup tasks and snapshot settings only change on user action,
        so they ride the slow tier instead of every core poll.
        """
        if not self.snapshot_buttons_enabled:
            self._clear_snapshot_settings_state()

        if not include_slow:
            return

        # Deliberately sequential. Gathering these adds an event-loop suspension
        # that reorders Home Assistant's entity setup during the first refresh.
        await self._refresh_fan_mode()
        await self._refresh_backup_tasks()
        if self.snapshot_buttons_enabled:
            await self._refresh_snapshot_settings()

    def _handle_connection_recovered(self) -> None:
        """Log once when polling recovers after a connection failure."""
        if self._connection_offline_logged:
            _LOGGER.info("UniFi Drive connection restored")
        self._connection_transient_logged = False
        self._connection_offline_logged = False

    def _handle_connection_failure(self, err: CannotConnect) -> dict[str, Any]:
        """Return cached data during tolerated connection failures."""
        message = safe_error_text(err)
        cached_data = self.data if isinstance(self.data, dict) else None
        if cached_data is None:
            self.is_device_online = False
            self._connection_failure_count = _CONNECTION_FAILURES_BEFORE_OFFLINE
            raise UpdateFailed(message) from err

        self._connection_failure_count += 1
        if self._should_keep_cached_data_online():
            if not self._connection_transient_logged:
                _LOGGER.debug(
                    "UniFi Drive storage poll failed once, keeping device "
                    "online with last known data: %s",
                    message,
                )
                self._connection_transient_logged = True
            return cached_data

        self.is_device_online = False
        if not self._connection_offline_logged:
            _LOGGER.warning(
                "UniFi Drive is unavailable, keeping last known data: %s",
                message,
            )
            self._connection_offline_logged = True
        return self._with_offline_status(cached_data)

    def _should_keep_cached_data_online(self) -> bool:
        """Return whether a transient failure should keep the device online."""
        return (
            self.is_device_online
            and self._connection_failure_count < _CONNECTION_FAILURES_BEFORE_OFFLINE
        )

    async def _refresh_fan_mode(self) -> None:
        """Refresh fan mode without treating optional endpoint failures as fatal."""
        if not self.fan_control_enabled:
            return
        if self.client.fan_mode_read_supported is False:
            return

        try:
            mode = await self.client.async_get_fan_mode()
        except (CannotConnect, InvalidAuth, UnexpectedResponse, UnsupportedFeature) as err:
            _LOGGER.debug(
                "Could not read UniFi Drive fan mode: %s",
                safe_error_text(err),
            )
            return

        if mode:
            self.fan_mode = mode

    async def _refresh_backup_tasks(self) -> None:
        """Refresh backup tasks while tolerating optional API gaps."""
        if self.client.backup_tasks_read_supported is False:
            return
        try:
            self.backup_tasks = await self.client.async_get_backup_tasks()
        except (CannotConnect, InvalidAuth, UnexpectedResponse, UnsupportedFeature) as err:
            _LOGGER.debug(
                "Could not read UniFi Drive backup tasks: %s",
                safe_error_text(err),
            )
            self.backup_tasks = []

    async def _refresh_snapshot_settings(self) -> None:
        """Refresh snapshot settings and trigger inventory refresh if possible.

        Deliberately not gated on `snapshot_settings_read_supported`: this call
        also drives the snapshot repair-issue lifecycle.
        """
        try:
            self.snapshot_settings = await self.client.async_get_snapshot_settings()
        except (
            CannotConnect,
            InvalidAuth,
            UnexpectedResponse,
            UnsupportedFeature,
        ) as err:
            # Snapshot settings and inventory are optional features.
            _LOGGER.debug(
                "Could not read UniFi Drive snapshot settings: %s",
                safe_error_text(err),
            )
            if not isinstance(err, CannotConnect):
                async_create_snapshot_read_issue(self.hass, self.config_entry, err)
            self._clear_snapshot_settings_state(clear_issues=False)
            return

        await self._async_refresh_snapshot_inventory_if_due()
        async_update_snapshot_read_issue(
            self.hass,
            self.config_entry,
            supported=self.client.snapshot_settings_read_supported,
        )

    def _clear_snapshot_settings_state(self, *, clear_issues: bool = True) -> None:
        """Clear cached snapshot state and optionally clear snapshot repairs."""
        self.snapshot_settings = []
        self.snapshot_inventory = {}
        self.snapshot_inventory_errors = {}
        self.snapshot_inventory_skip_reasons = {}
        self._snapshot_inventory_target_keys = set()
        self._snapshot_inventory_last_refresh = None
        self._snapshot_inventory_refresh_requested = False
        if clear_issues:
            async_clear_snapshot_issues(self.hass, self.config_entry)

    def request_snapshot_inventory_refresh(self) -> None:
        """Force the next coordinator refresh to read snapshot inventory."""
        self._snapshot_inventory_refresh_requested = True
        self.request_slow_refresh()

    async def _async_refresh_snapshot_inventory_if_due(self) -> None:
        """Refresh snapshot inventory on a slower cadence than storage polling."""
        active_target_keys = self._snapshot_inventory_active_target_keys()
        if active_target_keys != self._snapshot_inventory_target_keys:
            self._snapshot_inventory_refresh_requested = True
            self._snapshot_inventory_target_keys = active_target_keys

        self._prune_snapshot_inventory_state(active_target_keys)
        now = datetime.now(UTC)
        if not self._snapshot_inventory_refresh_due(now):
            return

        refresh_requested = self._snapshot_inventory_refresh_requested
        if refresh_requested:
            self._snapshot_inventory_refresh_requested = False
        try:
            self.snapshot_inventory = await self._async_get_snapshot_inventory(active_target_keys)
        except (RuntimeError, TypeError, ValueError) as err:
            if refresh_requested:
                self._snapshot_inventory_refresh_requested = True
            _LOGGER.debug(
                "Unexpected error while refreshing snapshot inventory: %s",
                safe_error_text(err),
            )
            self._snapshot_inventory_last_refresh = now
            return

        self._snapshot_inventory_last_refresh = now

    def _snapshot_inventory_refresh_due(self, now: datetime) -> bool:
        """Return whether snapshot inventory should be read now."""
        if self._snapshot_inventory_refresh_requested:
            return True
        if self._snapshot_inventory_last_refresh is None:
            return True
        return now - self._snapshot_inventory_last_refresh >= (
            _SNAPSHOT_INVENTORY_REFRESH_INTERVAL
        )

    def _snapshot_inventory_active_target_keys(self) -> set[str]:
        """Return valid snapshot target keys from the current settings payload."""
        active_target_keys: set[str] = set()
        for target in self.snapshot_settings:
            if not isinstance(target, dict):
                continue
            target_key = snapshot_target_key(target)
            if target_key:
                active_target_keys.add(target_key)
        return active_target_keys

    def _prune_snapshot_inventory_state(self, active_target_keys: set[str]) -> None:
        """Drop cached snapshot inventory state for targets no longer advertised."""
        self.snapshot_inventory = {
            target_key: inventory
            for target_key, inventory in self.snapshot_inventory.items()
            if target_key in active_target_keys
        }
        self.snapshot_inventory_errors = {
            target_key: reason
            for target_key, reason in self.snapshot_inventory_errors.items()
            if target_key in active_target_keys
        }
        self.snapshot_inventory_skip_reasons = {
            target_key: reason
            for target_key, reason in self.snapshot_inventory_skip_reasons.items()
            if target_key in active_target_keys
        }

    async def _async_get_snapshot_inventory(
        self, active_target_keys: set[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Return inventory summaries keyed by stable snapshot target key."""
        if active_target_keys is None:
            active_target_keys = self._snapshot_inventory_active_target_keys()
        inventory: dict[str, dict[str, Any]] = {}
        inventory_errors: dict[str, str] = {}
        snapshot_inventory_supported_by_type = _snapshot_inventory_type_support_map(
            self.client
        )
        pending: list[tuple[str, dict[str, Any], str | None]] = []
        for target in self.snapshot_settings:
            if not isinstance(target, dict):
                continue
            target_key = snapshot_target_key(target)
            if not target_key:
                continue
            if skip_reason := self.snapshot_inventory_skip_reasons.get(target_key):
                inventory_errors[target_key] = skip_reason
                continue
            target_type = snapshot_target_type(target)
            if _snapshot_inventory_type_is_unsupported(
                snapshot_inventory_supported_by_type,
                target_type,
            ):
                reason = SNAPSHOT_INVENTORY_REASON_UNSUPPORTED
                inventory_errors[target_key] = reason
                self.snapshot_inventory_skip_reasons[target_key] = reason
                continue
            pending.append((target_key, target, target_type))

        # Deliberately sequential: gathering these reorders Home Assistant's
        # entity setup, and the inventory read is already throttled to 10 min.
        for pending_key, pending_target, pending_type in pending:
            try:
                inventory[pending_key] = (
                    await self.client.async_get_snapshot_inventory_target(pending_target)
                )
                self.snapshot_inventory_skip_reasons.pop(pending_key, None)
            except (
                CannotConnect,
                InvalidAuth,
                UnexpectedResponse,
                UnsupportedFeature,
            ) as err:
                inventory_errors[pending_key] = _snapshot_inventory_error_reason(err)
                if _snapshot_inventory_read_should_be_skipped(err):
                    self.snapshot_inventory_skip_reasons[pending_key] = (
                        inventory_errors[pending_key]
                    )
                _LOGGER.debug(
                    "Could not read UniFi Drive snapshot inventory for %s: %s",
                    pending_type,
                    safe_error_text(err),
                )
            except (RuntimeError, TypeError, ValueError) as err:
                inventory_errors[pending_key] = _snapshot_inventory_error_reason(err)
                _LOGGER.debug(
                    "Unexpectedly failed to read snapshot inventory for %s: %s",
                    pending_type,
                    safe_error_text(err),
                )

        self.snapshot_inventory_skip_reasons = {
            target_key: reason
            for target_key, reason in self.snapshot_inventory_skip_reasons.items()
            if target_key in active_target_keys
        }
        self.snapshot_inventory_errors = inventory_errors
        return inventory

    @staticmethod
    def _with_offline_status(data: dict[str, Any]) -> dict[str, Any]:
        """Return a defensive shallow copy with `_system.status=offline`."""
        payload = dict(data)
        system = payload.get("_system")
        if not isinstance(system, dict):
            system = {}
        else:
            system = dict(system)
        payload["_system"] = system
        system["status"] = "offline"
        return payload


def _snapshot_inventory_read_should_be_skipped(err: Exception) -> bool:
    """Return whether an inventory read error should be treated as sticky."""
    if isinstance(err, InvalidAuth):
        return True
    if isinstance(err, UnsupportedFeature):
        return _snapshot_inventory_error_text_has_unavailable_marker(err)
    return False


def _snapshot_inventory_type_support_map(client: object) -> dict[str, bool]:
    """Return a validated snapshot inventory support map from a client."""
    support_map = getattr(client, "snapshot_inventory_supported_by_type", {})
    if not isinstance(support_map, dict):
        _LOGGER.debug(
            "Ignoring invalid snapshot inventory support cache type for client %s",
            type(client).__name__,
        )
        return {}

    validated: dict[str, bool] = {}
    for key, value in support_map.items():
        if isinstance(key, str) and isinstance(value, bool):
            validated[key] = value
    if len(validated) != len(support_map):
        _LOGGER.debug(
            "Ignoring malformed snapshot inventory support cache entries for client %s",
            type(client).__name__,
        )
    return validated


def _snapshot_inventory_type_is_unsupported(
    snapshot_inventory_supported_by_type: Mapping[str, bool],
    target_type: str,
) -> bool:
    """Return whether snapshot inventory reads should be skipped for the target type."""
    if snapshot_inventory_supported_by_type.get(target_type) is False:
        return True
    return (
        target_type == "mydrive"
        and snapshot_inventory_supported_by_type.get("personal") is False
    )


def _snapshot_inventory_error_text_has_unavailable_marker(err: Exception) -> bool:
    """Return whether an error message contains the unsupported snapshot marker."""
    message = safe_error_text(err).lower()
    return _SNAPSHOT_INVENTORY_UNAVAILABLE_MARKER in message


def _snapshot_inventory_error_reason(err: Exception) -> str:
    """Return a stable user-facing category for inventory read failures."""
    if isinstance(err, InvalidAuth):
        return SNAPSHOT_INVENTORY_REASON_PERMISSION
    if isinstance(err, UnsupportedFeature):
        if _snapshot_inventory_error_text_has_unavailable_marker(err):
            return SNAPSHOT_INVENTORY_REASON_UNSUPPORTED
        return SNAPSHOT_INVENTORY_REASON_UNEXPECTED_RESPONSE
    if isinstance(err, CannotConnect):
        return SNAPSHOT_INVENTORY_REASON_CONNECTION
    if isinstance(err, UnexpectedResponse):
        return SNAPSHOT_INVENTORY_REASON_UNEXPECTED_RESPONSE
    return SNAPSHOT_INVENTORY_REASON_UNKNOWN
