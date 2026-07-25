"""Constants for the Philips HomeRun (Local) integration."""

from __future__ import annotations

DOMAIN = "homerun_local"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_FAN_SPEEDS = "fan_speeds"

DEFAULT_PORT = 8787
DEFAULT_FAN_SPEEDS = ["quiet", "normal", "strong", "max"]

# How often the coordinator polls GET /api/state
UPDATE_INTERVAL_SECONDS = 5

# Platforms forwarded from the config entry
PLATFORMS = ["vacuum", "sensor", "select", "switch", "number", "button", "camera"]

MANUFACTURER = "Philips"
MODEL = "HomeRun XU7100"

# Water tank levels (backend enum -> friendly label)
WATER_LEVELS = {"closed": "Off", "low": "Low", "middle": "Medium", "high": "High"}
