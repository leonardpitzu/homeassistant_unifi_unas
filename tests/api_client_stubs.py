"""Shared API test helpers."""

from custom_components.unifi_unas.api import UnifiUnasApiClient
from custom_components.unifi_unas.api import snapshot as api_snapshot_module
from custom_components.unifi_unas.snapshot import schedule as snapshot_schedule_module

__all__ = [
    "SnapshotStatusClient",
    "SnapshotWriteClient",
    "UnifiUnasApiClient",
    "api_snapshot_module",
    "snapshot_schedule_module",
]


class SnapshotWriteClient(api_snapshot_module.ApiSnapshotMixin):
    """Small fake client for testing snapshot write routing."""

    def __init__(self) -> None:
        """Initialize the fake client."""
        self._snapshot_settings_write_supported = None
        self._snapshot_settings_write_supported_by_type = {}
        self._snapshot_create_supported = None
        self._snapshot_create_supported_by_type = {}
        self._snapshot_inventory_supported = None
        self._snapshot_inventory_supported_by_type = {}
        self.calls = []
        self.responses = [(200, {"data": "OK"})]

    async def _ensure_authenticated(self) -> None:
        """No-op authentication stub for this pure routing test client."""
        return None

    async def _request_raw(self, method, path, *, json_body=None):
        """Record the outgoing request and return success."""
        self.calls.append((method, path, json_body))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class SnapshotStatusClient(api_snapshot_module.ApiSnapshotMixin):
    """Small fake client for testing snapshot endpoint status handling."""

    def __init__(self, status: int) -> None:
        """Initialize the fake client."""
        self._snapshot_settings_read_supported = None
        self._snapshot_create_supported = None
        self._snapshot_create_supported_by_type = {}
        self._snapshot_inventory_supported = None
        self._snapshot_inventory_supported_by_type = {}
        self.status = status
        self.calls = []

    async def _request_raw(self, method, path, *, json_body=None):
        """Record the outgoing request and return the configured status."""
        self.calls.append((method, path, json_body))
        return self.status, {"error": "not found"}
