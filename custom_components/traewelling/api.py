"""Schmaler Client für die Träwelling-REST-API (v1)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession

from .cache import TtlCache
from .const import DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 20

# Eindeutig identifizierbar für die Träwelling-Betreiber: Name, Version, Kontakt
# und – sobald bekannt – der Träwelling-Account (@username), auf Wunsch der Betreiber.
USER_AGENT_CONTACT = "+https://github.com/v8b-kg/trwl_ha_integr"

# Fallback, wenn Träwelling 429 ohne Retry-After schickt.
DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 3600

# Zwischenspeicher (Sekunden). Stationsdaten ändern sich praktisch nie,
# Abfahrten und Fahrtverläufe nur kurz, damit mehrere Geräte bzw. Karte und
# Hintergrund-Abfrage sich eine Antwort teilen.
TTL_AUTOCOMPLETE = 6 * 3600
TTL_NEARBY = 24 * 3600
TTL_STATION_HISTORY = 10 * 60
TTL_TICKETS = 10 * 60
TTL_DEPARTURES = 20
TTL_TRIP = 30


class TraewellingError(Exception):
    """Allgemeiner API-Fehler."""


class TraewellingAuthError(TraewellingError):
    """Token ungültig, abgelaufen oder ohne passenden Scope."""


class TraewellingRateLimitError(TraewellingError):
    """429 – Rate-Limit erreicht. `retry_after` in Sekunden."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"Rate-Limit von Träwelling erreicht – nächster Versuch in {self.retry_after} s"
        )


class TraewellingCheckinError(TraewellingError):
    """Check-in abgelehnt (z. B. Überschneidung mit anderer Fahrt)."""


def _message(payload: Any, body: str) -> str:
    """Fehlermeldung aus der API-Antwort lesbar machen (JSON-„message“, Umlaute)."""
    message = None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
    if not isinstance(message, str) or not message.strip():
        message = (body or "").strip()[:200] or "keine Details"
    return message


