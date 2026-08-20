"""Repairs issue helpers for UniFi Drive snapshot capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .api_errors import InvalidAuth
from .const import DOMAIN
from .security import safe_error_text
from .snapshot_types import normalize_snapshot_target_type, snapshot_target_slug

if TYPE_CHECKING:
    from .runtime import UnifiDriveConfigEntry

_SNAPSHOT_ISSUE_KINDS = ("permission", "unavailable")
_SNAPSHOT_TARGET_TYPES = ("shared", "mydrive")
_SNAPSHOT_ACTIONS = ("create", "settings")


def async_create_snapshot_read_issue(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    err: Exception,
) -> None:
    """Create a repairs issue for snapshot target discovery failures."""
    if hass is None:
        return

    kind = _issue_kind_from_error(err)
    _create_snapshot_issue(
        hass,
        entry,
        capability="read",
        kind=kind,
        error=safe_error_text(err),
    )


def async_update_snapshot_read_issue(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    *,
    supported: bool | None,
) -> None:
    """Sync repairs state after a snapshot target read attempt."""
    if hass is None:
        return

    if supported is True:
        _clear_snapshot_issue_kinds(hass, entry, capability="read")
    elif supported is False:
        _create_snapshot_issue(
            hass,
            entry,
            capability="read",
            kind="unavailable",
            error="Snapshot settings endpoint is not available on this system.",
        )


def async_create_snapshot_action_issue(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    *,
    action: str,
    target: dict[str, Any],
    err: Exception,
) -> None:
    """Create a repairs issue for snapshot create/settings action failures."""
    if hass is None:
        return

    target_type = _snapshot_issue_target_type(target)
    _create_snapshot_issue(
        hass,
        entry,
        capability=action,
        kind=_issue_kind_from_error(err),
        target_type=target_type,
        target_name=_snapshot_issue_target_name(target),
        error=safe_error_text(err),
    )


def async_clear_snapshot_action_issues(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    *,
    action: str,
    target: dict[str, Any],
) -> None:
    """Clear repairs issues for a snapshot action after a successful call."""
    if hass is None:
        return

    _clear_snapshot_issue_kinds(
        hass,
        entry,
        capability=action,
        target_type=_snapshot_issue_target_type(target),
    )


def async_update_snapshot_target_missing_issue(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    *,
    target_key: str,
    target_name: str,
    target_type: str | None,
    missing_count: int,
    threshold: int,
) -> None:
    """Sync repairs state for a snapshot target that disappeared."""
    if hass is None:
        return

    issue_id = _snapshot_target_missing_issue_id(entry, target_key)
    if missing_count < threshold:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="snapshot_target_missing",
        translation_placeholders={
            "entry_title": str(getattr(entry, "title", "") or entry.entry_id),
            "target_type": _target_type_label(target_type),
            "target_name": target_name,
            "missing_count": str(missing_count),
        },
    )


def async_clear_snapshot_target_missing_issue(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
    *,
    target_key: str,
) -> None:
    """Clear a missing-target repairs issue when the target returns."""
    if hass is None:
        return

    ir.async_delete_issue(
        hass,
        DOMAIN,
        _snapshot_target_missing_issue_id(entry, target_key),
    )


def async_clear_snapshot_issues(
    hass: HomeAssistant | None,
    entry: UnifiDriveConfigEntry,
) -> None:
    """Clear all snapshot repairs for an entry."""
    if hass is None:
        return

    _clear_snapshot_issue_kinds(hass, entry, capability="read")
    for action in _SNAPSHOT_ACTIONS:
        _clear_snapshot_issue_kinds(hass, entry, capability=action)
        for target_type in _SNAPSHOT_TARGET_TYPES:
            _clear_snapshot_issue_kinds(
                hass,
                entry,
                capability=action,
                target_type=target_type,
            )


def _create_snapshot_issue(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    *,
    capability: str,
    kind: str,
    error: str,
    target_type: str | None = None,
    target_name: str | None = None,
) -> None:
    """Create a translated Home Assistant repairs issue."""
    _clear_other_snapshot_issue_kinds(
        hass,
        entry,
        capability=capability,
        kind=kind,
        target_type=target_type,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _snapshot_issue_id(entry, capability, kind, target_type=target_type),
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=_snapshot_translation_key(capability, kind),
        translation_placeholders={
            "entry_title": str(getattr(entry, "title", "") or entry.entry_id),
            "target_type": _target_type_label(target_type),
            "target_name": target_name or _target_type_label(target_type),
            "error": _short_error(error),
        },
    )


def _clear_other_snapshot_issue_kinds(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    *,
    capability: str,
    kind: str,
    target_type: str | None = None,
) -> None:
    """Clear stale issue variants before creating the current one."""
    for existing_kind in _SNAPSHOT_ISSUE_KINDS:
        if existing_kind == kind:
            continue
        ir.async_delete_issue(
            hass,
            DOMAIN,
            _snapshot_issue_id(
                entry,
                capability,
                existing_kind,
                target_type=target_type,
            ),
        )


def _clear_snapshot_issue_kinds(
    hass: HomeAssistant,
    entry: UnifiDriveConfigEntry,
    *,
    capability: str,
    target_type: str | None = None,
) -> None:
    """Clear both permission and availability variants for one capability."""
    for kind in _SNAPSHOT_ISSUE_KINDS:
        ir.async_delete_issue(
            hass,
            DOMAIN,
            _snapshot_issue_id(entry, capability, kind, target_type=target_type),
        )


def _snapshot_issue_id(
    entry: UnifiDriveConfigEntry,
    capability: str,
    kind: str,
    *,
    target_type: str | None = None,
) -> str:
    """Return a stable repairs issue id for one snapshot capability."""
    issue_id = f"{entry.entry_id}_snapshot_{capability}"
    if target_type:
        issue_id = f"{issue_id}_{target_type}"
    return f"{issue_id}_{kind}"


def _snapshot_target_missing_issue_id(
    entry: UnifiDriveConfigEntry,
    target_key: str,
) -> str:
    """Return a stable repairs issue id for a missing snapshot target."""
    return f"{entry.entry_id}_snapshot_target_{snapshot_target_slug(target_key)}_missing"


def _snapshot_translation_key(capability: str, kind: str) -> str:
    """Return the translation key for one snapshot issue."""
    if capability == "read":
        return f"snapshot_read_{kind}"
    return f"snapshot_{capability}_{kind}"


def _issue_kind_from_error(err: Exception) -> str:
    """Return whether an error should be presented as permission or capability."""
    return "permission" if isinstance(err, InvalidAuth) else "unavailable"


def _snapshot_issue_target_type(target: Mapping[str, Any]) -> str | None:
    """Return a normalized target type for issue ids and labels."""
    if not isinstance(target, Mapping):
        return None

    target_type = normalize_snapshot_target_type(target.get("type"))
    return target_type if target_type in _SNAPSHOT_TARGET_TYPES else None


def _snapshot_issue_target_name(target: Mapping[str, Any]) -> str:
    """Return a user-facing snapshot target name."""
    if not isinstance(target, Mapping):
        return "snapshot target"

    target_id = str(target.get("id", "")).strip()
    return str(target.get("name") or target.get("shared_drive_name") or target_id)


def _target_type_label(target_type: str | None) -> str:
    """Return a concise user-facing target type label."""
    if target_type == "mydrive":
        return "My Drive"
    if target_type == "shared":
        return "Shared Drive"
    return "snapshot target"


def _short_error(error: str) -> str:
    """Keep repairs placeholders useful without flooding the UI."""
    return safe_error_text(error)
