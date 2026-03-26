"""Config flow for iAqualink HPM integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

import homeassistant.config_entries as config_entries
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from . import async_get_systems
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _map_auth_error(err: Exception) -> str:
    """Map iaqualink exceptions to config flow error keys."""
    err_name = err.__class__.__name__
    err_text = str(err).lower()
    err_repr = repr(err).lower()

    if err_name == "AqualinkAuthenticationException":
        return "invalid_auth"

    if err_name == "AqualinkApiConnectionException":
        return "cannot_connect"

    if err_name == "AqualinkServiceException":
        # iaqualink can surface credential/login failures as HTTP 400/401 service errors.
        if (
            "401" in err_text
            or "403" in err_text
            or "unauthorized" in err_text
            or "invalid token" in err_text
            or "invalid credentials" in err_text
        ):
            return "invalid_auth"
        return "cannot_connect"

    # Fallback for wrapped/renamed service errors coming from dependency changes.
    if "aqualinkserviceexception" in err_repr:
        if (
            "401" in err_text
            or "403" in err_text
            or "unauthorized" in err_text
            or "invalid token" in err_text
            or "invalid credentials" in err_text
        ):
            return "invalid_auth"
        return "cannot_connect"

    if "invalid credentials" in err_text or "401" in err_text:
        return "invalid_auth"

    if "not a supported system type" in err_text:
        return "no_systems"

    return "unknown"


class AqualinkHpmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iAqualink HPM."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return AqualinkHpmOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                username = user_input[CONF_USERNAME].strip()
                masked_username = (
                    f"{username[:2]}***@{username.split('@', 1)[1]}"
                    if "@" in username
                    else f"{username[:2]}***"
                )
                _LOGGER.debug("Config flow auth started for user=%s", masked_username)
                systems = await async_get_systems(
                    self.hass,
                    username,
                    user_input[CONF_PASSWORD],
                    hpm_only=True,
                )
            except Exception as err:  # noqa: BLE001
                errors["base"] = _map_auth_error(err)
                if errors["base"] == "unknown":
                    _LOGGER.exception(
                        "Unexpected error during iAqualink auth (type=%s): %s",
                        err.__class__.__name__,
                        err,
                    )
                else:
                    _LOGGER.warning(
                        "iAqualink auth failed with mapped error '%s' (type=%s): %s",
                        errors["base"],
                        err.__class__.__name__,
                        err,
                    )
            else:
                _LOGGER.debug("Config flow auth returned %s HPM systems", len(systems))
                if systems:
                    await self.async_set_unique_id(username)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"iAqualink Heat Pump ({username})",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                errors["base"] = "unknown"
                if not systems:
                    errors["base"] = "no_systems"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class AqualinkHpmOptionsFlow(config_entries.OptionsFlow):
    """Handle iAqualink HPM options (scan interval)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
