"""Unit tests for update endpoint handling in the API client."""

from __future__ import annotations

import asyncio

from custom_components.unifi_unas.api import UnifiUnasApiClient
from custom_components.unifi_unas.api.errors import UnsupportedFeature


def _run_update_once(status: int):
    client = UnifiUnasApiClient(None, host="unas.local")

    async def _fake_request_raw(*_args, **_kwargs):
        return status, {"status": status}

    client._request_raw = _fake_request_raw
    return asyncio.run(
        client._async_update_action_once("UniFi OS", "/api/firmware/update", {})
    )


def test_update_action_accepts_2xx() -> None:
    """2xx responses should be accepted."""
    _run_update_once(202)


def test_update_action_accepts_409_as_noop() -> None:
    """409 should be treated as already up-to-date."""
    _run_update_once(409)


def test_update_action_404_raises_unsupported_feature() -> None:
    """404 should map to UnsupportedFeature."""
    try:
        _run_update_once(404)
    except UnsupportedFeature:
        return
    raise AssertionError("Expected UnsupportedFeature for HTTP 404")


def test_update_action_405_raises_unsupported_feature() -> None:
    """405 should map to UnsupportedFeature."""
    try:
        _run_update_once(405)
    except UnsupportedFeature:
        return
    raise AssertionError("Expected UnsupportedFeature for HTTP 405")


def test_update_action_500_raises_unsupported_feature() -> None:
    """Other non-2xx codes should map to UnsupportedFeature."""
    try:
        _run_update_once(500)
    except UnsupportedFeature:
        return
    raise AssertionError("Expected UnsupportedFeature for HTTP 500")
