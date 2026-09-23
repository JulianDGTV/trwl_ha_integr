"""Sensoren für aktive Fahrt und Statistiken."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STATE_IDLE, STATE_TRAVELLING, STATE_UPCOMING
from .coordinator import TraewellingCoordinator
from .entity import TraewellingEntity
from .helpers import (
    arrival,
    checkin_of,
    delay_minutes,
    departure,
    destination_of,
    first,
    history_count,
    history_distance_km,
    history_entry,
    meters_to_km,
    minutes_to_hours,
    origin_of,
)


@dataclass(frozen=True, kw_only=True)
class TrwlSensorDescription(SensorEntityDescription):
    """Sensorbeschreibung mit Wert- und Attributfunktion."""

    value_fn: Callable[[dict[str, Any]], Any]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


# --------------------------------------------------------------------------- #
# Zugriffs-Helfer
# --------------------------------------------------------------------------- #


def _trip(data: dict[str, Any]) -> dict[str, Any] | None:
    """Die gerade anzuzeigende Fahrt: laufend, sonst demnächst startend."""
    status = data.get("trip")
    if isinstance(status, dict):
        return status
    # Fallback, falls der Coordinator noch nichts aufgeloest hat.
    status = data.get("active")
    return status if isinstance(status, dict) else None


def _trip_state(data: dict[str, Any]) -> str:
    return data.get("trip_state") or (
        STATE_TRAVELLING if isinstance(data.get("active"), dict) else STATE_IDLE
    )


def _is_travelling(data: dict[str, Any]) -> bool:
    return _trip_state(data) == STATE_TRAVELLING


def _upcoming(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("upcoming")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _minutes_until_departure(data: dict[str, Any]) -> int | None:
    dep = departure(_trip(data))
    if dep is None:
        return None
    return max(0, int((dep - dt_util.utcnow()).total_seconds() // 60))


def _user(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("user") or {}


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    """`/statistics/overview` liefert {"summary": {...}}."""
    stats = data.get("stats") or {}
    summary = stats.get("summary")
    return summary if isinstance(summary, dict) else stats


def _progress(data: dict[str, Any]) -> float | None:
    dep = departure(_trip(data))
    arr = arrival(_trip(data))
    if dep is None or arr is None or arr <= dep:
        return None
    total = (arr - dep).total_seconds()
    done = (dt_util.utcnow() - dep).total_seconds()
    return round(max(0.0, min(100.0, done / total * 100)), 1)


def _minutes_left(data: dict[str, Any]) -> int | None:
    if not _is_travelling(data):
        return None
    arr = arrival(_trip(data))
    if arr is None:
        return None
    return max(0, int((arr - dt_util.utcnow()).total_seconds() // 60))


def _journey_attrs(data: dict[str, Any]) -> dict[str, Any]:
    status = _trip(data)
    if status is None:
        return {}
    checkin = checkin_of(status) or {}
    origin = origin_of(status) or {}
    dest = destination_of(status) or {}
    operator = checkin.get("operator") or {}
    event = status.get("event") or {}
    next_up = _upcoming(data)
    return {
        "fahrtstatus": _trip_state(data),
        "departure_in_minutes": _minutes_until_departure(data),
        "planned_trips": len(next_up),
        "status_id": status.get("id"),
        "body": status.get("body"),
        "line": first(checkin, "lineName", "number"),
        "journey_number": checkin.get("journeyNumber"),
        "category": checkin.get("category"),
        "operator": operator.get("name") if isinstance(operator, dict) else None,
        "origin": origin.get("name"),
        "origin_platform": first(
            origin, "departurePlatformReal", "departurePlatformPlanned", "platform"
        ),
        "destination": dest.get("name"),
        "destination_platform": first(
            dest, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"
        ),
        "departure_planned": first(origin, "departurePlanned", "departure"),
        "departure_real": first(origin, "departureReal"),
        "arrival_planned": first(dest, "arrivalPlanned", "arrival"),
        "arrival_real": first(dest, "arrivalReal"),
        "distance_km": meters_to_km(checkin.get("distance")),
        "duration_minutes": checkin.get("duration"),
        "points": checkin.get("points"),
        "event": event.get("name") if isinstance(event, dict) else None,
        "url": f"https://traewelling.de/status/{status.get('id')}"
        if status.get("id")
        else None,
    }


def _longest_ride_attrs(data: dict[str, Any]) -> dict[str, Any]:
    """Laengste/kuerzeste Fahrt als StatusResource im Summary."""
    summary = _summary(data)
    out: dict[str, Any] = {}
    for label, keys in (
        ("longest_by_distance", ("longest_checkin_by_distance", "longest_ride")),
        ("shortest_by_distance", ("shortest_checkin_by_distance", "shortest_ride")),
        ("longest_by_duration", ("longest_checkin_by_duration",)),
        ("shortest_by_duration", ("shortest_checkin_by_duration",)),
    ):
        status = first(summary, *keys)
        if not isinstance(status, dict):
            continue
        checkin = checkin_of(status) or {}
        out[label] = {
            "line": first(checkin, "lineName", "number"),
            "origin": (origin_of(status) or {}).get("name"),
            "destination": (destination_of(status) or {}).get("name"),
            "distance_km": meters_to_km(checkin.get("distance")),
            "duration_minutes": checkin.get("duration"),
            "date": first(origin_of(status) or {}, "departurePlanned", "departure"),
        }
    return out


def _favorites(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    favorites = data.get("favorites") or {}
    items = favorites.get(key)
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _top_name(data: dict[str, Any], key: str, *name_keys: str) -> str | None:
    items = _favorites(data, key)
    if not items:
        return None
    return first(items[0], *name_keys)


def _route_label(item: dict[str, Any] | None) -> str | None:
    """Routen haben kein Namensfeld, nur origin und destination."""
    if not isinstance(item, dict):
        return None
    origin = item.get("origin")
    destination = item.get("destination")
    if origin and destination:
        return f"{origin} \u2192 {destination}"
    return origin or destination


def _top_route(data: dict[str, Any]) -> str | None:
    items = _favorites(data, "routes")
    return _route_label(items[0]) if items else None


def _top_attrs(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Top 10 als Attribut, plus Anzahl und Distanz des Spitzenreiters."""
    items = _favorites(data, key)
    if not items:
        return {}
    top = items[0]
    out: dict[str, Any] = {"top10": items[:10], "count": top.get("count")}
    if key == "routes":
        out["top10"] = [
            {**item, "label": _route_label(item)} for item in items[:10]
        ]
        out["origin"] = top.get("origin")
        out["destination"] = top.get("destination")
    if top.get("distance_km") is not None:
        out["distance_km"] = top["distance_km"]
    return out


