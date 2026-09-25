"""Hilfsfunktionen zum robusten Auslesen der Träwelling-Antworten.

Die API benennt Felder über die Zeit um (siehe API_CHANGELOG.md), deshalb wird
hier überall mit mehreren Kandidaten-Keys gearbeitet statt mit festen Pfaden.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


def user_of(status: dict[str, Any]) -> dict[str, Any]:
    """Nutzer eines Status: neu `userDetails`, früher (vor 2024-08) direkt am Status."""
    details = status.get("userDetails")
    if isinstance(details, dict):
        return details
    return {
        "id": status.get("user"),
        "username": status.get("username"),
        "displayName": status.get("username"),
        "profilePicture": status.get("profilePicture"),
    }


def is_own(status: dict[str, Any], me: dict[str, Any] | None) -> bool:
    """Gehört der Status dem angemeldeten Nutzer?"""
    me = me or {}
    my_ids = {str(v) for v in (me.get("id"), me.get("uuid")) if v is not None}
    user = user_of(status)
    if my_ids and user.get("id") is not None:
        return str(user["id"]) in my_ids
    return bool(me.get("username")) and user.get("username") == me.get("username")


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


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie zwischen zwei Koordinaten in Metern (Haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


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


def history_entry(
    history: dict[str, Any] | None, group: str, key: str
) -> dict[str, Any] | None:
    """Eintrag aus /statistics/history holen.

    `group` ist "years", "months" oder "weeks"; `key` z. B. "2026-09".
    Die API kann die Buckets als Dict (key -> werte) oder als Liste von
    Objekten liefern – beides wird unterstützt.
    """
    if not isinstance(history, dict):
        return None

    bucket = None
    aliases = {"years": "yearly", "months": "monthly", "weeks": "weekly"}
    for candidate in (
        aliases.get(group, group),
        group,
        group.rstrip("s"),
        f"by{group.capitalize()}",
    ):
        if candidate in history:
            bucket = history[candidate]
            break
    if bucket is None:
        return None

    if isinstance(bucket, dict):
        entry = bucket.get(key)
        if isinstance(entry, dict):
            return entry
        if isinstance(entry, (int, float)):
            return {"count": entry}
        return None

    if isinstance(bucket, list):
        for item in bucket:
            if not isinstance(item, dict):
                continue
            label = first(
                item, "key", "date", "period", "label", "year", "month", "week"
            )
            if str(label) == key:
                return item
    return None


def history_count(entry: dict[str, Any] | None) -> int | None:
    value = first(
        entry or {}, "count", "checkins", "checkinCount", "checkin_count", "amount"
    )
    return int(value) if isinstance(value, (int, float)) else None


def history_distance_km(entry: dict[str, Any] | None) -> float | None:
    entry = entry or {}
    km = first(entry, "distance_km", "km")
    if isinstance(km, (int, float)):
        return round(float(km), 1)
    return meters_to_km(first(entry, "distance", "totalDistance", "distance_total"))
