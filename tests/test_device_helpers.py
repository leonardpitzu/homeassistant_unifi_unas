"""Unit tests for Home Assistant device metadata helpers."""

from __future__ import annotations

import types

from custom_components.unifi_unas import device as device_module


class _FakeClient:
    base_url = "https://unas.local"


class _FakeCoordinator:
    client = _FakeClient()
    data = {
        "_system": {
            "hardware": {
                "shortname": "UNAS2",
                "name": "UniFi Drive UNAS",
                "firmwareVersion": "5.0.17",
            }
        }
    }


class _FakeEntry:
    title = "Keller"


def test_device_info_uses_dynamic_model_and_firmware_version() -> None:
    """DeviceInfo should reflect UniFi OS hardware metadata when available."""
    info = device_module.build_device_info(_FakeCoordinator(), _FakeEntry(), "dev-1")

    assert info["model"] == "UNAS2"
    assert info["sw_version"] == "5.0.17"
    assert info["name"] == "Keller"
    assert info["configuration_url"] == "https://unas.local"


def test_device_info_falls_back_to_hardware_name_and_ucore_version() -> None:
    """DeviceInfo should keep useful metadata when shortname/firmware are absent."""
    coordinator = types.SimpleNamespace(
        client=types.SimpleNamespace(base_url="https://backup.local"),
        data={
            "_system": {
                "ucore_version": "5.1.0",
                "hardware": {
                    "shortname": "",
                    "name": "UniFi Drive Backup",
                    "firmwareVersion": "",
                },
            }
        },
    )

    info = device_module.build_device_info(
        coordinator,
        _FakeEntry(),
        "backup-user",
        configuration_url="https://override.local",
    )

    assert info["identifiers"] == {("unifi_unas", "backup-user")}
    assert info["model"] == "UniFi Drive Backup"
    assert info["sw_version"] == "5.1.0"
    assert info["configuration_url"] == "https://override.local"


def test_device_info_uses_raw_system_payload_version_fields() -> None:
    """DeviceInfo should accept system metadata that is not nested under _system."""
    coordinator = types.SimpleNamespace(
        client=types.SimpleNamespace(base_url="https://raw.local"),
        data={
            "hardware": {"shortname": "UNAS2W"},
            "firmware_version": "5.1.10",
        },
    )

    info = device_module.build_device_info(coordinator, _FakeEntry(), "raw-system")

    assert info["model"] == "UNAS2W"
    assert info["sw_version"] == "5.1.10"


def test_device_info_uses_client_cached_system_metadata() -> None:
    """Fresh installs should keep firmware metadata when only the client has it."""
    coordinator = types.SimpleNamespace(
        client=types.SimpleNamespace(
            base_url="https://cached.local",
            _system_info={
                "hardware": {
                    "shortname": "UNAS2W",
                    "firmwareVersion": "5.1.10",
                }
            },
        ),
        data={"pools": []},
    )

    info = device_module.build_device_info(coordinator, _FakeEntry(), "cached-system")

    assert info["model"] == "UNAS2W"
    assert info["sw_version"] == "5.1.10"


def test_device_info_uses_default_model_without_system_payload() -> None:
    """DeviceInfo should remain stable while the device is offline."""
    coordinator = types.SimpleNamespace(
        client=types.SimpleNamespace(base_url=None),
        data=None,
    )

    info = device_module.build_device_info(coordinator, _FakeEntry(), "offline-entry")

    assert info["identifiers"] == {("unifi_unas", "offline-entry")}
    assert info["model"] == "UniFi Drive / UNAS"
    assert "sw_version" not in info
    assert info["configuration_url"] is None
