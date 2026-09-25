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
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import TraewellingConfigEntry
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
from .journey import arr_live, arr_source, station_of, transfer


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


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


def _upcoming(data: dict[str, Any]) -> dict[str, Any] | None:
    status = data.get("upcoming")
    return status if isinstance(status, dict) else None


def _upcoming_attrs(data: dict[str, Any]) -> dict[str, Any]:
    status = _upcoming(data)
    if status is None:
        return {}
    attrs = _status_attrs(status)
    dep = departure(status)
    if dep is not None:
        attrs["minutes_until"] = max(
            0, int((dep - dt_util.utcnow()).total_seconds() // 60)
        )
    attrs["after_current"] = _active(data) is not None
    chain = _chain(data)
    legs = []
    prev = _active(data)
    for leg in chain:
        legs.append({**_status_attrs(leg), "transfer": transfer(prev, leg)})
        prev = leg
    attrs["chain"] = legs
    attrs["warnings"] = [
        leg["transfer"]["warning"]
        for leg in legs
        if isinstance(leg.get("transfer"), dict) and leg["transfer"].get("warning")
    ]
    attrs["transfers"] = len(legs) - (0 if _active(data) is not None else 1)
    last = chain[-1] if chain else None
    if last is not None:
        dest = destination_of(last) or {}
        attrs["final_destination"] = dest.get("name")
        attrs["final_arrival_planned"] = first(dest, "arrivalPlanned", "arrival")
        final = arr_live(last)
        attrs["final_arrival"] = final.isoformat() if final else None
    return attrs


def _chain(data: dict[str, Any]) -> list[dict[str, Any]]:
    chain = data.get("chain")
    return [s for s in chain if isinstance(s, dict)] if isinstance(chain, list) else []


def _next_transfer(data: dict[str, Any]) -> dict[str, Any] | None:
    """Nächster Umstieg: aktive Fahrt → 1. Anschluss, sonst 1. → 2. Fahrt."""
    chain = _chain(data)
    legs = [_active(data), *chain] if _active(data) is not None else chain
    if len(legs) < 2:
        return None
    info = transfer(legs[0], legs[1])
    if info is None:
        return None
    nxt = _status_attrs(legs[1])
    return {
        **info,
        "from_line": _status_attrs(legs[0]).get("line"),
        "to_line": nxt.get("line"),
        "to_destination": nxt.get("destination"),
        "departure_planned": nxt.get("departure_planned"),
        "departure_real": nxt.get("departure_real"),
        "status_id": nxt.get("status_id"),
    }


def _journey_attrs(data: dict[str, Any]) -> dict[str, Any]:
    return _status_attrs(_active(data))


def _status_attrs(status: dict[str, Any] | None) -> dict[str, Any]:
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
        "origin_station_id": station_of(origin).get("id"),
        "destination_station_id": station_of(dest).get("id"),
        "cancelled": bool(origin.get("cancelled") or dest.get("cancelled")),
        "destination_platform": first(
            dest, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"
        ),
        "departure_planned": first(origin, "departurePlanned", "departure"),
        "departure_real": first(origin, "departureReal"),
        "arrival_planned": first(dest, "arrivalPlanned", "arrival"),
        "arrival_real": first(dest, "arrivalReal"),
        "arrival_expected": _iso(arr_live(status)),
        "arrival_estimated": arr_source(status) == "estimate",
        "distance_km": meters_to_km(checkin.get("distance")),
        "duration_minutes": checkin.get("duration"),
        "points": checkin.get("points"),
        "event": event.get("name") if isinstance(event, dict) else None,
        "url": f"https://traewelling.de/status/{status.get('id')}"
        if status.get("id")
        else None,
    }


CHECKIN_KEYS = ("total_checkins", "checkin_count", "checkins", "totalCheckins", "count")
DISTANCE_KM_KEYS = ("total_distance_km", "distance_km")
DISTANCE_M_KEYS = ("total_distance", "totalDistance", "distance")

CATEGORY_LABELS = {
    "nationalExpress": "Fernverkehr (ICE)",
    "national": "Fernverkehr (IC/EC)",
    "regionalExp": "Regionalexpress",
    "regional": "Regionalverkehr",
    "suburban": "S-Bahn",
    "subway": "U-Bahn",
    "tram": "Tram",
    "bus": "Bus",
    "ferry": "Fähre",
    "taxi": "Taxi",
    "plane": "Flugzeug",
}
PURPOSE_LABELS = {0: "Privat", 1: "Geschäftlich", 2: "Pendeln"}


