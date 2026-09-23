"""Hilfsfunktionen zum robusten Auslesen der Träwelling-Antworten.

Die API benennt Felder über die Zeit um (siehe API_CHANGELOG.md), deshalb wird
hier überall mit mehreren Kandidaten-Keys gearbeitet statt mit festen Pfaden.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


def first(data: Any, *keys: str, default: Any = None) -> Any:
    """Ersten vorhandenen (nicht-None) Key aus einem Dict zurückgeben."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def checkin_of(status: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fahrt-Objekt eines Status: neu `checkin`, früher `train`."""
    if not isinstance(status, dict):
        return None
    value = first(status, "checkin", "train")
    return value if isinstance(value, dict) else None


def origin_of(status: dict[str, Any] | None) -> dict[str, Any] | None:
    checkin = checkin_of(status) or {}
    value = first(checkin, "origin", "from")
    return value if isinstance(value, dict) else None


def destination_of(status: dict[str, Any] | None) -> dict[str, Any] | None:
    checkin = checkin_of(status) or {}
    value = first(checkin, "destination", "to")
    return value if isinstance(value, dict) else None


def status_user_id(status: dict[str, Any] | None) -> Any:
    """ID des Verfassers: neu `user`, früher `userDetails` bzw. flach."""
    if not isinstance(status, dict):
        return None
    for key in ("user", "userDetails"):
        value = status.get(key)
        if isinstance(value, dict) and value.get("id") is not None:
            return value["id"]
        if isinstance(value, (int, str)):
            return value
    return first(status, "userId", "user_id")


def parse_dt(value: Any) -> datetime | None:
    """ISO-8601-String in ein aware datetime wandeln."""
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed


def departure(status: dict[str, Any] | None, real: bool = True) -> datetime | None:
    stop = origin_of(status) or {}
    keys = (
        ("departureReal", "departurePlanned", "departure")
        if real
        else ("departurePlanned", "departure")
    )
    return parse_dt(first(stop, *keys))


def arrival(status: dict[str, Any] | None, real: bool = True) -> datetime | None:
    stop = destination_of(status) or {}
    keys = (
        ("arrivalReal", "arrivalPlanned", "arrival")
        if real
        else ("arrivalPlanned", "arrival")
    )
    return parse_dt(first(stop, *keys))


def delay_minutes(planned: datetime | None, real: datetime | None) -> int | None:
    if planned is None or real is None:
        return None
    return int(round((real - planned).total_seconds() / 60))


def meters_to_km(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(value / 1000, 1)


def minutes_to_hours(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(value / 60, 1)


GROUP_ALIASES = {
    "yearly":  ("yearly", "years", "year"),
    "monthly": ("monthly", "months", "month"),
    "weekly":  ("weekly", "weeks", "week"),
}


def history_entry(
    history: dict[str, Any] | None, group: str, period: str
) -> dict[str, Any] | None:
    """Eintrag aus /statistics/history holen.

    Die API liefert Listen unter `yearly`, `monthly` und `weekly`; jeder
    Eintrag hat `period` ("2026" bzw. "2026-09"), `period_type`,
    `checkin_count` und `distance_km`.
    """
    if not isinstance(history, dict):
        return None
    data = history.get("data") if isinstance(history.get("data"), dict) else history

    bucket = None
    for candidate in GROUP_ALIASES.get(group, (group,)):
        if candidate in data:
            bucket = data[candidate]
            break
    if bucket is None:
        return None

    if isinstance(bucket, list):
        for item in bucket:
            if not isinstance(item, dict):
                continue
            label = first(item, "period", "key", "date", "label")
            if str(label) == period:
                return item
        return None

    if isinstance(bucket, dict):
        entry = bucket.get(period)
        if isinstance(entry, dict):
            return entry
        if isinstance(entry, (int, float)):
            return {"checkin_count": entry}
    return None


def history_count(entry: dict[str, Any] | None) -> int | None:
    value = first(entry or {}, "checkin_count", "count", "checkins", "amount")
    return int(value) if isinstance(value, (int, float)) else None


def history_distance_km(entry: dict[str, Any] | None) -> float | None:
    """`distance_km` ist bereits in Kilometern, `distance` waere in Metern."""
    if not isinstance(entry, dict):
        return None
    value = entry.get("distance_km")
    if isinstance(value, (int, float)):
        return round(float(value), 1)
    return meters_to_km(first(entry, "distance", "totalDistance"))
