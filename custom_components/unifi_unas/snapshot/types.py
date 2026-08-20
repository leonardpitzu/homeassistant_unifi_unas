"""Snapshot target normalization helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .snapshot_inventory import snapshot_inventory_error_is_sticky


def normalize_snapshot_target_type(value: object) -> str:
    """Return the canonical snapshot target type string."""
    target_type = str(value or "").strip().lower()
    if target_type in {"mydrive", "my_drive", "personal", "user"}:
        return "mydrive"
    if target_type in {"shared", "shared_drive", "shareddrive"}:
        return "shared"
    return target_type


def snapshot_target_type(target: Mapping[str, Any]) -> str:
    """Return a normalized snapshot target type."""
    if not isinstance(target, Mapping):
        return ""
    return normalize_snapshot_target_type(target.get("type"))


def snapshot_target_key(target: Mapping[str, Any]) -> str:
    """Return a stable snapshot target key."""
    if not isinstance(target, Mapping):
        return ""
    target_type = snapshot_target_type(target)
    target_id = str(target.get("id", "")).strip()
    if not target_type or not target_id:
        return ""
    return f"{target_type}_{target_id}"


def snapshot_target_name(target: Mapping[str, Any]) -> str:
    """Return a display name for a snapshot target."""
    if not isinstance(target, Mapping):
        return "Snapshot Target"

    for field in ("name", "display_name", "shared_drive_name", "user_name"):
        value = target.get(field)
        if isinstance(value, str):
            value = value.strip()
        if value:
            return str(value)

    target_id = str(target.get("id", "")).strip()
    return target_id or "Snapshot Target"


def snapshot_target_slug(value: str) -> str:
    """Return a stable slug for snapshot entity unique-id suffixes."""
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_") or "target"


def snapshot_create_button_supported(
    target: Mapping[str, Any],
    *,
    inventory_available: bool = False,
    inventory_error_reason: str | None = None,
    preserve_inventory_unknown: bool = False,
) -> bool:
    """Return whether Home Assistant should expose manual snapshot creation."""
    target_type = snapshot_target_type(target)
    if target_type == "shared":
        return True
    if target_type == "mydrive":
        if bool(target.get("is_current_user")) or inventory_available:
            return True
        if snapshot_inventory_error_is_sticky(inventory_error_reason):
            return False
        return preserve_inventory_unknown
    return False


def snapshot_create_button_supported_for_inventory(
    target: Mapping[str, Any],
    *,
    snapshot_inventory: Mapping[str, object] | None = None,
    snapshot_inventory_errors: Mapping[str, str] | None = None,
    preserve_inventory_unknown: bool = True,
) -> bool:
    """Return whether a create button should be exposed with inventory context."""
    target_key = snapshot_target_key(target)
    if not target_key:
        return False

    snapshot_inventory = snapshot_inventory or {}
    snapshot_inventory_errors = snapshot_inventory_errors or {}
    return snapshot_create_button_supported(
        target,
        inventory_available=target_key in snapshot_inventory,
        inventory_error_reason=snapshot_inventory_errors.get(target_key),
        preserve_inventory_unknown=preserve_inventory_unknown,
    )
