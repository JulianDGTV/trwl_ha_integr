"""Config Flow für Träwelling."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TraewellingApi, TraewellingAuthError, TraewellingError
from .const import (
    CONF_ACTIVE_INTERVAL,
    CONF_BASE_URL,
    CONF_STATS_FROM,
    CONF_STATS_INTERVAL,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_STATS_FROM,
    DEFAULT_STATS_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    }
)


class TraewellingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung über die UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def _async_validate(self, data: dict[str, Any]) -> tuple[dict, dict]:
        """Token prüfen. Gibt (user, errors) zurück."""
        api = TraewellingApi(
            async_get_clientsession(self.hass),
            data[CONF_TOKEN].strip(),
            data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        )
        try:
            user = await api.async_get_self()
        except TraewellingAuthError:
            return {}, {"base": "invalid_auth"}
        except TraewellingError as err:
            _LOGGER.debug("Verbindungstest fehlgeschlagen: %s", err)
            return {}, {"base": "cannot_connect"}
        return user, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user, errors = await self._async_validate(user_input)
            if not errors:
                username = user.get("username") or "Träwelling"
                await self.async_set_unique_id(
                    str(user.get("uuid") or user.get("id") or username)
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Träwelling ({username})",
                    data={
                        CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                        CONF_BASE_URL: user_input.get(
                            CONF_BASE_URL, DEFAULT_BASE_URL
                        ).rstrip("/"),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        if user_input is not None:
            data = {**self._reauth_entry.data, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            _, errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data=data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Token tauschen, z. B. um den Scope write-statuses für den Check-in zu ergänzen."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            _, errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data=data, reason="reconfigure_successful"
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return TraewellingOptionsFlow()


class TraewellingOptionsFlow(OptionsFlow):
    """Abfrageintervalle und Statistik-Zeitraum anpassen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ACTIVE_INTERVAL,
                    default=current.get(CONF_ACTIVE_INTERVAL, DEFAULT_ACTIVE_INTERVAL),
                ): vol.All(int, vol.Range(min=30, max=3600)),
                vol.Optional(
                    CONF_STATS_INTERVAL,
                    default=current.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL),
                ): vol.All(int, vol.Range(min=5, max=1440)),
                vol.Optional(
                    CONF_STATS_FROM,
                    default=current.get(CONF_STATS_FROM, DEFAULT_STATS_FROM),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
