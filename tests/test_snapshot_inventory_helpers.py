"""Unit tests for snapshot inventory payload helpers."""

from __future__ import annotations

from custom_components.unifi_unas.snapshot import inventory as snapshot_inventory_module


def test_snapshot_inventory_error_sticky_reason_helper() -> None:
    """Only permanent inventory failures should become sticky."""
    assert snapshot_inventory_module.snapshot_inventory_error_is_sticky("permission")
    assert snapshot_inventory_module.snapshot_inventory_error_is_sticky("unsupported")
    assert not snapshot_inventory_module.snapshot_inventory_error_is_sticky(
        "unexpected_response"
    )
    assert not snapshot_inventory_module.snapshot_inventory_error_is_sticky(None)


def test_snapshot_inventory_extracts_nested_snapshot_lists() -> None:
    """Inventory parsing should accept common nested list wrappers."""
    payload = {
        "data": {
            "items": [
                {
                    "snapshotId": "new",
                    "displayName": "New snapshot",
                    "isLocked": "true",
                    "createdAt": "2026-05-16T12:00:00Z",
                },
                {
                    "snapshotId": "old",
                    "displayName": "Old snapshot",
                    "isLocked": "false",
                    "createdAt": "2026-05-15T12:00:00+00:00",
                },
            ]
        }
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory == {
        "snapshot_count": 2,
        "snapshot_count_source": "inventory_items",
        "returned_snapshot_count": 2,
        "locked_count": 1,
        "inventory_total": None,
        "inventory_offset": None,
        "inventory_limit": None,
        "latest_snapshot_time": "2026-05-16T12:00:00Z",
        "oldest_snapshot_time": "2026-05-15T12:00:00Z",
        "latest_snapshot_id": "new",
        "oldest_snapshot_id": "old",
        "latest_snapshot_name": "New snapshot",
        "oldest_snapshot_name": "Old snapshot",
        "latest_snapshot_description": None,
        "oldest_snapshot_description": None,
        "snapshot_ids": ["new", "old"],
        "snapshot_names": ["New snapshot", "Old snapshot"],
        "snapshot_descriptions": [],
        "snapshot_metadata_truncated": False,
        "snapshot_metadata_limit": 10,
        "recent_snapshots": [
            {
                "id": "new",
                "name": "New snapshot",
                "description": None,
                "locked": True,
                "created_at": "2026-05-16T12:00:00Z",
            },
            {
                "id": "old",
                "name": "Old snapshot",
                "description": None,
                "locked": False,
                "created_at": "2026-05-15T12:00:00Z",
            },
        ],
        "recent_snapshot_count": 2,
        "recent_snapshot_limit": 10,
        "inventory_truncated": False,
    }


def test_snapshot_inventory_accepts_epoch_milliseconds() -> None:
    """Numeric UniFi timestamp variants should become stable UTC ISO strings."""
    payload = {
        "snapshots": [
            {"id": "a", "locked": 0, "timestamp": 1_778_932_800_000},
            {"id": "b", "locked": 1, "timestamp": 1_778_844_000},
        ]
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory["locked_count"] == 1
    assert inventory["latest_snapshot_id"] == "a"
    assert inventory["oldest_snapshot_id"] == "b"
    assert inventory["latest_snapshot_time"] == "2026-05-16T12:00:00Z"


def test_snapshot_inventory_uses_collection_total_for_state_count() -> None:
    """Collection metadata should expose total count and paging details."""
    payload = {
        "data": [
            {
                "id": "new",
                "description": "Before maintenance",
                "locked": False,
                "createdAt": "2026-05-16T12:00:00+02:00",
            },
            {
                "id": "old",
                "description": "",
                "locked": "true",
                "createdAt": "2026-05-15T12:00:00+02:00",
            },
        ],
        "offset": 0,
        "limit": 2,
        "total": 12,
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory["snapshot_count"] == 12
    assert inventory["snapshot_count_source"] == "inventory_total"
    assert inventory["returned_snapshot_count"] == 2
    assert inventory["inventory_total"] == 12
    assert inventory["inventory_offset"] == 0
    assert inventory["inventory_limit"] == 2
    assert inventory["inventory_truncated"] is True
    assert inventory["latest_snapshot_description"] == "Before maintenance"
    assert inventory["snapshot_descriptions"] == ["Before maintenance"]
    assert inventory["snapshot_metadata_truncated"] is True
    assert inventory["recent_snapshots"][0] == {
        "id": "new",
        "name": None,
        "description": "Before maintenance",
        "locked": False,
        "created_at": "2026-05-16T10:00:00Z",
    }


def test_snapshot_inventory_recent_list_keeps_undated_items() -> None:
    """Mixed dated and undated payloads should keep every returned item."""
    payload = {
        "items": [
            {"id": "undated-first"},
            {"id": "new", "createdAt": "2026-05-16T12:00:00Z"},
            {"id": "undated-last"},
            {"id": "old", "createdAt": "2026-05-15T12:00:00Z"},
        ]
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory["snapshot_count"] == 4
    assert inventory["returned_snapshot_count"] == 4
    assert inventory["recent_snapshot_count"] == 4
    assert inventory["inventory_truncated"] is False
    assert [item["id"] for item in inventory["recent_snapshots"]] == [
        "new",
        "old",
        "undated-first",
        "undated-last",
    ]


def test_snapshot_inventory_limits_retained_snapshot_metadata() -> None:
    """Snapshot metadata retained in HA state should have a hard upper bound."""
    payload = {
        "snapshots": [
            {
                "id": f"snap-{index:02d}",
                "name": f"Snapshot {index:02d}",
                "description": f"Description {index:02d}",
                "createdAt": f"2026-05-{index + 1:02d}T12:00:00Z",
            }
            for index in range(12)
        ]
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory["snapshot_count"] == 12
    assert inventory["returned_snapshot_count"] == 12
    assert inventory["snapshot_metadata_limit"] == 10
    assert inventory["snapshot_metadata_truncated"] is True
    assert len(inventory["snapshot_ids"]) == 10
    assert len(inventory["snapshot_names"]) == 10
    assert len(inventory["snapshot_descriptions"]) == 10
    assert len(inventory["recent_snapshots"]) == 10
    assert inventory["snapshot_ids"][0] == "snap-11"
    assert inventory["snapshot_ids"][-1] == "snap-02"


def test_snapshot_inventory_falls_back_to_payload_order_without_dates() -> None:
    """Undated inventory payloads should still expose counts and IDs."""
    payload = {
        "records": [
            {"uuid": "first", "name": "First"},
            {"uuid": "last", "name": "Last"},
        ]
    }

    inventory = snapshot_inventory_module.extract_snapshot_inventory(payload)

    assert inventory["snapshot_count"] == 2
    assert inventory["latest_snapshot_id"] == "first"
    assert inventory["oldest_snapshot_id"] == "last"
    assert inventory["latest_snapshot_time"] is None
    assert inventory["recent_snapshots"][0]["id"] == "first"


def test_snapshot_inventory_ignores_unknown_payload_shapes() -> None:
    """Unexpected payload shapes should produce an empty inventory summary."""
    assert snapshot_inventory_module.extract_snapshot_inventory({"ok": True}) == {
        "snapshot_count": 0,
        "snapshot_count_source": "inventory_items",
        "returned_snapshot_count": 0,
        "locked_count": 0,
        "inventory_total": None,
        "inventory_offset": None,
        "inventory_limit": None,
        "latest_snapshot_time": None,
        "oldest_snapshot_time": None,
        "latest_snapshot_id": None,
        "oldest_snapshot_id": None,
        "latest_snapshot_name": None,
        "oldest_snapshot_name": None,
        "latest_snapshot_description": None,
        "oldest_snapshot_description": None,
        "snapshot_ids": [],
        "snapshot_names": [],
        "snapshot_descriptions": [],
        "snapshot_metadata_truncated": False,
        "snapshot_metadata_limit": 10,
        "recent_snapshots": [],
        "recent_snapshot_count": 0,
        "recent_snapshot_limit": 10,
        "inventory_truncated": False,
    }
