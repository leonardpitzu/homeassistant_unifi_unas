"""Unit tests for translatable exception helpers."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.unifi_unas.const import DOMAIN
from custom_components.unifi_unas.exceptions import (
    unifi_unas_error,
    unifi_unas_validation_error,
)


def test_unifi_unas_error_carries_translation_metadata() -> None:
    """Action failures should reach the user through a translated message."""
    err = unifi_unas_error(
        "Could not run action",
        "system_action_failed",
        action="restart",
    )

    assert isinstance(err, HomeAssistantError)
    assert str(err) == "Could not run action"
    assert err.translation_domain == DOMAIN
    assert err.translation_key == "system_action_failed"
    assert err.translation_placeholders == {"action": "restart"}


def test_unifi_unas_validation_error_carries_translation_metadata() -> None:
    """Validation errors should preserve the same translation contract."""
    err = unifi_unas_validation_error("Device is offline", "device_offline")

    assert isinstance(err, ServiceValidationError)
    assert err.translation_domain == DOMAIN
    assert err.translation_key == "device_offline"
    assert err.translation_placeholders is None
