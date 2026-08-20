"""Translatable exception helpers for UniFi Drive user-facing actions."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN


def unifi_unas_error(
    message: str,
    translation_key: str,
    **placeholders: str,
) -> HomeAssistantError:
    """Return a translatable Home Assistant error with a fallback message."""
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=placeholders or None,
    )


def unifi_unas_validation_error(
    message: str,
    translation_key: str,
    **placeholders: str,
) -> ServiceValidationError:
    """Return a translatable service validation error with a fallback message."""
    return ServiceValidationError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=placeholders or None,
    )