def _summary(data: dict[str, Any], source: str = "stats") -> dict[str, Any]:
    """`summary` aus /statistics/overview (Fallback: Top-Level)."""
    stats = data.get(source)
    if not isinstance(stats, dict):
        return {}
    summary = stats.get("summary")
    return summary if isinstance(summary, dict) else stats


def _stat_value(data: dict[str, Any], *keys: str, source: str = "stats") -> Any:
    return first(_summary(data, source), *keys)


def _stat_km(data: dict[str, Any], source: str = "stats") -> float | None:
    summary = _summary(data, source)
    km = first(summary, *DISTANCE_KM_KEYS)
    if isinstance(km, (int, float)):
        return round(float(km), 1)
    return meters_to_km(first(summary, *DISTANCE_M_KEYS))


def _ride(status: Any) -> dict[str, Any] | None:
    if not isinstance(status, dict):
        return None
    checkin = checkin_of(status) or {}
    origin = origin_of(status) or {}
    dest = destination_of(status) or {}
    return {
        "line": first(checkin, "lineName", "number"),
        "origin": origin.get("name"),
        "destination": dest.get("name"),
        "distance_km": meters_to_km(checkin.get("distance")),
        "duration_minutes": checkin.get("duration"),
        "date": first(origin, "departurePlanned", "departure"),
        "url": f"https://traewelling.de/status/{status['id']}"
        if status.get("id")
        else None,
    }


def _longest_ride_attrs(data: dict[str, Any]) -> dict[str, Any]:
    summary = _summary(data)
    out: dict[str, Any] = {}
    for label, key in (
        ("longest_by_distance", "longest_checkin_by_distance"),
        ("shortest_by_distance", "shortest_checkin_by_distance"),
        ("longest_by_duration", "longest_checkin_by_duration"),
        ("shortest_by_duration", "shortest_checkin_by_duration"),
    ):
        ride = _ride(summary.get(key))
        if ride:
            out[label] = ride
    return out


def _longest_year(data: dict[str, Any]) -> dict[str, Any] | None:
    return _ride(_summary(data, "stats_year").get("longest_checkin_by_distance"))


def _month_key() -> str:
    return dt_util.now().strftime("%Y-%m")


def _year_key() -> str:
    return dt_util.now().strftime("%Y")


def _history(data: dict[str, Any]) -> dict[str, Any] | None:
    history = data.get("history")
    return history if isinstance(history, dict) else None


def _period_count(data: dict[str, Any], source: str, group: str, key: str) -> Any:
    value = _stat_value(data, *CHECKIN_KEYS, source=source)
    if isinstance(value, (int, float)):
        return int(value)
    return history_count(history_entry(_history(data), group, key))


def _period_distance(data: dict[str, Any], source: str, group: str, key: str) -> Any:
    value = _stat_km(data, source)
    if value is not None:
        return value
    return history_distance_km(history_entry(_history(data), group, key))


