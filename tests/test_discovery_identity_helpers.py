"""Tests for discovery identity persistence behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.unifi_unas.discovery import identity as discovery_identity_module

CONF_DISCOVERY_LAST_SEEN = discovery_identity_module.CONF_DISCOVERY_LAST_SEEN


def test_should_write_discovery_identity_update_throttles_recent_last_seen_only_changes() -> (
    None
):
    """Discovery metadata writes should be throttled when nothing changed except last-seen."""
    existing = {
        "host": "unas.local",
        "discovery_last_seen": "2026-05-22T10:00:00Z",
        "discovery_identity_source": "validated_system",
    }
    now = datetime(2026, 5, 22, 10, 3, 0, tzinfo=UTC)
    incoming = {
        **existing,
        CONF_DISCOVERY_LAST_SEEN: "2026-05-22T10:03:00Z",
    }

    assert not discovery_identity_module.should_write_discovery_identity_update(
        existing=existing,
        incoming=incoming,
        now=now,
        update_interval=timedelta(minutes=5),
    )


def test_should_write_discovery_identity_update_runs_on_metadata_change() -> None:
    """Discovery metadata changes should force an immediate config-entry write."""
    existing = {
        "discovery_last_seen": "2026-05-22T10:00:00Z",
        "discovery_identity_source": "validated_system",
    }
    now = datetime(2026, 5, 22, 10, 1, 0, tzinfo=UTC)
    incoming = {
        "discovery_last_seen": "2026-05-22T10:01:00Z",
        "discovery_identity_source": "discovery_mac",
    }

    assert discovery_identity_module.should_write_discovery_identity_update(
        existing=existing,
        incoming=incoming,
        now=now,
        update_interval=timedelta(minutes=5),
    )


def test_should_write_discovery_identity_update_handles_invalid_timestamps() -> None:
    """Invalid discovery timestamp data should prefer durability by writing once."""
    existing = {"discovery_last_seen": "not-a-timestamp"}
    now = datetime(2026, 5, 22, 10, 1, 0, tzinfo=UTC)
    incoming = {
        "discovery_last_seen": "2026-05-22T10:01:00Z",
        "discovery_host_aliases": ["192.0.2.50"],
    }

    assert discovery_identity_module.should_write_discovery_identity_update(
        existing=existing,
        incoming=incoming,
        now=now,
    )
