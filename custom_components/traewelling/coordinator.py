"""Coordinator: eigene Fahrten und Freunde jede Minute, Statistik nach Bedarf.

Anfragen pro Poll (Standard: jede Minute):

* /dashboard – Freunde + eigene Fahrten bis 20 min voraus (Seite 2 nur, wenn
  Seite 1 weniger als 24 h zurückreicht)
* /user/statuses/active – nur wenn eine eigene Fahrt läuft oder in Kürze
  startet, direkt nach einem Check-in und sonst als Sicherheitsnetz alle 5 min
* /dashboard/future – alle 5 min
* /status/{id} bzw. Abfahrtstafel – nur für Anschlüsse, die es brauchen
* Statistik – siehe statistics.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    TraewellingApi,
    TraewellingAuthError,
    TraewellingError,
    TraewellingRateLimitError,
)
from .const import (
    CONF_ACTIVE_INTERVAL,
    CONF_STATS_FROM,
    CONF_STATS_INTERVAL,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_STATS_FROM,
    DEFAULT_STATS_INTERVAL,
    DOMAIN,
    MIN_ACTIVE_INTERVAL,
)
from .friends import active_friend_trips
from .helpers import departure, is_own
from .own_trips import OwnTrips
from .statistics import StatisticsUpdater

_LOGGER = logging.getLogger(__name__)

# /dashboard/future (eigene Fahrten >20 min voraus) nur so oft abfragen –
# Träwelling aktualisiert Echtzeit ohnehin erst ab 20 min vor Abfahrt.
FUTURE_INTERVAL = timedelta(minutes=5)
# /user/statuses/active ohne erkennbaren Anlass trotzdem so oft prüfen.
ACTIVE_SAFETY_INTERVAL = timedelta(minutes=5)
# /dashboard: höchstens so viele Seiten à 15 Status; Seite 2 nur, wenn Seite 1
# nicht so weit zurückreicht (sonst kann dort keine laufende Fahrt mehr stehen).
DASHBOARD_PAGES = 2
DASHBOARD_SPAN = timedelta(hours=24)


class TraewellingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hält aktive Fahrt, Anschlüsse, Freunde, Profil und Statistiken."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: TraewellingApi
    ) -> None:
        options = {**entry.data, **entry.options}
        self.api = api
        self.entry = entry
        # Zuletzt bei einem eigenen Check-in genutzte Fahrkarte (id + Daten).
        self.last_ticket: dict[str, Any] | None = None
        self.trips = OwnTrips(api)
        self.statistics = StatisticsUpdater(
            hass,
            entry,
            api,
            interval=timedelta(
                minutes=int(options.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL))
            ),
            stats_from=options.get(CONF_STATS_FROM) or DEFAULT_STATS_FROM,
            publish=self._publish,
        )
        self._last_future: datetime | None = None
        self._last_active: datetime | None = None
        self._force_active = True
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=max(
                MIN_ACTIVE_INTERVAL,
                timedelta(
                    seconds=int(
                        options.get(CONF_ACTIVE_INTERVAL, DEFAULT_ACTIVE_INTERVAL)
                    )
                ),
            ),
        )

    # ------------------------------------------------------------------ #
    # Poll
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {**(self.data or {}), **self.statistics.results}
        if self.api.rate_limited_for > 0:
            # Retry-After respektieren: bis dahin keine Anfragen, alte Daten behalten.
            _LOGGER.debug(
                "Rate-Limit aktiv, überspringe Abfrage (noch %d s)",
                self.api.rate_limited_for,
            )
            return data

        now = dt_util.utcnow()
        try:
            if not data.get("user"):
                # Profil einmal vorab – u. a. um dich aus „Freunde“ herauszufiltern.
                self._publish({"user": await self.api.async_get_self()}, notify=False)
                data["user"] = self.statistics.results["user"]
            dashboard = await self._async_dashboard(now)
            future, future_complete = await self._async_future(now)

            own = [s for s in dashboard or [] if is_own(s, data["user"])]
            if dashboard is None or self._active_due(data, own, now):
                data["active"] = await self.api.async_get_active_status()
                self._last_active, self._force_active = now, False
        except TraewellingRateLimitError:
            return data
        except TraewellingAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TraewellingError as err:
            raise UpdateFailed(str(err)) from err

        active = data.get("active") if isinstance(data.get("active"), dict) else None
        if dashboard is not None:
            data["friends"] = active_friend_trips(dashboard, data["user"])
            self._remember_ticket([active, *own])
        else:
            data.setdefault("friends", [])

        own_future = [s for s in future or [] if is_own(s, data["user"])]
        self.trips.note_statuses(
            [*own, *own_future, *([active] if active else [])], now
        )
        await self.trips.async_update(
            data["user"],
            active,
            own if dashboard is not None else None,
            future,
            future_complete,
            now,
        )
        data["chain"] = await self.trips.async_chain(active, now)
        data["upcoming"] = data["chain"][0] if data["chain"] else None

        self.statistics.maybe_start(now, self.trips.changed_at)
        return data

    async def _async_dashboard(self, now: datetime) -> list[dict[str, Any]] | None:
        """Neueste Status von dir und allen, denen du folgst (None = Fehler)."""
        statuses: list[dict[str, Any]] = []
        try:
            for page in range(1, DASHBOARD_PAGES + 1):
                items, more = await self.api.async_get_dashboard_page(page)
                statuses.extend(items)
                oldest = min(
                    filter(None, (departure(s, real=False) for s in items)),
                    default=None,
                )
                if not more or (oldest is not None and oldest < now - DASHBOARD_SPAN):
                    break
        except (TraewellingRateLimitError, TraewellingAuthError):
            raise
        except TraewellingError as err:
            _LOGGER.warning("Dashboard (Freunde) konnte nicht geladen werden: %s", err)
            return None
        return statuses

    async def _async_future(
        self, now: datetime
    ) -> tuple[list[dict[str, Any]] | None, bool]:
        """Eigene Fahrten >20 min voraus, alle 5 min (None = nicht abgefragt)."""
        if self._last_future is not None and now - self._last_future < FUTURE_INTERVAL:
            return None, False
        try:
            future, complete = await self.api.async_get_future()
        except TraewellingRateLimitError:
            return None, False
        except TraewellingError as err:
            _LOGGER.debug("Zukünftige Check-ins nicht abrufbar: %s", err)
            self._last_future = now
            return None, False
        self._last_future = now
        return future, complete

    def _active_due(
        self, data: dict[str, Any], own: list[dict[str, Any]], now: datetime
    ) -> bool:
        """/user/statuses/active nur abfragen, wenn sich dort etwas tun kann."""
        return (
            self._force_active
            or self._last_active is None
            or isinstance(data.get("active"), dict)
            or now - self._last_active >= ACTIVE_SAFETY_INTERVAL
            or self.trips.active_expected(own, now)
        )

    # ------------------------------------------------------------------ #
    # Von Services aufgerufen
    # ------------------------------------------------------------------ #

    def remember_checkin(self, status: dict[str, Any]) -> None:
        """Frisch angelegten Check-in merken und beim nächsten Poll alles abgleichen."""
        self.trips.remember_checkin(status, dt_util.utcnow())
        self._last_future = None
        self._force_active = True

    def set_like(self, status_id: Any, liked: bool, likes: int | None) -> None:
        """Like-Status einer Freundes-Fahrt sofort übernehmen (ohne Neuabfrage)."""
        if not self.data:
            return
        friends = [
            _with_like(trip, liked, likes)
            if str(trip.get("status_id")) == str(status_id)
            else trip
            for trip in self.data.get("friends") or []
        ]
        # Bewusst ohne async_set_updated_data: der Poll-Takt läuft unverändert weiter.
        self.data = {**self.data, "friends": friends}
        self.async_update_listeners()

    # ------------------------------------------------------------------ #
    # Hilfen
    # ------------------------------------------------------------------ #

    def _remember_ticket(self, statuses: list[dict[str, Any] | None]) -> None:
        """Fahrkarte des jüngsten eigenen Status merken (Vorschlag beim Check-in).

        Die API liefert `ticket` ohnehin nur bei eigenen Status mit.
        """
        own = [
            s
            for s in statuses
            if isinstance(s, dict) and isinstance(s.get("ticket"), dict)
        ]
        if own:
            newest = max(
                own, key=lambda s: str(s.get("createdAt") or s.get("id") or "")
            )
            self.last_ticket = newest["ticket"]

    def _publish(self, results: dict[str, Any], notify: bool = True) -> None:
        """Statistik-Ergebnisse übernehmen, ohne den Poll-Takt neu zu starten."""
        if not results:
            return
        self.statistics.results.update(results)
        if notify and self.data is not None:
            self.data = {**self.data, **results}
            self.async_update_listeners()


# Config-Entry mit dem Coordinator als runtime_data.
TraewellingConfigEntry = ConfigEntry[TraewellingCoordinator]


def _with_like(trip: dict[str, Any], liked: bool, likes: int | None) -> dict[str, Any]:
    trip = {**trip, "liked": liked}
    if likes is not None:
        trip["likes"] = likes
    elif isinstance(trip.get("likes"), int):
        trip["likes"] = max(0, trip["likes"] + (1 if liked else -1))
    return trip
