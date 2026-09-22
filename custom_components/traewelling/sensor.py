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

from .const import DOMAIN
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


def _active(data: dict[str, Any]) -> dict[str, Any] | None:
    status = data.get("active")
    return status if isinstance(status, dict) else None


def _user(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("user") or {}


def _stats(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("stats") or {}


def _progress(data: dict[str, Any]) -> float | None:
    dep = departure(_active(data))
    arr = arrival(_active(data))
    if dep is None or arr is None or arr <= dep:
        return None
    total = (arr - dep).total_seconds()
    done = (dt_util.utcnow() - dep).total_seconds()
    return round(max(0.0, min(100.0, done / total * 100)), 1)


def _minutes_left(data: dict[str, Any]) -> int | None:
    arr = arrival(_active(data))
    if arr is None:
        return None
    return max(0, int((arr - dt_util.utcnow()).total_seconds() // 60))


def _journey_attrs(data: dict[str, Any]) -> dict[str, Any]:
    status = _active(data)
    if status is None:
        return {}
    checkin = checkin_of(status) or {}
    origin = origin_of(status) or {}
    dest = destination_of(status) or {}
    operator = checkin.get("operator") or {}
    event = status.get("event") or {}
    return {
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


def _stat_value(data: dict[str, Any], *keys: str) -> Any:
    """Wert aus /statistics/overview, Fallback auf verschachtelte Summary."""
    stats = _stats(data)
    value = first(stats, *keys)
    if value is None:
        for nested_key in ("summary", "overview", "totals"):
            nested = stats.get(nested_key)
            if isinstance(nested, dict):
                value = first(nested, *keys)
                if value is not None:
                    break
    return value


def _longest_ride_attrs(data: dict[str, Any]) -> dict[str, Any]:
    stats = _stats(data)
    out: dict[str, Any] = {}
    for label, keys in (
        ("longest_by_distance", ("longest_checkin_by_distance", "longest_ride")),
        ("shortest_by_distance", ("shortest_checkin_by_distance", "shortest_ride")),
        ("longest_by_duration", ("longest_checkin_by_duration",)),
        ("shortest_by_duration", ("shortest_checkin_by_duration",)),
    ):
        status = first(stats, *keys)
        if not isinstance(status, dict):
            continue
        checkin = checkin_of(status) or {}
        dest = destination_of(status) or {}
        out[label] = {
            "line": first(checkin, "lineName", "number"),
            "destination": dest.get("name"),
            "distance_km": meters_to_km(checkin.get("distance")),
            "duration_minutes": checkin.get("duration"),
            "date": first(origin_of(status) or {}, "departurePlanned", "departure"),
        }
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

ACTIVE_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="current_line",
        translation_key="current_line",
        name="Aktuelle Fahrt",
        icon="mdi:train",
        value_fn=lambda d: first(checkin_of(_active(d)) or {}, "lineName", "number"),
        attr_fn=_journey_attrs,
    ),
    TrwlSensorDescription(
        key="current_origin",
        name="Start",
        icon="mdi:map-marker-outline",
        value_fn=lambda d: (origin_of(_active(d)) or {}).get("name"),
    ),
    TrwlSensorDescription(
        key="current_destination",
        name="Ziel",
        icon="mdi:map-marker-check",
        value_fn=lambda d: (destination_of(_active(d)) or {}).get("name"),
    ),
    TrwlSensorDescription(
        key="current_departure",
        name="Abfahrt",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        value_fn=lambda d: departure(_active(d)),
    ),
    TrwlSensorDescription(
        key="current_arrival",
        name="Ankunft",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-end",
        value_fn=lambda d: arrival(_active(d)),
    ),
    TrwlSensorDescription(
        key="current_delay_departure",
        name="Verspätung Abfahrt",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-alert-outline",
        value_fn=lambda d: delay_minutes(
            departure(_active(d), real=False), departure(_active(d))
        ),
    ),
    TrwlSensorDescription(
        key="current_delay_arrival",
        name="Verspätung Ankunft",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-alert",
        value_fn=lambda d: delay_minutes(
            arrival(_active(d), real=False), arrival(_active(d))
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
        value_fn=lambda d: meters_to_km((checkin_of(_active(d)) or {}).get("distance")),
    ),
    TrwlSensorDescription(
        key="current_points",
        name="Punkte aktuelle Fahrt",
        icon="mdi:star-outline",
        value_fn=lambda d: (checkin_of(_active(d)) or {}).get("points"),
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
        value_fn=lambda d: meters_to_km(
            first(_user(d), "totalDistance", "trainDistance")
        )
        or meters_to_km(_stat_value(d, "distance", "total_distance", "totalDistance")),
    ),
    TrwlSensorDescription(
        key="duration_total",
        name="Reisezeit gesamt",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        value_fn=lambda d: minutes_to_hours(
            first(_user(d), "totalDuration", "trainDuration")
        )
        or minutes_to_hours(_stat_value(d, "duration", "total_duration")),
    ),
    TrwlSensorDescription(
        key="checkins_total",
        name="Check-ins gesamt",
        icon="mdi:ticket-confirmation",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _stat_value(
            d, "checkin_count", "checkins", "total_checkins", "totalCheckins", "count"
        ),
        attr_fn=_longest_ride_attrs,
    ),
    TrwlSensorDescription(
        key="active_days",
        name="Aktive Reisetage",
        icon="mdi:calendar-check",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _stat_value(d, "active_days", "activeDays", "days"),
    ),
    TrwlSensorDescription(
        key="checkins_month",
        name="Check-ins diesen Monat",
        icon="mdi:calendar-month",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: history_count(
            history_entry(_history(d), "months", _month_key())
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
            history_entry(_history(d), "months", _month_key())
        ),
    ),
    TrwlSensorDescription(
        key="checkins_year",
        name="Check-ins dieses Jahr",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: history_count(
            history_entry(_history(d), "years", _year_key())
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
            history_entry(_history(d), "years", _year_key())
        ),
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
