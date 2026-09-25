"""Statistik-Abfragen – nur so oft, wie sich die Werte ändern können.

Träwelling cacht die Statistik serverseitig (overview 1 h, history 6 h). Deshalb
werden die Endpunkte nach ihrer „Lebensdauer“ gruppiert:

* profile – Profil (Punkte der letzten 7 Tage sinken mit der Zeit) und
  Freunde-Rangliste (hängt an fremden Check-ins): im eingestellten Intervall.
* periods – Zeiträume (gesamt/Jahr/Monat/Woche), Favoriten, Verkehrsmittel:
  ändern sich nur durch eigene Check-ins oder den Datumswechsel. Nach einer
  Änderung wird so lange im Intervall abgefragt, bis Träwellings 1-h-Cache
  sicher abgelaufen ist, sonst alle 6 h.
* history – Monats-/Wochenverlauf: alle 6 h (Server-Cache).

Die Anfragen einer Runde gehen nacheinander mit 3 s Abstand raus.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    TraewellingApi,
    TraewellingAuthError,
    TraewellingError,
    TraewellingRateLimitError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Pause zwischen den einzelnen Anfragen (Fair Use).
REQUEST_SPACING = 3  # Sekunden
# Serverseitige Cache-Dauer von /statistics/overview (+ Puffer).
SERVER_CACHE = timedelta(minutes=65)
# Ohne eigene Änderung: Zeiträume/Favoriten und Verlauf so selten.
IDLE_INTERVAL = timedelta(hours=6)

HISTORY_MONTHS = 12
STORE_VERSION = 1

Publish = Callable[[dict[str, Any]], None]


def month_keys(today: date, months: int = HISTORY_MONTHS) -> list[str]:
    """YYYY-MM der letzten `months` Monate, ältester zuerst."""
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


def summary_values(payload: Any) -> tuple[int | None, float | None]:
    """(Check-ins, km) aus einer /statistics/overview-Antwort."""
    stats = payload if isinstance(payload, dict) else {}
    summary = stats.get("summary") if isinstance(stats.get("summary"), dict) else stats
    count = summary.get("total_checkins")
    km = summary.get("total_distance_km")
    return (
        int(count) if isinstance(count, (int, float)) else None,
        round(float(km), 1) if isinstance(km, (int, float)) else None,
    )


class StatisticsUpdater:
    """Plant und führt die Statistik-Abfragen im Hintergrund aus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: TraewellingApi,
        interval: timedelta,
        stats_from: str,
        publish: Publish,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._api = api
        self._interval = interval
        self._stats_from = stats_from
        self._publish = publish
        self._task: asyncio.Task | None = None
        self._last: dict[str, datetime] = {}
        self._periods_day: date | None = None
        self.results: dict[str, Any] = {}
        # Abgeschlossene Monate ändern sich nicht mehr → dauerhaft speichern.
        self._store: Store = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.months"
        )
        self._months: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ #
    # Planung
    # ------------------------------------------------------------------ #

    def _elapsed(self, group: str, now: datetime) -> timedelta | None:
        last = self._last.get(group)
        return None if last is None else now - last

    def due_groups(self, now: datetime, own_changed_at: datetime | None) -> list[str]:
        """Welche Gruppen jetzt dran sind (Reihenfolge = Abfrage-Reihenfolge)."""
        groups = []
        age = self._elapsed("profile", now)
        if age is None or age >= self._interval:
            groups.append("profile")

        age = self._elapsed("periods", now)
        last = self._last.get("periods")
        changed = (
            own_changed_at is not None
            and last is not None
            and own_changed_at > last - SERVER_CACHE
        )
        if (
            age is None
            or self._periods_day != dt_util.now().date()
            or age >= max(IDLE_INTERVAL, self._interval)
            or (changed and age >= self._interval)
        ):
            groups.append("periods")

        age = self._elapsed("history", now)
        if age is None or age >= max(IDLE_INTERVAL, self._interval):
            groups.append("history")
        return groups

    def maybe_start(self, now: datetime, own_changed_at: datetime | None) -> None:
        if self._task is not None and not self._task.done():
            return
        groups = self.due_groups(now, own_changed_at)
        if groups:
            self._task = self._entry.async_create_background_task(
                self._hass,
                self._async_run(groups),
                name=f"{DOMAIN} statistics {self._entry.entry_id}",
            )

    # ------------------------------------------------------------------ #
    # Abfragen
    # ------------------------------------------------------------------ #

    def _requests(self, group: str) -> list[tuple[str, Callable[[], Awaitable[Any]]]]:
        today = dt_util.now().date()
        date_to = (today + timedelta(days=1)).isoformat()
        month_from = today.replace(day=1).isoformat()
        year_from = today.replace(month=1, day=1).isoformat()
        week_from = (today - timedelta(days=today.weekday())).isoformat()
        api = self._api
        if group == "profile":
            return [
                ("user", api.async_get_self),
                ("leaderboard", api.async_get_leaderboard_friends),
            ]
        if group == "periods":
            return [
                (
                    "stats",
                    lambda: api.async_get_statistics_overview(
                        self._stats_from, date_to
                    ),
                ),
                (
                    "stats_month",
                    lambda: api.async_get_statistics_overview(month_from, date_to),
                ),
                (
                    "stats_year",
                    lambda: api.async_get_statistics_overview(year_from, date_to),
                ),
                (
                    "stats_week",
                    lambda: api.async_get_statistics_overview(week_from, date_to),
                ),
                (
                    "favorites",
                    lambda: api.async_get_statistics_favorites(year_from, date_to),
                ),
                (
                    "personal",
                    lambda: api.async_get_statistics_personal(year_from, date_to),
                ),
            ]
        return [("history", api.async_get_statistics_history)]

    async def _async_run(self, groups: list[str]) -> None:
        """Gruppen nacheinander abfragen. Fehler einzelner Endpunkte sind nicht
        fatal; bei 429 wird abgebrochen und beim nächsten Poll fortgesetzt."""
        first = True
        for group in groups:
            day = dt_util.now().date()
            results: dict[str, Any] = {}
            for key, fetch in self._requests(group):
                if not first:
                    await asyncio.sleep(REQUEST_SPACING)
                first = False
                try:
                    result = await fetch()
                except TraewellingRateLimitError as err:
                    _LOGGER.info("Statistik-Abfrage pausiert: %s", err)
                    self._apply(results)
                    return  # Gruppe bleibt fällig
                except TraewellingAuthError as err:
                    if key == "user":
                        self._entry.async_start_reauth(self._hass)
                        return
                    # /statistics/* braucht den Scope read-statistics. Fehlt er,
                    # läuft die restliche Integration trotzdem weiter.
                    _LOGGER.warning(
                        "Statistik-Endpunkt %s nicht verfügbar (Scope 'read-statistics' fehlt?): %s",
                        key,
                        err,
                    )
                    continue
                except TraewellingError as err:
                    _LOGGER.warning(
                        "Statistik-Endpunkt %s fehlgeschlagen: %s", key, err
                    )
                    continue
                if result is not None:
                    results[key] = result
            self._apply(results)
            self._last[group] = dt_util.utcnow()
            if group == "periods":
                self._periods_day = day

        if "periods" in groups or "history" in groups:
            monthly = await self._async_monthly()
            if monthly is not None:
                self._apply({"monthly": monthly})

    def _apply(self, results: dict[str, Any]) -> None:
        if results:
            self.results.update(results)
            self._publish(results)

    # ------------------------------------------------------------------ #
    # Monatsverlauf (Check-ins und km der letzten 12 Monate)
    # ------------------------------------------------------------------ #

    async def _async_monthly(self) -> list[dict[str, Any]] | None:
        today = dt_util.now().date()
        keys = month_keys(today)
        current = keys[-1]
        if self._months is None:
            stored = await self._store.async_load()
            self._months = dict((stored or {}).get("months", {}))
        months = self._months
        changed = False

        # 1) /statistics/history liefert alle Monate auf einmal – wenn verfügbar.
        history = self.results.get("history")
        rows = history.get("monthly") if isinstance(history, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("period"):
                continue
            key = str(row["period"])[:7]
            count, km = row.get("checkin_count"), row.get("distance_km")
            if key in keys and key != current and isinstance(count, (int, float)):
                value = {
                    "checkins": int(count),
                    "km": round(float(km), 1) if isinstance(km, (int, float)) else None,
                }
                if months.get(key) != value:
                    months[key] = value
                    changed = True

        # 2) Fehlende abgeschlossene Monate einmalig über /statistics/overview.
        for key in keys[:-1]:
            if key in months:
                continue
            y, m = map(int, key.split("-"))
            start, end = date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
            await asyncio.sleep(REQUEST_SPACING)
            try:
                payload = await self._api.async_get_statistics_overview(
                    start.isoformat(), end.isoformat()
                )
            except TraewellingRateLimitError:
                break  # Rest beim nächsten Durchlauf
            except TraewellingError as err:
                _LOGGER.debug("Monat %s nicht abrufbar: %s", key, err)
                break
            count, km = summary_values(payload)
            if count is None:
                break
            months[key] = {"checkins": count, "km": km}
            changed = True

        stale = [k for k in months if k not in keys]
        if changed or stale:
            for key in stale:
                months.pop(key, None)
            await self._store.async_save({"months": months})

        # 3) Laufender Monat immer frisch aus stats_month.
        cur_count, cur_km = summary_values(self.results.get("stats_month"))
        out = []
        for key in keys:
            entry = (
                {"checkins": cur_count, "km": cur_km}
                if key == current
                else months.get(key, {})
            )
            out.append(
                {
                    "month": key,
                    "checkins": entry.get("checkins"),
                    "km": entry.get("km"),
                    "current": key == current,
                }
            )
        return out
