"""Config flow for the Philips HomeRun (Local) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HomeRunApiClient, HomeRunApiError
from .const import (
    CONF_FAN_SPEEDS,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_FAN_SPEEDS,
    DEFAULT_PORT,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class HomeRunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Philips HomeRun (Local)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: ask for host + port and validate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = HomeRunApiClient(session, host, port)
            try:
                await client.async_get_state()
            except HomeRunApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Philips HomeRun ({host})",
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow to edit the fan speed list."""
        return HomeRunOptionsFlow()


class HomeRunOptionsFlow(OptionsFlow):
    """Allow editing the list of fan speeds exposed to Home Assistant."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            raw = user_input.get(CONF_FAN_SPEEDS, "")
            speeds = [s.strip() for s in raw.split(",") if s.strip()]
            return self.async_create_entry(
                data={CONF_FAN_SPEEDS: speeds or DEFAULT_FAN_SPEEDS}
            )

        current = self.config_entry.options.get(CONF_FAN_SPEEDS, DEFAULT_FAN_SPEEDS)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FAN_SPEEDS,
                    default=", ".join(current),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
