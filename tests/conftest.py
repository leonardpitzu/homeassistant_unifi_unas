"""Pytest collection setup for the UniFi Drive test suite."""

from __future__ import annotations

import sys
from importlib.util import find_spec

import pytest

HA_BACKED_TEST_FILES = {
    "test_control_entity_states.py",
    "test_core_monitoring_entity_states.py",
    "test_integration_entry_setup.py",
    "test_snapshot_control_entity_states.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Prepare the Home Assistant pytest plugin before tests run."""
    _skip_ha_backed_tests_without_plugin(items)
    _prime_homeassistant_plugin_modules()


def _skip_ha_backed_tests_without_plugin(items: list[pytest.Item]) -> None:
    """Skip HA-backed tests when the Home Assistant pytest plugin is unavailable."""
    if find_spec("pytest_homeassistant_custom_component") is not None:
        return

    skip = pytest.mark.skip(
        reason="HA-backed tests require pytest-homeassistant-custom-component"
    )
    for item in items:
        if item.path.name in HA_BACKED_TEST_FILES:
            item.add_marker(skip)


def _prime_homeassistant_plugin_modules() -> None:
    """Import HA modules that pytest-homeassistant patches by dotted path."""
    try:
        import homeassistant.helpers.aiohttp_client
        import homeassistant.util.logging
    except ModuleNotFoundError:
        return

    _bind_parent_modules("homeassistant.helpers.aiohttp_client")
    _bind_parent_modules("homeassistant.util.logging")


def _bind_parent_modules(module_name: str) -> None:
    """Expose imported submodules as attributes on their parent packages."""
    parts = module_name.split(".")
    for index in range(1, len(parts)):
        parent_name = ".".join(parts[:index])
        child_name = ".".join(parts[: index + 1])
        parent = sys.modules.get(parent_name)
        child = sys.modules.get(child_name)
        if parent is not None and child is not None:
            setattr(parent, parts[index], child)
