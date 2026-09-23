"""Schmaler Client für die Träwelling-REST-API (v1)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 20


class TraewellingError(Exception):
    """Allgemeiner API-Fehler."""


class TraewellingAuthError(TraewellingError):
    """Token ungültig, abgelaufen oder ohne passenden Scope."""


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
        # Merker, welcher Endpunkt für geplante Fahrten funktioniert hat.
        self._upcoming_path: str | None = None

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
            "User-Agent": (
                "home-assistant-traewelling/1.1.0 "
                "(+https://github.com/JulianDGTV/trwl_ha_integr)"
            ),
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

    @staticmethod
    def _data(payload: Any) -> Any:
        """Träwelling verpackt Antworten in {"data": ...}."""
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

    async def async_get_upcoming_statuses(
        self,
        user_id: Any = None,
        username: str | None = None,
        days_ahead: int = 2,
    ) -> list[dict[str, Any]]:
        """Bereits eingecheckte, aber noch nicht gestartete Fahrten.

        Träwelling bietet dafür mehrere Wege an und hat sie über die Jahre
        umgebaut. Wir probieren sie der Reihe nach durch und merken uns den
        ersten, der eine Liste liefert:

        1. GET /dashboard/future  – zukünftige Check-ins des eigenen Feeds
        2. GET /status?user_id=&from=&to=  – seit 2026-05-18 mit Zeitfenster
        3. GET /user/{username}/statuses  – Profil-Timeline

        Rückgabe ist immer eine Liste von StatusResource-Dicts (ggf. leer).
        """
        today = date.today()
        window = {
            "from": today.isoformat(),
            "to": (today + timedelta(days=days_ahead)).isoformat(),
        }

        candidates: list[tuple[str, dict[str, Any] | None]] = [
            ("dashboard/future", None)
        ]
        if user_id is not None:
            candidates.append(("status", {"user_id": user_id, **window}))
            candidates.append(("statuses", {"user_id": user_id, **window}))
        if username:
            candidates.append((f"user/{username}/statuses", None))

        if self._upcoming_path is not None:
            # Bekannten Weg zuerst versuchen.
            candidates.sort(key=lambda c: c[0] != self._upcoming_path)

        last_error: TraewellingError | None = None
        for path, params in candidates:
            try:
                payload = await self._get(path, params=params, allow_404=True)
            except TraewellingAuthError:
                raise
            except TraewellingError as err:
                last_error = err
                continue
            if payload is None:
                continue
            data = self._data(payload)
            if isinstance(data, list):
                if self._upcoming_path != path:
                    _LOGGER.debug("Geplante Fahrten kommen von /%s", path)
                    self._upcoming_path = path
                return [item for item in data if isinstance(item, dict)]

        if last_error is not None:
            raise last_error
        return []

    async def async_get_statistics_overview(
        self, date_from: str, date_until: str
    ) -> dict[str, Any] | None:
        """GET /statistics/overview – Scope read-statistics.

        Antwort: {"data": {"summary": {total_checkins, active_days,
        total_distance_km, mean_distance_km, longest_checkin_by_distance, ...}}}
        Ohne Parameter würde die API nur die letzten 4 Wochen liefern.
        """
        payload = await self._get(
            "statistics/overview",
            params={"from": date_from, "until": date_until},
            allow_404=True,
        )
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_history(self) -> dict[str, Any] | None:
        """GET /statistics/history.

        Antwort: {"data": {"yearly": [{period, period_type, checkin_count,
        distance_km}], "monthly": [...], "weekly": [...]}}
        """
        payload = await self._get("statistics/history", allow_404=True)
        return self._data(payload) if payload is not None else None

    async def async_get_statistics_favorites(
        self, date_from: str, date_until: str
    ) -> dict[str, Any] | None:
        """GET /statistics/favorites – Top-10 Stationen, Linien und Routen."""
        payload = await self._get(
            "statistics/favorites",
            params={"from": date_from, "until": date_until},
            allow_404=True,
        )
        return self._data(payload) if payload is not None else None
