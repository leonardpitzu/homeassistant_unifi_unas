"""Constants for the UniFi Drive / UNAS integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "unifi_unas"
PLATFORMS: Final = (Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.SENSOR)

DEFAULT_PORT: Final = 443
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 3600

CONF_WOL_MAC: Final = "wol_mac_address"
CONF_WOL_BROADCAST: Final = "wol_broadcast_address"
CONF_WOL_PORT: Final = "wol_port"
DEFAULT_WOL_BROADCAST: Final = "255.255.255.255"
DEFAULT_WOL_PORT: Final = 9

# Fan profiles: HA option -> API value. Other API spellings map via FAN_ALIASES.
FAN_PROFILES: Final = {"Quiet": "quiet", "Balance": "default", "Cooling": "cooling"}
FAN_ALIASES: Final = {
    "quiet": "Quiet",
    "silent": "Quiet",
    "default": "Balance",
    "default_profile": "Balance",
    "balance": "Balance",
    "balanced": "Balance",
    "cooling": "Cooling",
    "cool": "Cooling",
}