def _data(payload: Any) -> Any:
    """Träwelling verpackt Antworten meist in {"data": ...}."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _as_list(payload: Any) -> list[Any]:
    data = _data(payload) if payload is not None else None
    return data if isinstance(data, list) else []


def _as_dict(payload: Any) -> dict[str, Any] | None:
    data = _data(payload) if payload is not None else None
    return data if isinstance(data, dict) else None


def _has_next(payload: Any) -> bool:
    links = payload.get("links") if isinstance(payload, dict) else None
    return isinstance(links, dict) and bool(links.get("next"))


class TraewellingApi:
    """Minimaler async Client für die Endpunkte, die wir brauchen."""

    def __init__(
        self,
        session: ClientSession,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        username: str | None = None,
        version: str = "0",
    ) -> None:
        self._session = session
        self._token = token
        self._base = base_url.rstrip("/")
        self._version = version
        self._username: str | None = username
        # Bis zu diesem Zeitpunkt (time.monotonic) werden keine Anfragen gesendet.
        self._blocked_until = 0.0
        self._cache = TtlCache()

    @property
    def user_agent(self) -> str:
        user = f"; @{self._username}" if self._username else ""
        return f"trwl-ha-integration/{self._version} (Home Assistant; {USER_AGENT_CONTACT}{user})"

    @property
    def rate_limited_for(self) -> float:
        """Verbleibende Sperrzeit in Sekunden (0 = frei)."""
        return max(0.0, self._blocked_until - time.monotonic())

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #

    def _block(self, retry_after: str | None, path: str) -> TraewellingRateLimitError:
        """Retry-After (Sekunden oder HTTP-Datum) auswerten und Sperre setzen."""
        wait: float = DEFAULT_RETRY_AFTER
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                try:
                    wait = parsedate_to_datetime(retry_after).timestamp() - time.time()
                except (TypeError, ValueError):
                    wait = DEFAULT_RETRY_AFTER
        wait = min(max(wait, 1), MAX_RETRY_AFTER)
        self._blocked_until = time.monotonic() + wait
        _LOGGER.warning(
            "Träwelling-Rate-Limit erreicht (%s) – pausiere alle Anfragen für %d s",
            path,
            wait,
        )
        return TraewellingRateLimitError(wait)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any, str]:
        """Eine Anfrage senden → (Status, JSON oder None, Rohtext).

        Die Antwort wird immer vollständig gelesen und freigegeben.
        """
        remaining = self.rate_limited_for
        if remaining > 0:
            raise TraewellingRateLimitError(remaining)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        url = f"{self._base}/api/v1/{path.lstrip('/')}"
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, params=params, json=body
                ) as resp:
                    if resp.status == 429:
                        raise self._block(resp.headers.get("Retry-After"), path)
                    text = await resp.text()
                    status = resp.status
        except TraewellingError:
            raise
        except TimeoutError as err:
            raise TraewellingError(f"Timeout bei {path}") from err
        except ClientError as err:
            raise TraewellingError(f"Verbindungsfehler bei {path}: {err}") from err

        try:
            payload = json.loads(text) if text.strip() else None
        except ValueError:
            payload = None
        if status in (401, 403):
            raise TraewellingAuthError(
                f"Nicht autorisiert ({status}) für {path} – Token ungültig oder fehlender Scope"
            )
        _LOGGER.debug("%s %s -> %s", method, path, status)
        return status, payload, text

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, allow_404: bool = False
    ) -> Any:
        status, payload, text = await self._request("GET", path, params=params)
        if status == 404 and allow_404:
            return None
        if status >= 400:
            raise TraewellingError(f"{_message(payload, text)} (HTTP {status})")
        return payload

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        conflict_message: str | None = None,
    ) -> Any:
        """Schreibende Anfrage. Fachliche Fehler (400/409 …) als CheckinError."""
        status, payload, _text = await self._request(method, path, body=body)
        if status == 409:
            raise TraewellingCheckinError(
                conflict_message
                or "Du bist in diesem Zeitraum schon in eine andere Fahrt eingecheckt."
            )
        if status >= 400:
            message = (
                payload.get("message") or payload.get("error")
                if isinstance(payload, dict)
                else None
            )
            raise TraewellingCheckinError(
                str(message) if message else f"HTTP {status} für {path}"
            )
        return payload

    async def _pages(self, path: str, pages: int) -> tuple[list[dict[str, Any]], bool]:
        """Bis zu `pages` Seiten laden → (Einträge, vollständig?)."""
        items: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            payload = await self._get(path, params={"page": page}, allow_404=True)
            batch = [x for x in _as_list(payload) if isinstance(x, dict)]
            items.extend(batch)
            if not batch or not _has_next(payload):
                return items, True
        return items, False

    def _cached(self, key: tuple[Any, ...], ttl: float, fetch: Any) -> Any:
        return self._cache.get_or_fetch(key, ttl, fetch)

    def invalidate_own(self) -> None:
        """Nach eigenen Änderungen (Check-in, Fahrkarte): betroffene Caches leeren."""
        self._cache.invalidate(lambda key: key[0] in ("history", "tickets"))

    # ------------------------------------------------------------------ #
    # Lesen (read-statuses / read-statistics)
    # ------------------------------------------------------------------ #

    async def async_get_self(self) -> dict[str, Any]:
        """Profil des authentifizierten Nutzers (Punkte, Gesamtdistanz, ...)."""
        user = _data(await self._get("auth/user")) or {}
        if isinstance(user, dict) and isinstance(user.get("username"), str):
            self._username = user["username"].strip() or None
        return user

    async def async_get_active_status(self) -> dict[str, Any] | None:
        """Aktueller Check-in oder None (Träwelling: 204/404 ohne Fahrt)."""
        return _as_dict(await self._get("user/statuses/active", allow_404=True)) or None

    async def async_get_dashboard_page(
        self, page: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """GET /dashboard – eine Seite (15) der neuesten Status von dir und allen,
        denen du folgst, absteigend nach Abfahrt → (Status, weitere Seite?)."""
        payload = await self._get("dashboard", params={"page": page}, allow_404=True)
        items = [x for x in _as_list(payload) if isinstance(x, dict)]
        return items, bool(items) and _has_next(payload)

    async def async_get_future(
        self, pages: int = 3
    ) -> tuple[list[dict[str, Any]], bool]:
        """GET /dashboard/future – eigene Check-ins >20 min voraus → (Status, vollständig?).

        Träwelling sortiert absteigend (späteste zuerst, 15 je Seite) – die
        nächsten Fahrten stehen also hinten. Deshalb ggf. weiterblättern.
        """
        return await self._pages("dashboard/future", pages)

    async def async_get_status(self, status_id: Any) -> dict[str, Any] | None:
        """GET /status/{id} – ein einzelner Status (None = gelöscht/nicht sichtbar)."""
        return _as_dict(await self._get(f"status/{int(status_id)}", allow_404=True))

    async def async_get_statistics_overview(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics/overview – serverseitig 1 h gecacht."""
        return _as_dict(
            await self._get(
                "statistics/overview",
                params={"from": date_from, "until": date_to},
                allow_404=True,
            )
        )

    async def async_get_statistics_history(self) -> dict[str, Any] | None:
        """GET /statistics/history – Jahre/Monate/Wochen, serverseitig 6 h gecacht."""
        return _as_dict(await self._get("statistics/history", allow_404=True))

    async def async_get_statistics_favorites(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics/favorites – Lieblingsstationen, -linien, -strecken."""
        return _as_dict(
            await self._get(
                "statistics/favorites",
                params={"from": date_from, "until": date_to},
                allow_404=True,
            )
        )

    async def async_get_statistics_personal(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics – Verkehrsmittel, Betreiber, Reisezwecke."""
        return _as_dict(
            await self._get(
                "statistics",
                params={"from": date_from, "until": date_to},
                allow_404=True,
            )
        )

    async def async_get_leaderboard_friends(self) -> list[dict[str, Any]] | None:
        """GET /leaderboard/friends – Rangliste der letzten 7 Tage unter Freunden."""
        data = _data(await self._get("leaderboard/friends", allow_404=True))
        return data if isinstance(data, list) else None

    # ------------------------------------------------------------------ #
    # Check-in (write-statuses) – lesende Aufrufe mit Zwischenspeicher
    # ------------------------------------------------------------------ #

    async def async_search_stations(self, query: str) -> list[dict[str, Any]]:
        """GET /trains/station/autocomplete/{query} – max. 10 Treffer."""
        query = query.strip()

        async def fetch() -> list[dict[str, Any]]:
            payload = await self._get(
                f"trains/station/autocomplete/{quote(query, safe='')}", allow_404=True
            )
            return _as_list(payload)

        return await self._cached(
            ("autocomplete", query.casefold()), TTL_AUTOCOMPLETE, fetch
        )

    async def async_nearby_station(
        self, latitude: float, longitude: float
    ) -> dict[str, Any] | None:
        """GET /trains/station/nearby – nächste Station zu Koordinaten (~10 m genau gecacht)."""
        lat, lon = round(latitude, 4), round(longitude, 4)

        async def fetch() -> dict[str, Any] | None:
            # 404 = keine Station in der Nähe – wird mitgespeichert, andere
            # Fehler nicht.
            payload = await self._get(
                "trains/station/nearby",
                params={"latitude": lat, "longitude": lon},
                allow_404=True,
            )
            return _as_dict(payload)

        return await self._cached(("nearby", lat, lon), TTL_NEARBY, fetch)

    async def async_station_history(self) -> list[dict[str, Any]]:
        """GET /trains/station/history – zuletzt genutzte Stationen."""

        async def fetch() -> list[dict[str, Any]]:
            return _as_list(await self._get("trains/station/history", allow_404=True))

        return await self._cached(("history",), TTL_STATION_HISTORY, fetch)

    async def async_departures(
        self, station_id: int, when: str | None = None, travel_type: str | None = None
    ) -> dict[str, Any]:
        """GET /station/{id}/departures – Live-Abfahrten inkl. meta.station/times."""
        params: dict[str, Any] = {}
        if when:
            params["when"] = when
        if travel_type:
            params["travelType"] = travel_type

        async def fetch() -> dict[str, Any]:
            payload = await self._get(
                f"station/{int(station_id)}/departures", params=params
            )
            return payload if isinstance(payload, dict) else {"data": [], "meta": {}}

        key = ("departures", int(station_id), when or "", travel_type or "")
        return await self._cached(key, TTL_DEPARTURES, fetch)

    async def async_trip(self, trip_id: str, line_name: str) -> dict[str, Any]:
        """GET /trains/trip – Fahrt mit allen Halten."""

        async def fetch() -> dict[str, Any]:
            payload = await self._get(
                "trains/trip", params={"hafasTripId": trip_id, "lineName": line_name}
            )
            return _data(payload) or {}

        return await self._cached(("trip", trip_id, line_name), TTL_TRIP, fetch)

    async def async_checkin(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /trains/checkin."""
        try:
            return _data(await self._send("POST", "trains/checkin", body)) or {}
        finally:
            self.invalidate_own()

    # ------------------------------------------------------------------ #
    # Fahrkarten
    # ------------------------------------------------------------------ #

    async def async_tickets(self, valid_on: str | None = None) -> list[dict[str, Any]]:
        """GET /tickets – eigene Fahrkarten, optional nur die am Tag gültigen."""
        params = {"validOn": valid_on} if valid_on else None

        async def fetch() -> list[dict[str, Any]]:
            return _as_list(await self._get("tickets", params=params, allow_404=True))

        return await self._cached(("tickets", valid_on or ""), TTL_TICKETS, fetch)

    async def async_assign_ticket(self, status_id: int, ticket_id: str | None) -> Any:
        """PUT /statuses/{id}/tickets – Fahrkarte zuordnen (None = entfernen)."""
        try:
            return await self._send(
                "PUT", f"statuses/{int(status_id)}/tickets", {"ticketId": ticket_id}
            )
        finally:
            self.invalidate_own()

    # ------------------------------------------------------------------ #
    # Likes (write-likes)
    # ------------------------------------------------------------------ #

    async def async_like(self, status_id: int, like: bool = True) -> dict[str, Any]:
        """POST/DELETE /status/{id}/like – Status liken bzw. Like zurücknehmen."""
        payload = await self._send(
            "POST" if like else "DELETE",
            f"status/{int(status_id)}/like",
            conflict_message="Diesen Status hast du schon geliked.",
        )
        return _as_dict(payload) or {}
