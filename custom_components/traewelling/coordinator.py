"""Coordinator: pollt die aktive Fahrt häufig, Statistiken selten."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
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
)
from .friends import active_friend_trips
from .journey import arr_live, build_chain, dep_live


_LOGGER = logging.getLogger(__name__)

# Pause zwischen den einzelnen Statistik-Anfragen, damit sie nicht als
# Stoß beim Server ankommen (Fair Use von Träwelling).
STATS_REQUEST_SPACING = 3  # Sekunden

# Bevorstehende eigene Fahrten: so weit voraus anzeigen …
UPCOMING_HORIZON = timedelta(minutes=60)
# … und /dashboard/future (Fahrten >20 min voraus) nur so oft abfragen.
# Träwelling aktualisiert Echtzeitdaten erst ab 20 min vor Abfahrt – danach
# kommen die Fahrten über /dashboard (jede Minute) bzw. /status/{id}.
FUTURE_INTERVAL = timedelta(minutes=5)
# Ab hier liefert /dashboard die eigene Fahrt (Träwelling: 20 min) + Puffer.
DASHBOARD_WINDOW = timedelta(minutes=20)
# Höchstens so viele Einzelabfragen /status/{id} pro Poll (Fair Use).
MAX_STATUS_REFRESH = 3

# Monatsverlauf fürs Diagramm
HISTORY_MONTHS = 12
STORE_VERSION = 1


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
        self._stats_task: asyncio.Task | None = None
        # Ergebnisse der Statistik-Abfragen (werden in jedes Update gemischt).
        self._stats: dict[str, Any] = {}
        # Zuletzt bei einem eigenen Check-in genutzte Fahrkarte (id + Daten).
        self.last_ticket: dict[str, Any] | None = None
        # Eigene Status aus /dashboard/future bzw. direkt aus einem Check-in.
        self._future: list[dict[str, Any]] = []
        self._last_future: datetime | None = None
        self._own_checkins: dict[Any, dict[str, Any]] = {}
        self._dashboard_own: list[dict[str, Any]] = []
        self._dashboard_fresh = False
        self._future_fresh = False
        self._future_new = False
        # Alle bekannten eigenen, noch nicht beendeten Fahrten (id -> Status).
        self._known: dict[Any, dict[str, Any]] = {}
        # Abgeschlossene Monate ändern sich nicht mehr → dauerhaft zwischenspeichern.
        self._month_store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.months")
        self._month_cache: dict[str, dict[str, Any]] | None = None

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

        if self.api.rate_limited_for > 0:
            # Retry-After respektieren: bis dahin keine Anfragen, alte Daten behalten.
            _LOGGER.debug(
                "Rate-Limit aktiv, überspringe Abfrage (noch %d s)",
                self.api.rate_limited_for,
            )
            return data

        try:
            if not data.get("user") and not self._stats.get("user"):
                # Profil einmal vorab – wird u. a. gebraucht, um dich selbst
                # aus „Freunde unterwegs“ herauszufiltern.
                self._stats["user"] = await self.api.async_get_self()
            data["active"] = await self.api.async_get_active_status()
        except TraewellingRateLimitError:
            return {**data, **self._stats}
        except TraewellingAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TraewellingError as err:
            raise UpdateFailed(str(err)) from err

        data.update(self._stats)
        await self._async_update_friends(data)
        await self._async_update_future()
        await self._async_update_known(data)
        chain = self._build_chain(data)
        data["chain"] = chain
        data["upcoming"] = chain[0] if chain else None
        self._maybe_start_statistics()
        return data

    # ------------------------------------------------------------------ #
    # Bevorstehende eigene Fahrt
    # ------------------------------------------------------------------ #

    def set_like(self, status_id: Any, liked: bool, likes: int | None) -> None:
        """Like-Status einer Freundes-Fahrt sofort übernehmen (ohne Neuabfrage)."""
        if not self.data:
            return
        friends = []
        for trip in self.data.get("friends") or []:
            if str(trip.get("status_id")) == str(status_id):
                trip = {**trip, "liked": liked}
                if likes is not None:
                    trip["likes"] = likes
                elif isinstance(trip.get("likes"), int):
                    trip["likes"] = max(0, trip["likes"] + (1 if liked else -1))
            friends.append(trip)
        self.data = {**self.data, "friends": friends}
        self.async_update_listeners()

    def remember_checkin(self, status: dict[str, Any]) -> None:
        """Frisch angelegten Check-in merken – sofort als „bald“ anzeigbar."""
        if isinstance(status, dict) and status.get("id") is not None:
            self._own_checkins[status["id"]] = status
            self._last_future = None  # beim nächsten Poll neu abgleichen

    async def _async_update_future(self) -> None:
        self._future_fresh = False
        self._future_new = False
        now = dt_util.utcnow()
        if self._last_future is not None and now - self._last_future < FUTURE_INTERVAL:
            return
        try:
            self._future = await self.api.async_get_future()
            self._last_future = now
            self._future_new = True
            self._future_fresh = self.api.future_complete
        except TraewellingRateLimitError:
            return
        except TraewellingError as err:
            _LOGGER.debug("Zukünftige Check-ins nicht abrufbar: %s", err)
            self._last_future = now

    def _is_own(self, status: dict[str, Any], user: dict[str, Any] | None) -> bool:
        me = user or {}
        my_ids = {str(v) for v in (me.get("id"), me.get("uuid")) if v is not None}
        details = status.get("userDetails") or {}
        uid = details.get("id", status.get("user"))
        if my_ids and uid is not None:
            return str(uid) in my_ids
        return bool(me.get("username")) and details.get("username") == me.get("username")

    async def _async_update_known(self, data: dict[str, Any]) -> None:
        """Bekannte eigene Fahrten zusammenführen, Gelöschte vergessen.

        Reihenfolge = Aktualität: eigener Check-in < /dashboard/future <
        /dashboard (jede Minute, mit Echtzeit) < /status/{id}.
        """
        now = dt_util.utcnow()
        user = data.get("user")
        future_ids = {s.get("id") for s in self._future if isinstance(s, dict)}
        dash = self._dashboard_own if self._dashboard_fresh else []
        dash_ids = {s.get("id") for s in dash if isinstance(s, dict)}

        future = self._future if self._future_new else []
        for status in [*self._own_checkins.values(), *future, *dash]:
            if not isinstance(status, dict) or status.get("id") is None:
                continue
            if status.get("id") in self._own_checkins or self._is_own(status, user):
                self._known[status["id"]] = status
        # Eigene Check-ins, die der Server schon liefert, nicht mehr gesondert merken.
        for sid in (future_ids if self._future_new else set()) | dash_ids:
            self._own_checkins.pop(sid, None)
        active = data.get("active") if isinstance(data.get("active"), dict) else {}
        if active.get("id") is not None:
            self._known.pop(active["id"], None)  # läuft gerade → nicht Teil der Kette

        refresh: list[Any] = []
        for sid, status in list(self._known.items()):
            arr = arr_live(status)
            dep = dep_live(status)
            if arr is not None and arr < now:
                self._forget(sid)  # vorbei
                continue
            if dep is None:
                continue
            if dep >= now + DASHBOARD_WINDOW + timedelta(minutes=2):
                # Müsste in /dashboard/future stehen – fehlt es dort, wurde
                # der Check-in gelöscht.
                if self._future_fresh and sid not in future_ids and sid not in dash_ids:
                    self._forget(sid)
            elif sid not in dash_ids and dep >= now - timedelta(minutes=5):
                # Kurz vor Abfahrt, aber nicht (mehr) im Dashboard (z. B. vor
                # über 7 Tagen angelegt) → einzeln mit Echtzeit nachladen.
                refresh.append((dep, sid))

        refresh.sort(key=lambda x: x[0])
        for _dep, sid in refresh[:MAX_STATUS_REFRESH]:
            try:
                status = await self.api.async_get_status(sid)
            except TraewellingRateLimitError:
                return
            except TraewellingError as err:
                _LOGGER.debug("Status %s nicht abrufbar: %s", sid, err)
                continue
            if status is None:
                self._forget(sid)  # gelöscht
            else:
                self._known[sid] = status

    def _forget(self, sid: Any) -> None:
        self._known.pop(sid, None)
        self._own_checkins.pop(sid, None)

    def _build_chain(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Anschlusskette: nach der aktiven Fahrt bzw. ab der nächsten Fahrt
        (innerhalb einer Stunde) jeweils den nächsten eigenen Check-in."""
        active = data.get("active") if isinstance(data.get("active"), dict) else None
        return build_chain(
            active, list(self._known.values()), dt_util.utcnow(), UPCOMING_HORIZON
        )

    async def _async_update_friends(self, data: dict[str, Any]) -> None:
        """Laufende Fahrten gefolgter Accounts. Fehler hier sind nicht fatal."""
        self._dashboard_fresh = False
        try:
            statuses = await self.api.async_get_dashboard()
        except TraewellingRateLimitError:
            return  # alte Liste behalten
        except TraewellingError as err:
            # Auch Auth-Fehler nur loggen: der Rest der Integration soll weiterlaufen.
            _LOGGER.warning("Dashboard (Freunde) konnte nicht geladen werden: %s", err)
            data.setdefault("friends", [])
            return
        data["friends"] = active_friend_trips(statuses, data.get("user"))
        self._dashboard_own = [
            s for s in statuses if isinstance(s, dict) and self._is_own(s, data.get("user"))
        ]
        self._dashboard_fresh = True
        self._remember_ticket([data.get("active"), *statuses], data.get("user"))

    def _remember_ticket(self, statuses: list[Any], user: dict[str, Any] | None) -> None:
        """Fahrkarte des jüngsten eigenen Status merken (Vorschlag beim Check-in)."""
        me = user or {}
        my_ids = {str(v) for v in (me.get("id"), me.get("uuid")) if v is not None}
        own = []
        for status in statuses:
            if not isinstance(status, dict) or not isinstance(status.get("ticket"), dict):
                continue
            details = status.get("userDetails") or {}
            uid = str(details.get("id", status.get("user")))
            # Die API liefert `ticket` ohnehin nur bei eigenen Status mit.
            if my_ids and uid not in my_ids:
                continue
            own.append(status)
        if own:
            newest = max(own, key=lambda s: str(s.get("createdAt") or s.get("id") or ""))
            self.last_ticket = newest["ticket"]

    # ------------------------------------------------------------------ #
    # Statistik – läuft im Hintergrund, Anfragen mit Abstand
    # ------------------------------------------------------------------ #

    def _maybe_start_statistics(self) -> None:
        if self._stats_task is not None and not self._stats_task.done():
            return
        now = dt_util.utcnow()
        if self._last_stats is not None and now - self._last_stats < self._stats_interval:
            return
        self._stats_task = self.entry.async_create_background_task(
            self.hass,
            self._async_update_statistics(),
            name=f"{DOMAIN} statistics {self.entry.entry_id}",
        )

    async def _async_update_statistics(self) -> None:
        """Profil + Statistik-Endpunkte nacheinander mit Pause abfragen.

        Fehler sind nicht fatal. Bei 429 wird abgebrochen und nach Ablauf von
        Retry-After beim nächsten regulären Poll neu gestartet.
        """
        today = dt_util.now().date()
        date_to = (today + timedelta(days=1)).isoformat()
        month_from = today.replace(day=1).isoformat()
        year_from = today.replace(month=1, day=1).isoformat()
        week_from = (today - timedelta(days=today.weekday())).isoformat()

        # Fabriken statt Coroutinen, damit nichts ungewartet liegen bleibt.
        requests = (
            ("user", lambda: self.api.async_get_self()),
            ("stats", lambda: self.api.async_get_statistics_overview(self._stats_from, date_to)),
            ("stats_month", lambda: self.api.async_get_statistics_overview(month_from, date_to)),
            ("stats_year", lambda: self.api.async_get_statistics_overview(year_from, date_to)),
            ("stats_week", lambda: self.api.async_get_statistics_overview(week_from, date_to)),
            ("history", lambda: self.api.async_get_statistics_history()),
            ("favorites", lambda: self.api.async_get_statistics_favorites(year_from, date_to)),
            ("personal", lambda: self.api.async_get_statistics_personal(year_from, date_to)),
            ("leaderboard", lambda: self.api.async_get_leaderboard_friends()),
        )

        results: dict[str, Any] = {}
        for index, (key, factory) in enumerate(requests):
            if index:
                await asyncio.sleep(STATS_REQUEST_SPACING)
            try:
                result = await factory()
            except TraewellingRateLimitError as err:
                _LOGGER.info("Statistik-Abfrage pausiert: %s", err)
                self._publish(results)
                return  # _last_stats bleibt → nächster Poll nach Retry-After
            except TraewellingAuthError as err:
                if key == "user":
                    self.entry.async_start_reauth(self.hass)
                    return
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
                results[key] = result

        self._publish(results)
        monthly = await self._async_monthly(results)
        if monthly is not None:
            self._publish({"monthly": monthly})
        self._last_stats = dt_util.utcnow()

    # ------------------------------------------------------------------ #
    # Monatsverlauf (Check-ins und km der letzten 12 Monate)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _month_keys(today: date) -> list[str]:
        """YYYY-MM der letzten HISTORY_MONTHS Monate, ältester zuerst."""
        keys = []
        y, m = today.year, today.month
        for _ in range(HISTORY_MONTHS):
            keys.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        return list(reversed(keys))

    @staticmethod
    def _summary_values(payload: Any) -> tuple[int | None, float | None]:
        stats = payload if isinstance(payload, dict) else {}
        summary = stats.get("summary") if isinstance(stats.get("summary"), dict) else stats
        count = summary.get("total_checkins")
        km = summary.get("total_distance_km")
        return (
            int(count) if isinstance(count, (int, float)) else None,
            round(float(km), 1) if isinstance(km, (int, float)) else None,
        )

    async def _async_monthly(self, results: dict[str, Any]) -> list[dict[str, Any]] | None:
        today = dt_util.now().date()
        keys = self._month_keys(today)
        current = keys[-1]
        if self._month_cache is None:
            stored = await self._month_store.async_load()
            self._month_cache = dict((stored or {}).get("months", {}))

        # 1) /statistics/history liefert alles auf einmal – wenn verfügbar.
        history = results.get("history") or self._stats.get("history")
        rows = history.get("monthly") if isinstance(history, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not row.get("period"):
                    continue
                key = str(row["period"])[:7]
                count, km = row.get("checkin_count"), row.get("distance_km")
                if key in keys and key != current and isinstance(count, (int, float)):
                    self._month_cache[key] = {
                        "checkins": int(count),
                        "km": round(float(km), 1) if isinstance(km, (int, float)) else None,
                    }

        # 2) Fehlende abgeschlossene Monate einmalig über /statistics/overview.
        changed = False
        for key in keys[:-1]:
            if key in self._month_cache:
                continue
            y, m = map(int, key.split("-"))
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1)
            await asyncio.sleep(STATS_REQUEST_SPACING)
            try:
                payload = await self.api.async_get_statistics_overview(
                    start.isoformat(), end.isoformat()
                )
            except TraewellingRateLimitError:
                break  # Rest beim nächsten Durchlauf
            except TraewellingError as err:
                _LOGGER.debug("Monat %s nicht abrufbar: %s", key, err)
                break
            count, km = self._summary_values(payload)
            if count is None:
                break
            self._month_cache[key] = {"checkins": count, "km": km}
            changed = True

        if changed or rows:
            await self._month_store.async_save(
                {"months": {k: v for k, v in self._month_cache.items() if k in keys}}
            )

        # 3) Laufender Monat immer frisch aus stats_month.
        month_stats = results.get("stats_month") or self._stats.get("stats_month")
        cur_count, cur_km = self._summary_values(month_stats)

        out = []
        for key in keys:
            entry = self._month_cache.get(key, {})
            if key == current:
                entry = {"checkins": cur_count, "km": cur_km}
            out.append(
                {
                    "month": key,
                    "checkins": entry.get("checkins"),
                    "km": entry.get("km"),
                    "current": key == current,
                }
            )
        return out

    def _publish(self, results: dict[str, Any]) -> None:
        """Ergebnisse übernehmen, ohne den Poll-Takt neu zu starten."""
        if not results:
            return
        self._stats.update(results)
        if self.data is not None:
            self.data = {**self.data, **results}
            self.async_update_listeners()

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
