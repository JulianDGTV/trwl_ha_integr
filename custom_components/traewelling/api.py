"""Schmaler Client für die Träwelling-REST-API (v1)."""

from __future__ import annotations

import asyncio
import logging
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
            "User-Agent": "home-assistant-traewelling/1.0",
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
