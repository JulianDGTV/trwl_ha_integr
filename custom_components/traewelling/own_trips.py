"""Eigene eingecheckte Fahrten: zusammenführen, aktuell halten, Kette bauen.

Quellen, nach Aktualität:
eigener Check-in über die Karte < /dashboard/future (alle 5 min, >20 min
voraus) < /dashboard (jede Minute, mit Echtzeit) < /status/{id} (einzeln,
nur wenn eine Fahrt kurz vor Abfahrt im Dashboard fehlt).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .api import TraewellingApi, TraewellingError, TraewellingRateLimitError
from .helpers import checkin_of, first, is_own, origin_of, parse_dt
from .journey import (
    arr_live,
    arr_planned,
    arr_source,
    build_chain,
    dep_is_live,
    dep_live,
    dep_planned,
    station_of,
    transfer,
)

_LOGGER = logging.getLogger(__name__)

# Bevorstehende eigene Fahrten so weit voraus anzeigen.
UPCOMING_HORIZON = timedelta(minutes=60)
# Bis so weit vor Abfahrt liefert /dashboard eigene Fahrten (Träwelling: 20 min).
DASHBOARD_WINDOW = timedelta(minutes=20)
# Höchstens so viele Einzelabfragen /status/{id} pro Poll.
MAX_STATUS_REFRESH = 3
# Anschluss ohne Echtzeit bei verspäteter Ankunft: Live-Abfahrtstafel der
# Umstiegsstation – je Anschluss höchstens alle 3 min, max. 2 pro Poll,
# nur für Anschlüsse in den nächsten 3 h.
BOARD_INTERVAL = timedelta(minutes=3)
MAX_BOARD_LOOKUPS = 2
BOARD_HORIZON = timedelta(hours=3)
# Ab so kurz vor Abfahrt bis kurz nach Ankunft einer eigenen Fahrt wird
# /user/statuses/active jede Minute abgefragt.
ACTIVE_LEAD = timedelta(minutes=5)
ACTIVE_TAIL = timedelta(minutes=2)


class OwnTrips:
    """Bekannte eigene, noch nicht beendete Fahrten."""

    def __init__(self, api: TraewellingApi) -> None:
        self._api = api
        self._known: dict[Any, dict[str, Any]] = {}
        self._pending: dict[Any, dict[str, Any]] = {}  # frisch eingecheckt
        self._board: dict[Any, dict[str, Any]] = {}
        # Wann sich die eigenen Check-ins zuletzt geändert haben (neu/gelöscht).
        self.changed_at: datetime | None = None
        self._seen: set[Any] | None = None
        self._since: datetime | None = None

    # ------------------------------------------------------------------ #
    # Änderungen erkennen (steuert die Statistik-Abfragen)
    # ------------------------------------------------------------------ #

    def note_statuses(self, statuses: list[dict[str, Any]], now: datetime) -> None:
        """Neue eigene Status seit Start registrieren (nicht beim ersten Mal)."""
        if self._seen is None:
            self._seen = set()
            self._since = now
        for status in statuses:
            sid = status.get("id")
            if sid is None or sid in self._seen:
                continue
            self._seen.add(sid)
            created = parse_dt(status.get("createdAt"))
            if self._since is not None and (created is None or created >= self._since):
                self.changed_at = now

    def _deleted(self, sid: Any, now: datetime) -> None:
        self.forget(sid)
        self.changed_at = now

    def forget(self, sid: Any) -> None:
        self._known.pop(sid, None)
        self._pending.pop(sid, None)
        self._board.pop(sid, None)

    # ------------------------------------------------------------------ #
    # Zusammenführen
    # ------------------------------------------------------------------ #

    def remember_checkin(self, status: dict[str, Any], now: datetime) -> None:
        """Frisch angelegten Check-in sofort übernehmen."""
        if isinstance(status, dict) and status.get("id") is not None:
            self._pending[status["id"]] = status
            self.changed_at = now

    def active_expected(
        self, dashboard_own: list[dict[str, Any]], now: datetime
    ) -> bool:
        """Läuft (bald) eine eigene Fahrt? Dann /user/statuses/active abfragen."""
        for status in [*self._pending.values(), *self._known.values(), *dashboard_own]:
            dep, arr = dep_live(status), arr_live(status)
            if (
                dep is not None
                and dep - ACTIVE_LEAD <= now
                and (arr is None or now <= arr + ACTIVE_TAIL)
            ):
                return True
        return False

    async def async_update(
        self,
        me: dict[str, Any] | None,
        active: dict[str, Any] | None,
        dashboard_own: list[dict[str, Any]] | None,
        future: list[dict[str, Any]] | None,
        future_complete: bool,
        now: datetime,
    ) -> None:
        """Quellen zusammenführen, Vergangenes und Gelöschtes vergessen.

        `dashboard_own`/`future` sind None, wenn sie in diesem Poll nicht
        (erfolgreich) abgefragt wurden.
        """
        dash = dashboard_own or []
        dash_ids = {s.get("id") for s in dash}
        future_ids = {s.get("id") for s in future or []}

        for status in [*self._pending.values(), *(future or []), *dash]:
            sid = status.get("id")
            if sid is not None and (sid in self._pending or is_own(status, me)):
                self._known[sid] = status
        for sid in future_ids | dash_ids:
            self._pending.pop(sid, None)  # liefert der Server jetzt selbst
        if active is not None and active.get("id") is not None:
            self._known.pop(active["id"], None)  # läuft gerade → nicht Teil der Kette

        refresh: list[tuple[datetime, Any]] = []
        for sid, status in list(self._known.items()):
            arr, dep = arr_live(status), dep_live(status)
            if arr is not None and arr < now:
                self.forget(sid)  # vorbei
            elif dep is None:
                continue
            elif dep >= now + DASHBOARD_WINDOW + timedelta(minutes=2):
                # Müsste in /dashboard/future stehen – fehlt es dort, wurde der
                # Check-in gelöscht (nur prüfbar, wenn die Liste vollständig ist).
                if (
                    future is not None
                    and future_complete
                    and sid not in future_ids | dash_ids
                ):
                    self._deleted(sid, now)
            elif (
                dashboard_own is not None
                and sid not in dash_ids
                and dep >= now - timedelta(minutes=5)
            ):
                # Kurz vor Abfahrt, aber nicht im Dashboard (z. B. vor über
                # 7 Tagen angelegt) → einzeln mit Echtzeit nachladen.
                refresh.append((dep, sid))

        for _dep, sid in sorted(refresh, key=lambda x: x[0])[:MAX_STATUS_REFRESH]:
            try:
                status = await self._api.async_get_status(sid)
            except TraewellingRateLimitError:
                return
            except TraewellingError as err:
                _LOGGER.debug("Status %s nicht abrufbar: %s", sid, err)
                continue
            if status is None:
                self._deleted(sid, now)
            else:
                self._known[sid] = status

    # ------------------------------------------------------------------ #
    # Kette + Echtzeit von der Abfahrtstafel
    # ------------------------------------------------------------------ #

    async def async_chain(
        self, active: dict[str, Any] | None, now: datetime
    ) -> list[dict[str, Any]]:
        """Anschlusskette nach der aktiven Fahrt bzw. ab der nächsten Fahrt
        (innerhalb einer Stunde), ergänzt um Echtzeit von der Abfahrtstafel."""
        chain = build_chain(active, list(self._known.values()), now, UPCOMING_HORIZON)
        lookups = 0
        out: list[dict[str, Any]] = []
        prev = active
        for leg in chain:
            sid = leg.get("id")
            board = self._board.get(sid)
            if _needs_board(prev, leg, now):
                stale = board is None or now - board["t"] >= BOARD_INTERVAL
                if stale and lookups < MAX_BOARD_LOOKUPS:
                    lookups += 1
                    fresh = await self._async_lookup_board(leg)
                    if fresh is not None:
                        board = self._board[sid] = {**fresh, "t": now}
                    elif board is None:
                        self._board[sid] = {
                            "t": now
                        }  # nichts gefunden → nicht jede Minute
                    else:
                        board["t"] = now
            elif dep_is_live(leg):
                self._board.pop(sid, None)  # Träwelling hat jetzt selbst Echtzeit
                board = None
            leg = _with_board(leg, board)  # noqa: PLW2901 – bewusst ersetzt
            out.append(leg)
            prev = leg
        return out

    async def _async_lookup_board(
        self, status: dict[str, Any]
    ) -> dict[str, Any] | None:
        station_id = station_of(origin_of(status)).get("id")
        planned = dep_planned(status)
        if station_id is None or planned is None:
            return None
        checkin = checkin_of(status) or {}
        when = (planned - timedelta(minutes=2)).isoformat()
        try:
            payload = await self._api.async_departures(int(station_id), when=when)
        except TraewellingError as err:
            _LOGGER.debug("Abfahrtstafel %s nicht abrufbar: %s", station_id, err)
            return None
        items = payload.get("data") if isinstance(payload, dict) else None
        trip_id = checkin.get("hafasId")
        line = first(checkin, "lineName", "number")
        hit = None
        for dep in items if isinstance(items, list) else []:
            if not isinstance(dep, dict):
                continue
            if trip_id and dep.get("tripId") == trip_id:
                hit = dep
                break
            dep_line = first(dep.get("line") or {}, "name", "productName", "id")
            if (
                hit is None
                and line
                and dep_line == line
                and parse_dt(dep.get("plannedWhen")) == planned
            ):
                hit = dep
        if hit is None:
            return None
        return {
            "real": hit.get("when"),
            "platform": hit.get("platform"),
            "cancelled": bool(hit.get("cancelled")),
        }


def _needs_board(
    prev: dict[str, Any] | None, nxt: dict[str, Any], now: datetime
) -> bool:
    """Anschluss hat keine Echtzeit, die Ankunft davor ist aber verspätet oder
    der Umstieg sieht (nach Plan des Anschlusses) kritisch aus."""
    if prev is None or dep_is_live(nxt):
        return False
    dep = dep_planned(nxt)
    if dep is None or dep > now + BOARD_HORIZON or dep < now - timedelta(minutes=10):
        return False
    if station_of(origin_of(nxt)).get("id") is None:
        return False
    arr_p, arr_l = arr_planned(prev), arr_live(prev)
    delayed = (
        arr_source(prev) != "plan"
        and arr_p
        and arr_l
        and arr_l - arr_p >= timedelta(minutes=2)
    )
    rating = (transfer(prev, nxt) or {}).get("rating")
    return bool(delayed) or rating in ("risk", "missed", "unknown")


def _with_board(status: dict[str, Any], board: dict[str, Any] | None) -> dict[str, Any]:
    """Status-Kopie mit Echtzeit/Gleis von der Abfahrtstafel."""
    if not board or dep_is_live(status):
        return status
    checkin = dict(checkin_of(status) or {})
    key = "origin" if "origin" in checkin else "from"
    origin = dict(checkin.get(key) or {})
    if board.get("real"):
        origin["departureReal"] = board["real"]
    if board.get("platform"):
        origin["departurePlatformReal"] = board["platform"]
    if board.get("cancelled"):
        origin["cancelled"] = True
    checkin[key] = origin
    ckey = "checkin" if "checkin" in status else "train"
    return {**status, ckey: checkin, "_board": bool(board.get("real"))}