def _month_key() -> str:
    return dt_util.now().strftime("%Y-%m")


def _year_key() -> str:
    return dt_util.now().strftime("%Y")


def _history(data: dict[str, Any]) -> dict[str, Any] | None:
    history = data.get("history")
    return history if isinstance(history, dict) else None


# --------------------------------------------------------------------------- #
# Sensordefinitionen
# --------------------------------------------------------------------------- #

def _next_planned(data: dict[str, Any]) -> dict[str, Any] | None:
    """Nächste geplante Fahrt – unabhängig vom Vorschaufenster."""
    items = _upcoming(data)
    return items[0] if items else None


def _planned_attrs(data: dict[str, Any]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for status in _upcoming(data)[:5]:
        checkin = checkin_of(status) or {}
        dep = departure(status)
        out.append(
            {
                "line": first(checkin, "lineName", "number"),
                "origin": (origin_of(status) or {}).get("name"),
                "destination": (destination_of(status) or {}).get("name"),
                "departure": dep.isoformat() if dep else None,
                "status_id": status.get("id"),
            }
        )
    return {"trips": out, "count": len(_upcoming(data))}


ACTIVE_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="trip_state",
        name="Fahrtstatus",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_TRAVELLING, STATE_UPCOMING, STATE_IDLE],
        icon="mdi:transit-connection-variant",
        value_fn=_trip_state,
        attr_fn=_journey_attrs,
    ),
    TrwlSensorDescription(
        key="departure_in",
        name="Abfahrt in",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-fast",
        value_fn=_minutes_until_departure,
    ),
    TrwlSensorDescription(
        key="next_planned_departure",
        name="Nächste geplante Fahrt",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=lambda d: departure(_next_planned(d)),
        attr_fn=_planned_attrs,
    ),
    TrwlSensorDescription(
        key="current_line",
        translation_key="current_line",
        name="Aktuelle Fahrt",
        icon="mdi:train",
        value_fn=lambda d: first(checkin_of(_trip(d)) or {}, "lineName", "number"),
        attr_fn=_journey_attrs,
    ),
    TrwlSensorDescription(
        key="current_origin",
        name="Start",
        icon="mdi:map-marker-outline",
        value_fn=lambda d: (origin_of(_trip(d)) or {}).get("name"),
    ),
    TrwlSensorDescription(
        key="current_destination",
        name="Ziel",
        icon="mdi:map-marker-check",
        value_fn=lambda d: (destination_of(_trip(d)) or {}).get("name"),
    ),
    TrwlSensorDescription(
        key="current_departure",
        name="Abfahrt",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        value_fn=lambda d: departure(_trip(d)),
    ),
    TrwlSensorDescription(
        key="current_arrival",
        name="Ankunft",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-end",
        value_fn=lambda d: arrival(_trip(d)),
    ),
    TrwlSensorDescription(
        key="current_delay_departure",
        name="Verspätung Abfahrt",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-alert-outline",
        value_fn=lambda d: delay_minutes(
            departure(_trip(d), real=False), departure(_trip(d))
        ),
    ),
    TrwlSensorDescription(
        key="current_delay_arrival",
        name="Verspätung Ankunft",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-alert",
        value_fn=lambda d: delay_minutes(
            arrival(_trip(d), real=False), arrival(_trip(d))
        ),
    ),
    TrwlSensorDescription(
        key="current_minutes_left",
        name="Restfahrzeit",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_fn=_minutes_left,
    ),
    TrwlSensorDescription(
        key="current_progress",
        name="Fahrtfortschritt",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:progress-clock",
        value_fn=_progress,
    ),
    TrwlSensorDescription(
        key="current_distance",
        name="Distanz aktuelle Fahrt",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: meters_to_km((checkin_of(_trip(d)) or {}).get("distance")),
    ),
    TrwlSensorDescription(
        key="current_points",
        name="Punkte aktuelle Fahrt",
        icon="mdi:star-outline",
        value_fn=lambda d: (checkin_of(_trip(d)) or {}).get("points"),
    ),
)

