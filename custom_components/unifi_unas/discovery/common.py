"""Shared discovery normalization helpers."""

from __future__ import annotations

from ipaddress import IPv6Address, ip_address
from typing import Any

from .discovery_identity import discovery_host_key, discovery_mac_key


def clean_text(value: Any) -> str | None:
    """Return stripped text for non-empty values."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value).strip()
    return text or None


def clean_host_label(value: Any) -> str | None:
    """Return a readable host label without a trailing DNS root dot."""
    text = clean_text(value)
    return text.rstrip(".") if text else None


def parse_bool(value: Any) -> bool | None:
    """Return a bool for common discovery truthy/falsey values."""
    if isinstance(value, bool):
        return value
    text = clean_text(value)
    if text is None:
        return None
    if text.lower() in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text.lower() in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def device_key(host: str, hw_addr: str | None) -> str:
    """Return a stable selection key for a discovered device."""
    if mac_key := discovery_mac_key(hw_addr):
        return f"mac:{mac_key}"
    return f"host:{discovery_host_key(host)}"


def mac_from_eui64_ipv6(value: Any) -> str | None:
    """Return a MAC address from a link-local IPv6 EUI-64 address."""
    try:
        address = ip_address(value)
    except (TypeError, ValueError):
        text = clean_text(value)
        if text is None:
            return None
        text = text.strip("[]").split("%", 1)[0]
        try:
            address = ip_address(text)
        except ValueError:
            return None

    if not isinstance(address, IPv6Address) or not address.is_link_local:
        return None

    identifier = address.packed[-8:]
    if identifier[3:5] != b"\xff\xfe":
        return None

    mac = bytes(
        (
            identifier[0] ^ 0x02,
            identifier[1],
            identifier[2],
            identifier[5],
            identifier[6],
            identifier[7],
        )
    )
    return ":".join(f"{octet:02x}" for octet in mac)
