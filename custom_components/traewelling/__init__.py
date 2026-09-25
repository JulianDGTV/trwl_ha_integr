"""Träwelling-Integration für Home Assistant."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import TraewellingApi
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .coordinator import TraewellingConfigEntry, TraewellingCoordinator
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
    """JS-Karte bereitstellen und fürs Dashboard registrieren.

    1. Statischer Pfad für die Datei.
    2. Eintrag als Dashboard-Ressource (Einstellungen → Dashboards → Ressourcen).
       Die wird bei jedem Laden eines Dashboards mitgeladen – unabhängig davon,
       wann die Integration beim Start fertig ist.
    3. Fallback für YAML-Dashboards: extra_js_url.
    """
    version = (await async_get_integration(hass, DOMAIN)).version or "0"
    url = f"{CARD_URL_BASE}?v={version}"

    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(CARD_FILE), False)]
        )
    except ImportError:  # HA < 2024.7
        hass.http.register_static_path(CARD_URL_BASE, str(CARD_FILE), False)
    except RuntimeError:
        pass  # bereits registriert

    if await _async_register_resource(hass, url):
        return

    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
    except Exception as err:  # noqa: BLE001 – darf den Start nie verhindern
        _LOGGER.warning(
            "Check-in-Karte konnte nicht automatisch geladen werden (%s). "
            "Bitte als Dashboard-Ressource (JavaScript-Modul) hinzufügen: %s",
            err,
            url,
        )


def _lovelace_resources(hass: HomeAssistant):
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        data = hass.data.get(LOVELACE_DATA)
        if data is not None:
            return getattr(data, "resources", None)
    except ImportError:
        pass
    data = hass.data.get("lovelace")  # HA < 2025.2
    if isinstance(data, dict):
        return data.get("resources")
    return getattr(data, "resources", None)


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Karte als Lovelace-Ressource eintragen bzw. Version aktualisieren."""
    try:
        resources = _lovelace_resources(hass)
        if resources is None or not hasattr(resources, "async_create_item"):
            return False  # YAML-Modus
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True

        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == CARD_URL_BASE:
                if item.get("url") != url:
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": url}
                    )
                return True

        await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception as err:  # noqa: BLE001 – darf den Start nie verhindern
        _LOGGER.debug("Lovelace-Ressource konnte nicht registriert werden: %s", err)
        return False


async def async_setup_entry(hass: HomeAssistant, entry: TraewellingConfigEntry) -> bool:
    """Config Entry einrichten."""
    # Titel ist „Träwelling (username)“ → der User-Agent kennt den Account ab
    # der ersten Anfrage (wird danach aus /auth/user aktualisiert).
    match = re.search(r"\(([^()]+)\)\s*$", entry.title or "")
    api = TraewellingApi(
        async_get_clientsession(hass),
        entry.data[CONF_TOKEN],
        entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        username=match.group(1) if match else None,
        version=(await async_get_integration(hass, DOMAIN)).version or "0",
    )
    coordinator = TraewellingCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TraewellingConfigEntry
) -> bool:
    """Config Entry entladen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: TraewellingConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
