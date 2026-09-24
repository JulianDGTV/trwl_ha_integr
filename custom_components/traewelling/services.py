"""Services für den Check-in direkt aus Home Assistant.

Die Check-in-Karte ruft diese Services mit `return_response` auf. So bleibt
der Träwelling-Token in Home Assistant und landet nie im Browser.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import (
    TraewellingAuthError,
    TraewellingCheckinError,
    TraewellingError,
    TraewellingRateLimitError,
)
from .const import DOMAIN
from .coordinator import TraewellingCoordinator
from .helpers import first

_LOGGER = logging.getLogger(__name__)

ATTR_ENTRY = "config_entry_id"

TRAVEL_TYPES = [
    "express", "regional", "suburban", "bus", "ferry", "subway", "tram", "taxi", "plane",
]
VISIBILITY = {"public": 0, "unlisted": 1, "followers": 2, "private": 3, "authenticated": 4}
BUSINESS = {"private": 0, "business": 1, "commute": 2}

SCOPE_HINT = (
    "Träwelling hat den Zugriff abgelehnt. Für den Check-in braucht der Token "
    "den Scope 'write-statuses' – neuen Token anlegen und unter Integration → "
    "⋮ → Neu konfigurieren eintragen."
)

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Optional("query"): cv.string,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
    }
)
DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Required("station_id"): vol.Coerce(int),
        vol.Optional("when"): cv.string,
        vol.Optional("travel_type"): vol.In(TRAVEL_TYPES),
    }
)
TRIP_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Required("trip_id"): cv.string,
        vol.Required("line_name"): cv.string,
    }
)
CHECKIN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Required("trip_id"): cv.string,
        vol.Required("line_name"): cv.string,
        vol.Required("start_id"): vol.Coerce(int),
        vol.Required("destination_id"): vol.Coerce(int),
        vol.Required("departure"): cv.string,
        vol.Required("arrival"): cv.string,
        vol.Optional("body"): vol.All(cv.string, vol.Length(max=280)),
        vol.Optional("visibility", default="public"): vol.In(list(VISIBILITY)),
        vol.Optional("business", default="private"): vol.In(list(BUSINESS)),
        vol.Optional("toot", default=False): cv.boolean,
        vol.Optional("ticket_id"): vol.Any(None, cv.string),
    }
)
LIKE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Required("status_id"): vol.Coerce(int),
        vol.Optional("like", default=True): cv.boolean,
    }
)
LIKE_SCOPE_HINT = (
    "Träwelling hat das Liken abgelehnt. Der Token braucht dafür den Scope "
    "'write-likes' – neuen Token anlegen und unter Integration → ⋮ → Neu "
    "konfigurieren eintragen."
)
TICKETS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Optional("date"): cv.string,  # YYYY-MM-DD, Standard: heute
    }
)


# --------------------------------------------------------------------------- #
# Aufbereitung – schlanke Dicts für die Karte
# --------------------------------------------------------------------------- #


def _station(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
    }


def _departure(raw: dict[str, Any]) -> dict[str, Any]:
    line = raw.get("line") or {}
    station = raw.get("station") or raw.get("stop") or {}
    return {
        "trip_id": raw.get("tripId"),
        "line_name": first(line, "name", "productName", "id"),
        "number": line.get("fahrtNr"),
        "product": first(line, "product", "mode"),
        "color": line.get("color"),
        "text_color": line.get("textColor"),
        "direction": first(raw, "direction", default=None)
        or (raw.get("destination") or {}).get("name"),
        "planned": raw.get("plannedWhen"),
        "real": raw.get("when"),
        "delay": raw.get("delay"),
        "platform": first(raw, "platform", "plannedPlatform"),
        "planned_platform": raw.get("plannedPlatform"),
        "cancelled": bool(raw.get("cancelled")),
        "station_id": station.get("id"),
        "station_name": station.get("name"),
    }


# „In der Nähe": Träwelling sucht serverseitig nur in einem kleinen Umkreis
# (Standard ~200 m). Findet es nichts, fragen wir Punkte auf immer größeren
# Ringen um den Standort ab und sortieren die Treffer nach echter Entfernung.
NEARBY_RINGS: tuple[tuple[int, int], ...] = ((400, 4), (1000, 6), (2000, 8))  # (Meter, Punkte)


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ring(lat: float, lon: float, meters: int, points: int) -> list[tuple[float, float]]:
    out = []
    for i in range(points):
        angle = 2 * math.pi * i / points
        dlat = meters * math.cos(angle) / 111320.0
        dlon = meters * math.sin(angle) / (111320.0 * max(0.01, math.cos(math.radians(lat))))
        out.append((lat + dlat, lon + dlon))
    return out


async def _nearby(api: Any, lat: float, lon: float) -> dict[str, Any]:
    """Nächste Station; bei Bedarf Suchradius stufenweise vergrößern."""
    found: dict[Any, dict[str, Any]] = {}

    def add(raw: Any) -> None:
        st = _station(raw)
        if st and st["id"] not in found:
            if isinstance(st.get("latitude"), (int, float)) and isinstance(st.get("longitude"), (int, float)):
                st["distance_m"] = round(_distance_m(lat, lon, st["latitude"], st["longitude"]))
            found[st["id"]] = st

    async def probe(plat: float, plon: float) -> Any:
        try:
            return await api.async_nearby_station(plat, plon)
        except (TraewellingRateLimitError, TraewellingAuthError) as err:
            async def _reraise() -> None:
                raise err

            return await _guard(_reraise())  # verständliche Fehlermeldung
        except TraewellingError:
            return None  # „keine Station gefunden" o. Ä. → nächster Punkt

    add(await probe(lat, lon))
    radius = 200
    if not found:
        for meters, points in NEARBY_RINGS:
            for plat, plon in _ring(lat, lon, meters, points):
                add(await probe(plat, plon))
            radius = meters
            if found:
                break

    stations = sorted(found.values(), key=lambda s: s.get("distance_m", 1e12))
    return {"stations": stations[:6], "radius_m": radius, "expanded": radius > 200}


def _ticket(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "valid_from": raw.get("validFrom"),
        "valid_until": raw.get("validUntil"),
        "trip_count": raw.get("tripCount"),
    }


def _stop(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "name": first(raw, "name", default=None) or (raw.get("station") or {}).get("name"),
        "arrival_planned": first(raw, "arrivalPlanned", "arrival"),
        "arrival_real": raw.get("arrivalReal"),
        "departure_planned": first(raw, "departurePlanned", "departure"),
        "departure_real": raw.get("departureReal"),
        "platform": first(raw, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"),
        "cancelled": bool(raw.get("cancelled")),
    }


# --------------------------------------------------------------------------- #
# Registrierung
# --------------------------------------------------------------------------- #


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> TraewellingCoordinator:
    coordinators: dict[str, TraewellingCoordinator] = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise ServiceValidationError("Träwelling ist nicht eingerichtet.")
    entry_id = call.data.get(ATTR_ENTRY)
    if entry_id:
        if entry_id not in coordinators:
            raise ServiceValidationError(f"Unbekannter Config-Entry {entry_id}.")
        return coordinators[entry_id]
    return next(iter(coordinators.values()))


async def _guard(coro):
    """API-Fehler in verständliche HA-Fehler übersetzen."""
    try:
        return await coro
    except TraewellingRateLimitError as err:
        raise HomeAssistantError(
            f"Träwelling bremst gerade (Rate-Limit). Bitte in {err.retry_after} s erneut versuchen."
        ) from err
    except TraewellingAuthError as err:
        raise HomeAssistantError(SCOPE_HINT) from err
    except TraewellingCheckinError as err:
        raise HomeAssistantError(f"Check-in abgelehnt: {err}") from err
    except TraewellingError as err:
        raise HomeAssistantError(f"Träwelling nicht erreichbar: {err}") from err


def async_setup_services(hass: HomeAssistant) -> None:
    """Services einmalig registrieren."""
    if hass.services.has_service(DOMAIN, "search_stations"):
        return

    async def search_stations(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        api = coord.api
        query = (call.data.get("query") or "").strip()
        lat, lon = call.data.get("latitude"), call.data.get("longitude")

        if query:
            stations = await _guard(api.async_search_stations(query))
            return {"stations": [s for s in map(_station, stations) if s]}

        if lat is not None and lon is not None:
            return await _nearby(api, lat, lon)

        # Ohne Suche: Heimatbahnhof + zuletzt genutzte Stationen.
        history = await _guard(api.async_station_history())
        user = (coord.data or {}).get("user") or {}
        home = _station(user.get("home"))
        return {
            "home": home,
            "stations": [s for s in map(_station, history) if s],
        }

    async def get_departures(call: ServiceCall) -> ServiceResponse:
        api = _coordinator(hass, call).api
        payload = await _guard(
            api.async_departures(
                call.data["station_id"],
                call.data.get("when"),
                call.data.get("travel_type"),
            )
        )
        meta = payload.get("meta") or {}
        items = payload.get("data") or []
        return {
            "station": _station(meta.get("station")),
            "times": meta.get("times") or {},
            "departures": [_departure(d) for d in items if isinstance(d, dict)],
        }

    async def get_trip(call: ServiceCall) -> ServiceResponse:
        api = _coordinator(hass, call).api
        trip = await _guard(api.async_trip(call.data["trip_id"], call.data["line_name"]))
        stops = trip.get("stopovers") or []
        return {
            "line_name": trip.get("lineName"),
            "category": trip.get("category"),
            "origin": (trip.get("origin") or {}).get("name"),
            "destination": (trip.get("destination") or {}).get("name"),
            "stops": [_stop(s) for s in stops if isinstance(s, dict)],
        }

    async def checkin(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        body: dict[str, Any] = {
            "tripId": call.data["trip_id"],
            "lineName": call.data["line_name"],
            "start": call.data["start_id"],
            "destination": call.data["destination_id"],
            "departure": call.data["departure"],
            "arrival": call.data["arrival"],
            "visibility": VISIBILITY[call.data["visibility"]],
            "business": BUSINESS[call.data["business"]],
            "toot": call.data["toot"],
        }
        if call.data.get("body"):
            body["body"] = call.data["body"]

        result = await _guard(coord.api.async_checkin(body))
        status = result.get("status") or {}
        coord.remember_checkin(status)

        # Fahrkarte nachträglich zuordnen. Schlägt das fehl, bleibt der
        # Check-in trotzdem bestehen – die Karte zeigt dann einen Hinweis.
        ticket_id = call.data.get("ticket_id")
        ticket_ok: bool | None = None
        ticket_error: str | None = None
        if ticket_id and status.get("id"):
            try:
                await coord.api.async_assign_ticket(status["id"], ticket_id)
                ticket_ok = True
                coord.last_ticket = {"id": ticket_id}
            except TraewellingError as err:
                ticket_ok = False
                ticket_error = str(err)
                _LOGGER.warning("Fahrkarte konnte nicht zugeordnet werden: %s", err)

        # Sofort neu laden, damit Sensoren und Karte die neue Fahrt zeigen.
        await coord.async_request_refresh()

        points = result.get("points") or {}
        return {
            "ticket_assigned": ticket_ok,
            "ticket_error": ticket_error,
            "status_id": status.get("id"),
            "url": f"https://traewelling.de/status/{status['id']}" if status.get("id") else None,
            "points": points.get("points") if isinstance(points, dict) else points,
            "also_on_this_connection": [
                first(s.get("userDetails") or {}, "displayName", "username")
                for s in (result.get("alsoOnThisConnection") or [])
                if isinstance(s, dict)
            ],
        }

    async def like(call: ServiceCall) -> ServiceResponse:
        """Status eines Freundes liken bzw. Like zurücknehmen."""
        coord = _coordinator(hass, call)
        status_id = call.data["status_id"]
        want = call.data["like"]
        try:
            result = await coord.api.async_like(status_id, want)
        except TraewellingAuthError as err:
            raise HomeAssistantError(LIKE_SCOPE_HINT) from err
        except TraewellingCheckinError:
            result = {}  # 409 = war schon (nicht) geliked → Zielzustand ist erreicht
        except TraewellingRateLimitError as err:
            raise HomeAssistantError(
                f"Träwelling bremst gerade (Rate-Limit). Bitte in {err.retry_after} s erneut versuchen."
            ) from err
        except TraewellingError as err:
            raise HomeAssistantError(f"Like fehlgeschlagen: {err}") from err
        count = result.get("count") if isinstance(result.get("count"), int) else None
        coord.set_like(status_id, want, count)
        return {"status_id": status_id, "liked": want, "likes": count}

    hass.services.async_register(
        DOMAIN, "like", like, LIKE_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )

    async def get_tickets(call: ServiceCall) -> ServiceResponse:
        """Am Tag gültige Fahrkarten + Vorschlag (zuletzt genutzte, falls gültig)."""
        coord = _coordinator(hass, call)
        valid_on = call.data.get("date") or dt_util.now().date().isoformat()
        try:
            raw = await coord.api.async_tickets(valid_on)
        except TraewellingAuthError:
            # Funktion für das Konto nicht verfügbar oder Scope fehlt → Feld ausblenden.
            return {"available": False, "tickets": [], "suggested": None}
        except TraewellingRateLimitError as err:
            raise HomeAssistantError(
                f"Träwelling bremst gerade (Rate-Limit). Bitte in {err.retry_after} s erneut versuchen."
            ) from err
        except TraewellingError as err:
            raise HomeAssistantError(f"Fahrkarten nicht abrufbar: {err}") from err

        tickets = [t for t in map(_ticket, raw) if t]
        last_id = (coord.last_ticket or {}).get("id")
        suggested = last_id if any(t["id"] == last_id for t in tickets) else None
        return {
            "available": True,
            "date": valid_on,
            "tickets": tickets,
            "last_used": last_id,
            "suggested": suggested,
        }

    hass.services.async_register(
        DOMAIN, "get_tickets", get_tickets, TICKETS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "search_stations", search_stations, SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_departures", get_departures, DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_trip", get_trip, TRIP_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "checkin", checkin, CHECKIN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