STATS_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="points_total",
        name="Punkte gesamt",
        icon="mdi:star",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: first(_user(d), "points", "totalPoints"),
    ),
    TrwlSensorDescription(
        key="distance_total",
        name="Distanz gesamt",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:map-marker-distance",
        # total_distance_km kommt bereits in Kilometern, das Profil in Metern.
        value_fn=lambda d: _summary(d).get("total_distance_km")
        or meters_to_km(first(_user(d), "totalDistance", "trainDistance")),
    ),
    TrwlSensorDescription(
        key="distance_mean",
        name="Distanz je Fahrt",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve",
        value_fn=lambda d: _summary(d).get("mean_distance_km"),
    ),
    TrwlSensorDescription(
        key="duration_total",
        name="Reisezeit gesamt",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        value_fn=lambda d: minutes_to_hours(
            first(_user(d), "totalDuration", "trainDuration")
        ),
    ),
    TrwlSensorDescription(
        key="checkins_total",
        name="Check-ins gesamt",
        icon="mdi:ticket-confirmation",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _summary(d).get("total_checkins"),
        attr_fn=_longest_ride_attrs,
    ),
    TrwlSensorDescription(
        key="active_days",
        name="Aktive Reisetage",
        icon="mdi:calendar-check",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _summary(d).get("active_days"),
    ),
    TrwlSensorDescription(
        key="checkins_month",
        name="Check-ins diesen Monat",
        icon="mdi:calendar-month",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: history_count(
            history_entry(_history(d), "monthly", _month_key())
        ),
    ),
    TrwlSensorDescription(
        key="distance_month",
        name="Distanz diesen Monat",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: history_distance_km(
            history_entry(_history(d), "monthly", _month_key())
        ),
    ),
    TrwlSensorDescription(
        key="checkins_year",
        name="Check-ins dieses Jahr",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: history_count(
            history_entry(_history(d), "yearly", _year_key())
        ),
    ),
    TrwlSensorDescription(
        key="distance_year",
        name="Distanz dieses Jahr",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: history_distance_km(
            history_entry(_history(d), "yearly", _year_key())
        ),
    ),
    TrwlSensorDescription(
        key="favorite_station",
        name="Häufigste Station",
        icon="mdi:home-map-marker",
        value_fn=lambda d: _top_name(d, "stations", "name"),
        attr_fn=lambda d: _top_attrs(d, "stations"),
    ),
    TrwlSensorDescription(
        key="favorite_line",
        name="Häufigste Linie",
        icon="mdi:transit-connection-variant",
        value_fn=lambda d: _top_name(d, "lines", "linename", "lineName", "number", "name"),
        attr_fn=lambda d: _top_attrs(d, "lines"),
    ),
    TrwlSensorDescription(
        key="favorite_route",
        name="Häufigste Strecke",
        icon="mdi:routes",
        value_fn=_top_route,
        attr_fn=lambda d: _top_attrs(d, "routes"),
    ),
    TrwlSensorDescription(
        key="username",
        name="Benutzername",
        icon="mdi:account",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _user(d).get("username"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren anlegen."""
    coordinator: TraewellingCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TraewellingSensor(coordinator, description)
        for description in (*ACTIVE_SENSORS, *STATS_SENSORS)
    )


class TraewellingSensor(TraewellingEntity, SensorEntity):
    """Ein einzelner Träwelling-Sensor."""

    entity_description: TrwlSensorDescription

    @property
    def native_value(self) -> Any:
        try:
            value = self.entity_description.value_fn(self.coordinator.data or {})
        except (TypeError, ValueError, AttributeError):
            return None
        if isinstance(value, datetime):
            return value
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        try:
            return self.entity_description.attr_fn(self.coordinator.data or {})
        except (TypeError, ValueError, AttributeError):
            return None