def _fav(data: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    fav = data.get("favorites")
    items = fav.get(kind) if isinstance(fav, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _fav_route_label(item: dict[str, Any]) -> str:
    return f"{item.get('origin')} → {item.get('destination')}"


def _categories(data: dict[str, Any]) -> list[dict[str, Any]]:
    personal = data.get("personal")
    rows = personal.get("categories") if isinstance(personal, dict) else None
    if not isinstance(rows, list):
        return []
    out = [
        {
            "name": CATEGORY_LABELS.get(str(r.get("name")), r.get("name")),
            "key": r.get("name"),
            "count": r.get("count"),
            "hours": minutes_to_hours(r.get("duration")),
        }
        for r in rows
        if isinstance(r, dict)
    ]
    return sorted(out, key=lambda r: r.get("count") or 0, reverse=True)


def _operators(data: dict[str, Any]) -> list[dict[str, Any]]:
    personal = data.get("personal")
    rows = personal.get("operators") if isinstance(personal, dict) else None
    if not isinstance(rows, list):
        return []
    out = [
        {
            "name": r.get("name"),
            "count": r.get("count"),
            "hours": minutes_to_hours(r.get("duration")),
        }
        for r in rows
        if isinstance(r, dict)
    ]
    return sorted(out, key=lambda r: r.get("count") or 0, reverse=True)


def _purposes(data: dict[str, Any]) -> list[dict[str, Any]]:
    personal = data.get("personal")
    rows = personal.get("purpose") if isinstance(personal, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "name": PURPOSE_LABELS.get(r.get("reason"), str(r.get("reason"))),
            "count": r.get("count"),
            "hours": minutes_to_hours(r.get("duration")),
        }
        for r in rows
        if isinstance(r, dict)
    ]


def _leaderboard(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("leaderboard")
    if not isinstance(rows, list):
        return []
    me = _user(data)
    my_ids = {str(v) for v in (me.get("id"), me.get("uuid")) if v is not None}
    out = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        user = r.get("user") or {}
        out.append(
            {
                "rank": i + 1,
                "name": first(user, "displayName", "username", default="?"),
                "username": user.get("username"),
                "points": r.get("points"),
                "distance_km": meters_to_km(r.get("totalDistance")),
                "hours": minutes_to_hours(r.get("totalDuration")),
                "me": str(user.get("id")) in my_ids
                or (
                    bool(me.get("username"))
                    and user.get("username") == me.get("username")
                ),
            }
        )
    return out


def _my_rank(data: dict[str, Any]) -> int | None:
    return next((r["rank"] for r in _leaderboard(data) if r["me"]), None)


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


def _friends(data: dict[str, Any]) -> list[dict[str, Any]]:
    friends = data.get("friends")
    return friends if isinstance(friends, list) else []


UPCOMING_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="upcoming",
        name="Nächste Fahrt",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:train-car-passenger",
        value_fn=lambda d: departure(_upcoming(d)),
        attr_fn=_upcoming_attrs,
    ),
    TrwlSensorDescription(
        key="next_transfer",
        name="Nächster Umstieg",
        icon="mdi:swap-horizontal",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: (_next_transfer(d) or {}).get("minutes"),
        attr_fn=lambda d: _next_transfer(d) or {},
    ),
)

FRIENDS_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="friends_travelling",
        name="Freunde unterwegs",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(_friends(d)),
        attr_fn=lambda d: {
            "trips": _friends(d),
            "names": [t.get("name") for t in _friends(d)],
            "travelling": sum(1 for t in _friends(d) if not t.get("upcoming")),
            "soon": sum(1 for t in _friends(d) if t.get("upcoming")),
        },
    ),
)

