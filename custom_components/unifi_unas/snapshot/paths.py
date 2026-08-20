"""Endpoint path helpers for UniFi Drive snapshot operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .api_errors import UnexpectedResponse
from .snapshot_types import snapshot_target_type

SNAPSHOT_ENDPOINT_UNAVAILABLE_HTTP_STATUSES = {404, 405}
SNAPSHOT_SETTINGS_PATH = "/proxy/drive/api/v1/systems/snapshot"
SNAPSHOT_SETTING_PERSONAL_PATH = (
    "/proxy/drive/api/v1/snapshot-settings/personal/{target_id}"
)
SNAPSHOT_SETTING_SHARED_PATH = (
    "/proxy/drive/api/v1/snapshot-settings/shared/{target_id}"
)
SHARED_DRIVE_SNAPSHOTS_PATH = "/proxy/drive/api/v1/snapshots/shared/{shared_drive_name}"
PERSONAL_DRIVE_SNAPSHOTS_PATH = "/proxy/drive/api/v1/snapshots/personal/{target_id}"


def _snapshot_settings_write_paths(target: Any) -> tuple[str, ...]:
    """Return likely write endpoint paths for a snapshot target."""
    target_data = target if isinstance(target, Mapping) else {}
    target_type = snapshot_target_type(target_data)
    if not target_type:
        raise UnexpectedResponse("Snapshot target type is missing")

    target_id = str(target_data.get("user_id") or target_data.get("id") or "").strip()
    if not target_id:
        raise UnexpectedResponse("Snapshot target id is missing")

    if target_type == "mydrive":
        return (
            SNAPSHOT_SETTING_PERSONAL_PATH.format(
                target_id=quote(target_id, safe="")
            ),
        )

    if target_type == "shared":
        paths = []
        shared_drive_name = str(target_data.get("shared_drive_name") or "").strip()
        if shared_drive_name and shared_drive_name != target_id:
            paths.append(
                SNAPSHOT_SETTING_SHARED_PATH.format(
                    target_id=quote(shared_drive_name, safe="")
                )
            )
        paths.append(
            SNAPSHOT_SETTING_SHARED_PATH.format(
                target_id=quote(target_id, safe="")
            )
        )
        return tuple(paths)

    raise UnexpectedResponse(f"Unsupported snapshot target type: {target_type}")


def _snapshot_create_paths(target: Any) -> tuple[str, ...]:
    """Return likely snapshot creation paths for a target."""
    target_data = target if isinstance(target, Mapping) else {}
    target_type = snapshot_target_type(target_data)
    if not target_type:
        raise UnexpectedResponse("Snapshot target type is missing")

    if target_type == "shared":
        paths: list[str] = []
        shared_drive_name = str(target_data.get("shared_drive_name") or "").strip()
        target_id = str(target_data.get("id") or "").strip()
        if shared_drive_name:
            paths.append(
                SHARED_DRIVE_SNAPSHOTS_PATH.format(
                    shared_drive_name=quote(shared_drive_name, safe="")
                )
            )
        if target_id and target_id != shared_drive_name:
            paths.append(
                SHARED_DRIVE_SNAPSHOTS_PATH.format(
                    shared_drive_name=quote(target_id, safe="")
                )
            )
        if not paths:
            raise UnexpectedResponse("Snapshot target id is missing")
        return tuple(paths)

    if target_type == "mydrive":
        target_id = str(
            target_data.get("user_id") or target_data.get("id") or ""
        ).strip()
        if not target_id:
            raise UnexpectedResponse("Snapshot target id is missing")
        return (
            PERSONAL_DRIVE_SNAPSHOTS_PATH.format(
                target_id=quote(target_id, safe="")
            ),
        )

    raise UnexpectedResponse(f"Unsupported snapshot target type: {target_type}")


def _snapshot_inventory_paths(target: Any) -> tuple[str, ...]:
    """Return likely read endpoints for a target's snapshot inventory."""
    return _snapshot_create_paths(target)
