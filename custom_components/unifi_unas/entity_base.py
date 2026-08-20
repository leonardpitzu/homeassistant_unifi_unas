"""Shared entity helpers for UniFi Drive platforms."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import UnifiUnasCoordinator
from .device import build_device_info
from .runtime import UnifiDriveConfigEntry

_UNRESOLVED: Final = object()


class UnifiUnasDeviceInfoMixin:
    """Mixin for entities that expose the dynamic UniFi Drive device."""

    coordinator: UnifiUnasCoordinator
    _entry: UnifiDriveConfigEntry
    _device_identifier: str

    def _set_device_context(self, entry: UnifiDriveConfigEntry) -> None:
        """Store config-entry context for device info and unique IDs."""
        self._entry = entry
        self._device_identifier = entry.unique_id or entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Build dynamic device info from the latest coordinator payload."""
        return build_device_info(
            self.coordinator,
            self._entry,
            self._device_identifier,
        )


class SnapshotResolvedMixin:
    """Mixin for entities that locate their slice of the coordinator payload.

    Home Assistant reads availability, state and attributes for every state
    write, so resolving per property walked the storage payload three times per
    entity per poll. Resolution is cached against the snapshot object it came
    from, which is sound because the coordinator only ever replaces
    ``data`` wholesale; the optional-feature refresh mutates coordinator
    attributes instead, so re-publishing the same object means the payload
    really is unchanged.
    """

    coordinator: UnifiUnasCoordinator
    _resolved_snapshot: Any = _UNRESOLVED
    _resolved_value: dict[str, Any] | None = None

    def _resolve(self) -> dict[str, Any] | None:
        """Look up this entity's payload slice in the current snapshot."""
        raise NotImplementedError

    def _resolved(self) -> dict[str, Any] | None:
        """Return this entity's payload slice for the current snapshot."""
        snapshot = self.coordinator.data
        if snapshot is not self._resolved_snapshot:
            self._resolved_snapshot = snapshot
            self._resolved_value = self._resolve()
        return self._resolved_value
