"""Unit tests for config entry data/options helpers."""

from types import SimpleNamespace

from custom_components.unifi_unas import entry_options


def test_entry_value_prefers_options_over_data() -> None:
    """Runtime feature settings should be able to move to entry.options."""
    entry = SimpleNamespace(
        data={"scan_interval": 30, "fan_control_enabled": True},
        options={"scan_interval": 120, "fan_control_enabled": False},
    )

    assert entry_options.entry_int(entry, "scan_interval", 30) == 120
    assert entry_options.entry_bool(entry, "fan_control_enabled", True) is False


def test_entry_value_falls_back_to_data_and_defaults() -> None:
    """Connection and identity settings should still be readable from data."""
    entry = SimpleNamespace(data={"wol_mac_address": "aa:bb:cc:dd:ee:ff"})

    assert entry_options.entry_str(entry, "wol_mac_address") == "aa:bb:cc:dd:ee:ff"
    assert entry_options.entry_value(entry, "missing", "fallback") == "fallback"


def test_entry_int_uses_default_for_corrupted_values() -> None:
    """Corrupted stored option values should not break runtime setup."""
    entry = SimpleNamespace(
        data={"scan_interval": 30},
        options={"scan_interval": "not-an-integer"},
    )

    assert entry_options.entry_int(entry, "scan_interval", 30) == 30


def test_merged_entry_data_options_layers_options_for_form_defaults() -> None:
    """Reconfigure feature defaults should reflect option overrides."""
    entry = SimpleNamespace(
        data={"scan_interval": 30, "host": "unas.local"},
        options={"scan_interval": 120},
    )

    assert entry_options.merged_entry_data_options(entry) == {
        "host": "unas.local",
        "scan_interval": 120,
    }


def test_feature_options_from_data_keeps_only_runtime_feature_settings() -> None:
    """Feature reconfigure should not move identity/auth fields into options."""
    data = {
        "host": "unas.local",
        "username": "user",
        "scan_interval": 120,
        "fan_control_enabled": False,
        "snapshot_buttons_enabled": True,
        "wol_enabled": True,
        "wol_mac_address": "aa:bb:cc:dd:ee:ff",
        "wol_broadcast_address": "192.0.2.255",
        "wol_port": 9,
    }

    assert entry_options.feature_options_from_data(data) == {
        "scan_interval": 120,
        "fan_control_enabled": False,
        "snapshot_buttons_enabled": True,
        "wol_enabled": True,
        "wol_mac_address": "aa:bb:cc:dd:ee:ff",
        "wol_broadcast_address": "192.0.2.255",
        "wol_port": 9,
    }


def test_data_without_feature_options_removes_runtime_settings() -> None:
    """Migrated entry data should keep only connection/auth settings."""
    assert entry_options.data_without_feature_options(
        {
            "host": "unas.local",
            "username": "user",
            "scan_interval": 120,
            "wol_enabled": True,
        }
    ) == {
        "host": "unas.local",
        "username": "user",
    }


def test_entry_data_from_data_keeps_only_connection_settings() -> None:
    """New entry data should not include feature or unrelated option settings."""
    assert entry_options.entry_data_from_data(
        {
            "host": "unas.local",
            "port": 443,
            "ssl": True,
            "verify_ssl": False,
            "username": "user",
            "password": "secret",
            "api_key": "token",
            "scan_interval": 120,
            "unrelated_option": "skip",
        }
    ) == {
        "host": "unas.local",
        "port": 443,
        "ssl": True,
        "verify_ssl": False,
        "username": "user",
        "password": "secret",
        "api_key": "token",
    }


def test_merged_entry_data_updates_connection_settings_without_copying_options() -> None:
    """Connection reconfigure should not copy arbitrary options into entry data."""
    entry = SimpleNamespace(
        data={
            "host": "old.local",
            "port": 443,
            "legacy_data": "keep",
            "scan_interval": 30,
        },
        options={
            "scan_interval": 120,
            "future_option": "stay-in-options",
        },
    )

    assert entry_options.merged_entry_data_with_connection_updates(
        entry,
        {
            "host": "new.local",
            "port": 8443,
            "ssl": True,
            "verify_ssl": False,
            "username": "user",
            "password": "secret",
            "api_key": "token",
            "scan_interval": 120,
            "future_option": "do-not-copy",
        },
    ) == {
        "host": "new.local",
        "port": 8443,
        "legacy_data": "keep",
        "ssl": True,
        "verify_ssl": False,
        "username": "user",
        "password": "secret",
        "api_key": "token",
    }


def test_feature_options_from_entry_returns_current_options_only() -> None:
    """Reauth should preserve current options without importing old entry data."""
    entry = SimpleNamespace(
        data={
            "scan_interval": 30,
            "fan_control_enabled": True,
            "host": "unas.local",
        },
        options={
            "scan_interval": 120,
            "unrelated_option": "keep",
        },
    )

    assert entry_options.feature_options_from_entry(entry) == {
        "scan_interval": 120,
        "unrelated_option": "keep",
    }


def test_merged_feature_options_replaces_stale_option_overrides() -> None:
    """Reconfigure feature writes should update existing option keys."""
    entry = SimpleNamespace(
        options={
            "scan_interval": 30,
            "wol_enabled": True,
            "unrelated_option": "keep",
        }
    )
    data = {
        "scan_interval": 120,
        "wol_enabled": False,
        "host": "unas.local",
    }

    assert entry_options.merged_feature_options(entry, data) == {
        "scan_interval": 120,
        "wol_enabled": False,
        "unrelated_option": "keep",
    }
