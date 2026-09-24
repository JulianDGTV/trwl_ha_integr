"""Schmaler Client für die Träwelling-REST-API (v1)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession

from .const import DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 20


def _version() -> str:
    try:
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text("utf-8"))
        return str(manifest.get("version", "0"))
    except (OSError, ValueError):
        return "0"


# Eindeutig identifizierbar für die Träwelling-Betreiber: Name, Version, Kontakt.
USER_AGENT = (
    f"trwl-ha-integration/{_version()} "
    "(Home Assistant; +https://github.com/JulianDGTV/trwl_ha_integr)"
)

def _error_text(status: int, body: str) -> str:
    """Fehlermeldung aus der API-Antwort lesbar machen (JSON-„message“, Umlaute)."""
    message = None
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
    except ValueError:
        pass
    if not isinstance(message, str) or not message.strip():
        message = (body or "").strip()[:200] or "keine Details"
    return f"{message} (HTTP {status})"


# Fallback, wenn Träwelling 429 ohne Retry-After schickt.
DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 3600


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


class TraewellingApi:
    """Minimaler async Client für die Endpunkte, die wir brauchen."""

    def __init__(
        self,
        session: ClientSession,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._token = token
        self._base = base_url.rstrip("/")
        # Bis zu diesem Zeitpunkt (time.monotonic) werden keine Anfragen gesendet.
        self._blocked_until = 0.0

    @property
    def rate_limited_for(self) -> float:
        """Verbleibende Sperrzeit in Sekunden (0 = frei)."""
        return max(0.0, self._blocked_until - time.monotonic())

    def _check_rate_limit(self) -> None:
        remaining = self.rate_limited_for
        if remaining > 0:
            raise TraewellingRateLimitError(remaining)

    def _handle_429(self, resp: Any, path: str) -> None:
        """Retry-After (Sekunden oder HTTP-Datum) auswerten und Sperre setzen."""
        raw = resp.headers.get("Retry-After") if resp.headers else None
        wait: float = DEFAULT_RETRY_AFTER
        if raw:
            try:
                wait = float(raw)
            except ValueError:
                try:
                    when = parsedate_to_datetime(raw)
                    wait = when.timestamp() - time.time()
                except (TypeError, ValueError):
                    wait = DEFAULT_RETRY_AFTER
        wait = min(max(wait, 1), MAX_RETRY_AFTER)
        self._blocked_until = time.monotonic() + wait
        _LOGGER.warning(
            "Träwelling-Rate-Limit erreicht (%s) – pausiere alle Anfragen für %d s",
            path,
            wait,
        )
        raise TraewellingRateLimitError(wait)

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        url = f"{self._base}/api/v1/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._check_rate_limit()
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.get(url, headers=headers, params=params)
                if resp.status == 429:
                    self._handle_429(resp, path)
                if resp.status in (401, 403):
                    raise TraewellingAuthError(
                        f"Nicht autorisiert ({resp.status}) für {path} – "
                        "Token ungültig oder fehlender Scope"
                    )
                if resp.status == 404 and allow_404:
                    return None
                if resp.status >= 400:
                    raise TraewellingError(_error_text(resp.status, await resp.text()))
                payload = await resp.json(content_type=None)
        except TraewellingError:
            raise
        except asyncio.TimeoutError as err:
            raise TraewellingError(f"Timeout bei {path}") from err
        except ClientError as err:
            raise TraewellingError(f"Verbindungsfehler bei {path}: {err}") from err

        _LOGGER.debug("GET %s -> %s", path, payload)
        return payload

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        """POST mit JSON-Body. Fachliche Fehler (400/409) als CheckinError."""
        return await self._send("POST", path, body)

    async def _put(self, path: str, body: dict[str, Any]) -> Any:
        return await self._send("PUT", path, body)

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        conflict_message: str | None = None,
    ) -> Any:
        url = f"{self._base}/api/v1/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._check_rate_limit()
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.request(method, url, headers=headers, json=body)
                if resp.status == 429:
                    self._handle_429(resp, path)
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = None
        except TraewellingError:
            raise
        except asyncio.TimeoutError as err:
            raise TraewellingError(f"Timeout bei {path}") from err
        except ClientError as err:
            raise TraewellingError(f"Verbindungsfehler bei {path}: {err}") from err

        if resp.status in (401, 403):
            raise TraewellingAuthError(
                f"Nicht autorisiert ({resp.status}) für {path} – "
                "Token ungültig oder fehlender Scope"
            )
        if resp.status == 409:
            raise TraewellingCheckinError(
                conflict_message
                or "Du bist in diesem Zeitraum schon in eine andere Fahrt eingecheckt."
            )
        if resp.status >= 400:
            message = None
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
            raise TraewellingCheckinError(
                str(message) if message else f"HTTP {resp.status} für {path}"
            )
        _LOGGER.debug("%s %s -> %s", method, path, payload)
        return payload

    @staticmethod
    def _data(payload: Any) -> Any:
        """Träwelling verpackt Antworten meist in {"data": ...}."""
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    async def async_get_self(self) -> dict[str, Any]:
        """Profil des authentifizierten Nutzers (Punkte, Gesamtdistanz, ...)."""
        return self._data(await self._get("auth/user")) or {}

    async def async_get_active_status(self) -> dict[str, Any] | None:
        """Aktueller Check-in oder None, wenn gerade keine Fahrt läuft."""
        payload = await self._get("user/statuses/active", allow_404=True)
        if payload is None:
            return None
        return self._data(payload) or None

    async def async_get_dashboard(self, pages: int = 2) -> list[dict[str, Any]]:
        """GET /dashboard – neueste Status von dir und allen, denen du folgst."""
        statuses: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            payload = await self._get("dashboard", params={"page": page}, allow_404=True)
            items = self._data(payload) if payload is not None else None
            if not isinstance(items, list) or not items:
                break
            statuses.extend(items)
            links = payload.get("links") if isinstance(payload, dict) else None
            if isinstance(links, dict) and not links.get("next"):
                break
        return statuses

    async def async_get_future(self) -> list[dict[str, Any]]:
        """GET /dashboard/future – eigene Check-ins, die >20 min in der Zukunft starten."""
        payload = await self._get("dashboard/future", allow_404=True)
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, list) else []

    async def async_get_statistics_overview(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics/overview – benötigt Scope read-statistics."""
        payload = await self._get(
            "statistics/overview",
            params={"from": date_from, "until": date_to},
            allow_404=True,
        )
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_history(self) -> dict[str, Any] | None:
        """GET /statistics/history – Check-ins/Distanz je Jahr, Monat und Woche."""
        payload = await self._get("statistics/history", allow_404=True)
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_favorites(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics/favorites – Lieblingsstationen, -linien, -strecken."""
        payload = await self._get(
            "statistics/favorites",
            params={"from": date_from, "until": date_to},
            allow_404=True,
        )
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_personal(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics – Verkehrsmittel, Betreiber, Reisezwecke."""
        payload = await self._get(
            "statistics", params={"from": date_from, "until": date_to}, allow_404=True
        )
        return self._data(payload) if payload is not None else None

    async def async_get_leaderboard_friends(self) -> list[dict[str, Any]] | None:
        """GET /leaderboard/friends – Rangliste der letzten 7 Tage unter Freunden."""
        payload = await self._get("leaderboard/friends", allow_404=True)
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, list) else None

    # ------------------------------------------------------------------ #
    # Check-in (Scope write-statuses)
    # ------------------------------------------------------------------ #

    async def async_search_stations(self, query: str) -> list[dict[str, Any]]:
        """GET /trains/station/autocomplete/{query} – max. 10 Treffer."""
        payload = await self._get(
            f"trains/station/autocomplete/{quote(query.strip(), safe='')}",
            allow_404=True,
        )
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, list) else []

    async def async_nearby_station(
        self, latitude: float, longitude: float
    ) -> dict[str, Any] | None:
        """GET /trains/station/nearby – nächste Station zu Koordinaten."""
        payload = await self._get(
            "trains/station/nearby",
            params={"latitude": latitude, "longitude": longitude},
            allow_404=True,
        )
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, dict) else None

    async def async_station_history(self) -> list[dict[str, Any]]:
        """GET /trains/station/history – zuletzt genutzte Stationen."""
        payload = await self._get("trains/station/history", allow_404=True)
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, list) else []

    async def async_departures(
        self,
        station_id: int,
        when: str | None = None,
        travel_type: str | None = None,
    ) -> dict[str, Any]:
        """GET /station/{id}/departures – Live-Abfahrten inkl. meta.station/times."""
        params: dict[str, Any] = {}
        if when:
            params["when"] = when
        if travel_type:
            params["travelType"] = travel_type
        payload = await self._get(f"station/{int(station_id)}/departures", params=params)
        if not isinstance(payload, dict):
            return {"data": [], "meta": {}}
        return payload

    async def async_trip(self, trip_id: str, line_name: str) -> dict[str, Any]:
        """GET /trains/trip – Fahrt mit allen Halten."""
        payload = await self._get(
            "trains/trip", params={"hafasTripId": trip_id, "lineName": line_name}
        )
        return self._data(payload) or {}

    async def async_checkin(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /trains/checkin."""
        return self._data(await self._post("trains/checkin", body)) or {}

    # ------------------------------------------------------------------ #
    # Fahrkarten
    # ------------------------------------------------------------------ #

    async def async_tickets(self, valid_on: str | None = None) -> list[dict[str, Any]]:
        """GET /tickets – eigene Fahrkarten, optional nur die am Tag gültigen."""
        params = {"validOn": valid_on} if valid_on else None
        payload = await self._get("tickets", params=params, allow_404=True)
        data = self._data(payload) if payload is not None else None
        return data if isinstance(data, list) else []

    async def async_assign_ticket(self, status_id: int, ticket_id: str | None) -> Any:
        """PUT /statuses/{id}/tickets – Fahrkarte zuordnen (None = entfernen)."""
        return await self._put(f"statuses/{int(status_id)}/tickets", {"ticketId": ticket_id})

    # ------------------------------------------------------------------ #
    # Likes (Scope write-likes)
    # ------------------------------------------------------------------ #

    async def async_like(self, status_id: int, like: bool = True) -> dict[str, Any]:
        """POST/DELETE /status/{id}/like – Status liken bzw. Like zurücknehmen."""
        payload = await self._send(
            "POST" if like else "DELETE",
            f"status/{int(status_id)}/like",
            None,
            conflict_message="Diesen Status hast du schon geliked.",
        )
        data = self._data(payload)
        return data if isinstance(data, dict) else {}
