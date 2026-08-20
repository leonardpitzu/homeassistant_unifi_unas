"""Exceptions used by the UniFi Drive API client."""

from __future__ import annotations


class UnifiUnasApiError(Exception):
    """Base exception for UniFi Drive errors."""


class CannotConnect(UnifiUnasApiError):
    """Raised when the UNAS cannot be reached."""


class InvalidAuth(UnifiUnasApiError):
    """Raised when authentication fails or the account lacks permission."""


class UnexpectedResponse(UnifiUnasApiError):
    """Raised when the API returns unexpected data."""


class UnsupportedFeature(UnifiUnasApiError):
    """Raised when a requested local endpoint is not available."""