STATS_SENSORS: tuple[TrwlSensorDescription, ...] = (
    TrwlSensorDescription(
        key="points_total",
        name="Punkte gesamt",
        icon="mdi:star",
        # Träwelling liefert hier die Punkte der letzten 7 Tage – der Wert
        # sinkt also auch wieder (daher kein TOTAL_INCREASING).
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: first(_user(d), "points", "totalPoints"),
    ),
    TrwlSensorDescription(
        key="distance_total",
        name="Distanz gesamt",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: (
            meters_to_km(first(_user(d), "totalDistance", "trainDistance"))
            or _stat_km(d)
        ),
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
        value_fn=lambda d: _stat_value(d, *CHECKIN_KEYS),
        attr_fn=_longest_ride_attrs,
    ),
    TrwlSensorDescription(
        key="active_days",
        name="Aktive Reisetage",
        icon="mdi:calendar-check",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _stat_value(d, "active_days", "activeDays"),
    ),
    TrwlSensorDescription(
        key="mean_distance",
        name="Durchschnittsdistanz",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler",
        value_fn=lambda d: _stat_value(d, "mean_distance_km"),
    ),
    TrwlSensorDescription(
        key="checkins_week",
        name="Check-ins diese Woche",
        icon="mdi:calendar-week",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _period_count(d, "stats_week", "weeks", ""),
    ),
    TrwlSensorDescription(
        key="distance_week",
        name="Distanz diese Woche",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _stat_km(d, "stats_week"),
    ),
    TrwlSensorDescription(
        key="checkins_month",
        name="Check-ins diesen Monat",
        icon="mdi:calendar-month",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _period_count(d, "stats_month", "months", _month_key()),
    ),
    TrwlSensorDescription(
        key="distance_month",
        name="Distanz diesen Monat",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _period_distance(d, "stats_month", "months", _month_key()),
    ),
    TrwlSensorDescription(
        key="checkins_year",
        name="Check-ins dieses Jahr",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _period_count(d, "stats_year", "years", _year_key()),
    ),
    TrwlSensorDescription(
        key="distance_year",
        name="Distanz dieses Jahr",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _period_distance(d, "stats_year", "years", _year_key()),
    ),
    TrwlSensorDescription(
        key="monthly_history",
        name="Monatsverlauf",
        icon="mdi:chart-bar",
        value_fn=lambda d: next(
            (m.get("checkins") for m in (d.get("monthly") or []) if m.get("current")),
            None,
        ),
        attr_fn=lambda d: {"months": d.get("monthly") or []},
    ),
    TrwlSensorDescription(
        key="longest_ride_year",
        name="Längste Fahrt dieses Jahr",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-path",
        value_fn=lambda d: (_longest_year(d) or {}).get("distance_km"),
        attr_fn=lambda d: _longest_year(d) or {},
    ),
    TrwlSensorDescription(
        key="favorite_station",
        name="Lieblingsstation",
        icon="mdi:bank",
        value_fn=lambda d: (_fav(d, "stations")[:1] or [{}])[0].get("name"),
        attr_fn=lambda d: {"period": "Dieses Jahr", "top": _fav(d, "stations")[:10]},
    ),
    TrwlSensorDescription(
        key="favorite_line",
        name="Lieblingslinie",
        icon="mdi:train-variant",
        value_fn=lambda d: (_fav(d, "lines")[:1] or [{}])[0].get("linename"),
        attr_fn=lambda d: {"period": "Dieses Jahr", "top": _fav(d, "lines")[:10]},
    ),
    TrwlSensorDescription(
        key="favorite_route",
        name="Lieblingsstrecke",
        icon="mdi:swap-horizontal",
        value_fn=lambda d: next(
            (_fav_route_label(r) for r in _fav(d, "routes")[:1]), None
        ),
        attr_fn=lambda d: {
            "period": "Dieses Jahr",
            "top": [
                {**r, "label": _fav_route_label(r)} for r in _fav(d, "routes")[:10]
            ],
        },
    ),
    TrwlSensorDescription(
        key="top_category",
        name="Häufigstes Verkehrsmittel",
        icon="mdi:train-bus",
        value_fn=lambda d: (_categories(d)[:1] or [{}])[0].get("name"),
        attr_fn=lambda d: {
            "period": "Dieses Jahr",
            "categories": _categories(d),
            "operators": _operators(d)[:10],
            "purposes": _purposes(d),
        },
    ),
    TrwlSensorDescription(
        key="friends_rank",
        name="Rang unter Freunden",
        icon="mdi:podium",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_my_rank,
        attr_fn=lambda d: {
            "period": "Letzte 7 Tage",
            "participants": len(_leaderboard(d)),
            "my_points": next((r["points"] for r in _leaderboard(d) if r["me"]), None),
            "leaderboard": _leaderboard(d)[:10],
        },
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
    entry: TraewellingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren anlegen."""
    coordinator = entry.runtime_data
    async_add_entities(
        TraewellingSensor(coordinator, description)
        for description in (
            *ACTIVE_SENSORS,
            *UPCOMING_SENSORS,
            *FRIENDS_SENSORS,
            *STATS_SENSORS,
        )
    )


class TraewellingSensor(TraewellingEntity, SensorEntity):
    """Ein einzelner Träwelling-Sensor."""

    entity_description: TrwlSensorDescription
    # Große bzw. sich ständig ändernde Listen nicht in die Datenbank schreiben
    # (im Zustand bleiben sie für Karten und Templates vollständig erhalten).
    _unrecorded_attributes = frozenset(
        {
            "chain",
            "warnings",
            "trips",
            "names",
            "leaderboard",
            "top",
            "months",
            "categories",
            "operators",
            "purposes",
        }
    )

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self.coordinator.data or {})
        except (TypeError, ValueError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        try:
            return self.entity_description.attr_fn(self.coordinator.data or {})
        except (TypeError, ValueError, AttributeError):
            return None
