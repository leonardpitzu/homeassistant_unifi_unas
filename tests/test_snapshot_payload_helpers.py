"""Unit tests for snapshot payload helpers."""

from typing import Any

from custom_components.unifi_unas.snapshot import payload as snapshot_payload_module


def test_snapshot_target_type_uses_aliases_and_shape_detection() -> None:
    """List payloads should resolve target type using aliases and key hints."""
    assert (
        snapshot_payload_module._snapshot_target_type(
            {"type": "personal", "id": "user-1"}
        )
        == "mydrive"
    )
    assert (
        snapshot_payload_module._snapshot_target_type(
            {"targetType": "shared_drive", "sharedDrive": {"id": "shared-1"}}
        )
        == "shared"
    )
    assert (
        snapshot_payload_module._snapshot_target_type(
            {"user": {"id": "user-1"}, "id": "user-1"}
        )
        == "mydrive"
    )


def test_snapshot_target_type_invalid_payload_returns_none() -> None:
    """Malformed payload entries should return no target type instead of raising."""
    assert snapshot_payload_module._snapshot_target_type("bad-entry") is None
    assert snapshot_payload_module._snapshot_target_type(None) is None


def test_snapshot_target_type_normalized_returns_empty_on_invalid_payload() -> None:
    """Normalization helper should stay robust on non-mapping target objects."""
    assert snapshot_payload_module._snapshot_target_type_normalized("bad-entry") == ""
    assert snapshot_payload_module._snapshot_target_type_normalized(None) == ""


def test_extract_snapshot_settings_skips_invalid_list_items() -> None:
    """Non-dict list entries in snapshot payloads must be ignored."""
    payload: dict[str, Any] = {
        "data": [
            None,
            "invalid",
            {"sharedDriveName": "Team", "type": "shared"},
            {"user": {"id": "user-1", "firstName": "Alex"}, "targetName": "Alex"},
            {"foo": 123, "type": "mydrive"},
        ]
    }

    settings = snapshot_payload_module.extract_snapshot_settings(payload)
    assert len(settings) == 2
    assert settings[0]["type"] == "shared"
    assert settings[0]["id"] == "Team"
    assert settings[0]["name"] == "Team"
    assert settings[1]["type"] == "mydrive"
    assert settings[1]["id"] == "user-1"
    assert settings[1]["name"] == "Alex"
