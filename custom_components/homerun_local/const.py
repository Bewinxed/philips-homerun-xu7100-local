"""Constants for the Philips HomeRun (Local) integration."""

from __future__ import annotations

DOMAIN = "homerun_local"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "api_token"
CONF_FAN_SPEEDS = "fan_speeds"

DEFAULT_PORT = 8787
# Only used when the backend doesn't report the model's own suction levels
DEFAULT_FAN_SPEEDS = ["gentle", "normal", "strong", "max"]

# How often the coordinator polls GET /api/state
UPDATE_INTERVAL_SECONDS = 5

# Platforms forwarded from the config entry
PLATFORMS = ["vacuum", "sensor", "select", "switch", "number", "button", "camera", "time", "text"]

MANUFACTURER = "Philips"
MODEL = "HomeRun"

# Water tank levels (backend enum -> friendly label); levels the model reports
# that aren't listed here are shown title-cased
WATER_LEVELS = {"closed": "Off", "low": "Low", "middle": "Medium", "high": "High"}

# Cleaning settings of a schedule, as in the app's "Schoonmaakmethode"
# (backend schedule.py; values from the robot's thing model)
SCHEDULE_SETTINGS: dict[str, list[str]] = {
    "mode": ["both_work", "only_sweep", "only_mop", "intensive", "quiet"],
    "suction": ["closed", "gentle", "normal", "strong", "max"],
    "water": ["closed", "low", "middle", "high"],
    "repeat": ["1", "2", "5"],
}
