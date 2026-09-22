"""Schmaler Client für die Träwelling-REST-API (v1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession

from .const import DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 20


class TraewellingError(Exception):
    """Allgemeiner API-Fehler."""


class TraewellingAuthError(TraewellingError):
    """Token ungültig, abgelaufen oder ohne passenden Scope."""


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
            "User-Agent": "home-assistant-traewelling/1.2",
        }
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.get(url, headers=headers, params=params)
                if resp.status in (401, 403):
                    raise TraewellingAuthError(
                        f"Nicht autorisiert ({resp.status}) für {path} – "
                        "Token ungültig oder fehlender Scope"
                    )
                if resp.status == 404 and allow_404:
                    return None
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    raise TraewellingError(f"HTTP {resp.status} für {path}: {body}")
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
        url = f"{self._base}/api/v1/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "home-assistant-traewelling/1.2",
        }
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.post(url, headers=headers, json=body)
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = None
        except asyncio.TimeoutError as err:
            raise TraewellingError(f"Timeout bei {path}") from err
        except ClientError as err:
            raise TraewellingError(f"Verbindungsfehler bei {path}: {err}") from err

        if resp.status in (401, 403):
            raise TraewellingAuthError(
                f"Nicht autorisiert ({resp.status}) für {path} – "
                "der Token braucht den Scope 'write-statuses'"
            )
        if resp.status == 409:
            raise TraewellingCheckinError(
                "Du bist in diesem Zeitraum schon in eine andere Fahrt eingecheckt."
            )
        if resp.status >= 400:
            message = None
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
            raise TraewellingCheckinError(
                str(message) if message else f"HTTP {resp.status} für {path}"
            )
        _LOGGER.debug("POST %s -> %s", path, payload)
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

    async def async_get_statistics_overview(
        self, date_from: str, date_to: str
    ) -> dict[str, Any] | None:
        """GET /statistics/overview – benötigt Scope read-statistics."""
        payload = await self._get(
            "statistics/overview",
            params={"from": date_from, "to": date_to},
            allow_404=True,
        )
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_history(self) -> dict[str, Any] | None:
        """GET /statistics/history – Check-ins/Distanz je Jahr, Monat und Woche."""
        payload = await self._get("statistics/history", allow_404=True)
        return self._data(payload) if payload is not None else None

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
