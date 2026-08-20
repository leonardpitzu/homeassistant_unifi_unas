"""Unit tests for snapshot repairs issue helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.unifi_unas.snapshot import repairs as snapshot_repairs_module

_CREATED: list[dict] = []
_DELETED: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def _capture_issue_registry_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record issue-registry calls instead of touching a real registry."""

    def _create_issue(*args, **kwargs) -> None:
        _CREATED.append({"args": args, "kwargs": kwargs})

    def _delete_issue(hass, domain, issue_id) -> None:
        _DELETED.append((domain, issue_id))

    monkeypatch.setattr(
        snapshot_repairs_module.ir, "async_create_issue", _create_issue
    )
    monkeypatch.setattr(
        snapshot_repairs_module.ir, "async_delete_issue", _delete_issue
    )


class _FakeEntry:
    entry_id = "entry-1"
    title = "UNAS"


def setup_function() -> None:
    """Reset captured issue-registry calls."""
    _CREATED.clear()
    _DELETED.clear()


def test_snapshot_read_permission_issue_uses_translation_key() -> None:
    """Read auth failures should create a persistent permission repair."""
    snapshot_repairs_module.async_create_snapshot_read_issue(
        object(),
        _FakeEntry(),
        snapshot_repairs_module.InvalidAuth("missing snapshot read permission"),
    )

    issue = _CREATED[0]
    assert issue["args"][1:] == (
        snapshot_repairs_module.DOMAIN,
        "entry-1_snapshot_read_permission",
    )
    assert issue["kwargs"]["translation_key"] == "snapshot_read_permission"
    assert issue["kwargs"]["is_persistent"] is True
    assert issue["kwargs"]["translation_placeholders"]["entry_title"] == "UNAS"
    assert _DELETED == [
        (snapshot_repairs_module.DOMAIN, "entry-1_snapshot_read_unavailable")
    ]


def test_snapshot_read_success_clears_read_issue_variants() -> None:
    """A successful snapshot read should clear stale read repairs."""
    snapshot_repairs_module.async_update_snapshot_read_issue(
        object(),
        _FakeEntry(),
        supported=True,
    )

    assert _DELETED == [
        (snapshot_repairs_module.DOMAIN, "entry-1_snapshot_read_permission"),
        (snapshot_repairs_module.DOMAIN, "entry-1_snapshot_read_unavailable"),
    ]


def test_snapshot_action_unavailable_issue_is_scoped_by_type() -> None:
    """Action capability issues should be scoped to the failing target type."""
    snapshot_repairs_module.async_create_snapshot_action_issue(
        object(),
        _FakeEntry(),
        action="create",
        target={"id": "shared-1", "type": "shared", "name": "Team"},
        err=Exception("HTTP 404"),
    )

    issue = _CREATED[0]
    assert issue["args"][2] == "entry-1_snapshot_create_shared_unavailable"
    assert issue["kwargs"]["translation_key"] == "snapshot_create_unavailable"
    assert issue["kwargs"]["translation_placeholders"]["target_name"] == "Team"
    assert issue["kwargs"]["translation_placeholders"]["target_type"] == "Shared Drive"
    assert _DELETED == [
        (snapshot_repairs_module.DOMAIN, "entry-1_snapshot_create_shared_permission")
    ]


def test_snapshot_action_success_clears_target_type_issue_variants() -> None:
    """Successful actions should clear stale permission and unavailable repairs."""
    snapshot_repairs_module.async_clear_snapshot_action_issues(
        object(),
        _FakeEntry(),
        action="settings",
        target={"id": "user-1", "type": "mydrive", "name": "Backup User"},
    )

    assert _DELETED == [
        (
            snapshot_repairs_module.DOMAIN,
            "entry-1_snapshot_settings_mydrive_permission",
        ),
        (
            snapshot_repairs_module.DOMAIN,
            "entry-1_snapshot_settings_mydrive_unavailable",
        ),
    ]


def test_snapshot_target_missing_issue_waits_for_threshold() -> None:
    """Missing-target repairs should appear only after repeated misses."""
    snapshot_repairs_module.async_update_snapshot_target_missing_issue(
        object(),
        _FakeEntry(),
        target_key="shared_shared-1",
        target_name="Shared",
        target_type="shared",
        missing_count=2,
        threshold=3,
    )

    assert not _CREATED
    assert _DELETED == [
        (
            snapshot_repairs_module.DOMAIN,
            "entry-1_snapshot_target_shared_shared_1_missing",
        )
    ]

    snapshot_repairs_module.async_update_snapshot_target_missing_issue(
        object(),
        _FakeEntry(),
        target_key="shared_shared-1",
        target_name="Shared",
        target_type="shared",
        missing_count=3,
        threshold=3,
    )

    issue = _CREATED[0]
    assert issue["args"][2] == "entry-1_snapshot_target_shared_shared_1_missing"
    assert issue["kwargs"]["translation_key"] == "snapshot_target_missing"
    assert issue["kwargs"]["translation_placeholders"]["target_name"] == "Shared"
    assert issue["kwargs"]["translation_placeholders"]["missing_count"] == "3"


def test_snapshot_target_missing_success_clears_issue() -> None:
    """Returning snapshot targets should clear their missing-target repair."""
    snapshot_repairs_module.async_clear_snapshot_target_missing_issue(
        object(),
        _FakeEntry(),
        target_key="shared_shared-1",
    )

    assert _DELETED == [
        (
            snapshot_repairs_module.DOMAIN,
            "entry-1_snapshot_target_shared_shared_1_missing",
        )
    ]


def test_snapshot_action_issue_accepts_invalid_target_objects() -> None:
    """Invalid targets should degrade to neutral issue ids without crashing."""
    snapshot_repairs_module.async_create_snapshot_action_issue(
        object(),
        _FakeEntry(),
        action="settings",
        target="bad-target",
        err=Exception("temporary failure"),
    )

    issue = _CREATED[0]
    assert issue["args"][2] == "entry-1_snapshot_settings_unavailable"
    assert issue["kwargs"]["translation_placeholders"]["target_name"] == "snapshot target"
    assert issue["kwargs"]["translation_placeholders"]["target_type"] == "snapshot target"


def test_snapshot_unavailable_repair_text_explains_storage_is_unaffected() -> None:
    """Unavailable snapshot repair copy should make the blast radius clear."""
    root = Path(__file__).resolve().parents[1]
    unavailable_keys = {
        "snapshot_read_unavailable",
        "snapshot_create_unavailable",
        "snapshot_settings_unavailable",
        "snapshot_target_missing",
    }
    expected_sentences = (
        "This may be normal on this firmware or for this account.",
        "Storage monitoring is not affected.",
    )

    for path in (
        root / "custom_components" / "unifi_unas" / "strings.json",
        root / "custom_components" / "unifi_unas" / "translations" / "en.json",
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        issues = payload["issues"]
        for key in unavailable_keys:
            description = issues[key]["description"]
            for sentence in expected_sentences:
                assert sentence in description

    de_payload = json.loads(
        (
            root
            / "custom_components"
            / "unifi_unas"
            / "translations"
            / "de.json"
        ).read_text(encoding="utf-8")
    )
    for key in unavailable_keys:
        description = de_payload["issues"][key]["description"]
        assert "Firmware oder diesem Konto" in description
        assert "Speicherueberwachung ist nicht betroffen" in description
