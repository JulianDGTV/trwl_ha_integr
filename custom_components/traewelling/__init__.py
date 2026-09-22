"""Träwelling-Integration für Home Assistant."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TraewellingApi
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .coordinator import TraewellingCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILE = Path(__file__).parent / "www" / "traewelling-checkin-card.js"
CARD_URL_BASE = "/traewelling_static/traewelling-checkin-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services registrieren und die Check-in-Karte automatisch ausliefern."""
    async_setup_services(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """JS-Karte als statische Datei bereitstellen und im Frontend laden.

    Dadurch muss keine Dashboard-Ressource von Hand angelegt werden.
    """
    manifest = await hass.async_add_executor_job(
        (Path(__file__).parent / "manifest.json").read_text, "utf-8"
    )
    version = json.loads(manifest).get("version", "0")
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(CARD_FILE), False)]
        )
    except ImportError:  # HA < 2024.7
        hass.http.register_static_path(CARD_URL_BASE, str(CARD_FILE), False)
    except RuntimeError:
        # Pfad ist nach einem Reload bereits registriert.
        pass

    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL_BASE}?v={version}")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Check-in-Karte konnte nicht automatisch geladen werden (%s). "
            "Ressource manuell hinzufügen: %s",
            err,
            CARD_URL_BASE,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry einrichten."""
    api = TraewellingApi(
        async_get_clientsession(hass),
        entry.data[CONF_TOKEN],
        entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )
    coordinator = TraewellingCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry entladen."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
