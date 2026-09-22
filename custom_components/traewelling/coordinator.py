"""Coordinator: pollt die aktive Fahrt häufig, Statistiken selten."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import TraewellingApi, TraewellingAuthError, TraewellingError
from .const import (
    CONF_ACTIVE_INTERVAL,
    CONF_STATS_FROM,
    CONF_STATS_INTERVAL,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_STATS_FROM,
    DEFAULT_STATS_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class TraewellingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hält aktive Fahrt, Profil und Statistiken."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: TraewellingApi
    ) -> None:
        options = {**entry.data, **entry.options}
        self.api = api
        self.entry = entry
        self._stats_interval = timedelta(
            minutes=int(options.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL))
        )
        self._stats_from: str = options.get(CONF_STATS_FROM) or DEFAULT_STATS_FROM
        self._last_stats: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=max(
                    30, int(options.get(CONF_ACTIVE_INTERVAL, DEFAULT_ACTIVE_INTERVAL))
                )
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.data or {})

        try:
            data["active"] = await self.api.async_get_active_status()
        except TraewellingAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TraewellingError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.utcnow()
        if self._last_stats is None or now - self._last_stats >= self._stats_interval:
            await self._async_update_statistics(data)
            self._last_stats = now

        return data

    async def _async_update_statistics(self, data: dict[str, Any]) -> None:
        """Profil + Statistik-Endpunkte. Fehler hier sind nicht fatal."""
        try:
            data["user"] = await self.api.async_get_self()
        except TraewellingAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TraewellingError as err:
            _LOGGER.warning("Profil konnte nicht geladen werden: %s", err)

        today = dt_util.now().date()
        date_to = (today + timedelta(days=1)).isoformat()

        for key, coro in (
            (
                "stats",
                self.api.async_get_statistics_overview(self._stats_from, date_to),
            ),
            ("history", self.api.async_get_statistics_history()),
        ):
            try:
                result = await coro
            except TraewellingAuthError as err:
                # /statistics/* braucht den Scope read-statistics. Fehlt er,
                # soll die restliche Integration trotzdem laufen.
                _LOGGER.warning(
                    "Statistik-Endpunkt %s nicht verfügbar (Scope "
                    "'read-statistics' fehlt?): %s",
                    key,
                    err,
                )
                continue
            except TraewellingError as err:
                _LOGGER.warning("Statistik-Endpunkt %s fehlgeschlagen: %s", key, err)
                continue
            if result is not None:
                data[key] = result

    @property
    def username(self) -> str:
        user = (self.data or {}).get("user") or {}
        return (
            user.get("username")
            or user.get("displayName")
            or self.entry.title
            or "Träwelling"
        )

    @property
    def stats_from(self) -> date:
        return date.fromisoformat(self._stats_from)
