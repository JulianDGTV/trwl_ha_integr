"""Services für den Check-in direkt aus Home Assistant.

Die Check-in-Karte ruft diese Services mit `return_response` auf. So bleibt
der Träwelling-Token in Home Assistant und landet nie im Browser.
"""

from __future__ import annotations

import logging
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

from .api import TraewellingAuthError, TraewellingCheckinError, TraewellingError
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
            station = await _guard(api.async_nearby_station(lat, lon))
            return {"stations": [s for s in [_station(station)] if s]}

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
        # Sofort neu laden, damit Sensoren und Karte die neue Fahrt zeigen.
        await coord.async_request_refresh()

        status = result.get("status") or {}
        points = result.get("points") or {}
        return {
            "status_id": status.get("id"),
            "url": f"https://traewelling.de/status/{status['id']}" if status.get("id") else None,
            "points": points.get("points") if isinstance(points, dict) else points,
            "also_on_this_connection": [
                first(s.get("userDetails") or {}, "displayName", "username")
                for s in (result.get("alsoOnThisConnection") or [])
                if isinstance(s, dict)
            ],
        }

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
