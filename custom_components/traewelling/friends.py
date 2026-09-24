"""Aktive Fahrten der Leute, denen du folgst ("Freunde").

Quelle ist GET /api/v1/dashboard: die neuesten Status von dir und allen
Accounts, denen du folgst (inkl. privater Profile, die dich zugelassen haben).
Daraus werden alle Status herausgefiltert, deren Fahrt gerade läuft.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .helpers import (
    arrival,
    checkin_of,
    delay_minutes,
    departure,
    destination_of,
    first,
    meters_to_km,
    origin_of,
)

# Kleiner Puffer, damit eine Fahrt nicht in der Sekunde der Abfahrt
# bzw. Ankunft zwischen "aktiv" und "nicht aktiv" hin- und herspringt.
GRACE = timedelta(minutes=2)


def _user_of(status: dict[str, Any]) -> dict[str, Any]:
    details = status.get("userDetails")
    if isinstance(details, dict):
        return details
    # Altes Format (vor 2024-08): Felder direkt am Status.
    return {
        "id": status.get("user"),
        "username": status.get("username"),
        "displayName": status.get("username"),
        "profilePicture": status.get("profilePicture"),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def trip_of(status: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Status in ein flaches Dict für das Dashboard wandeln (None = nicht aktiv)."""
    dep = departure(status)
    arr = arrival(status)
    if dep is None or arr is None or arr <= dep:
        return None
    if not (dep - GRACE <= now <= arr + GRACE):
        return None

    user = _user_of(status)
    checkin = checkin_of(status) or {}
    origin = origin_of(status) or {}
    dest = destination_of(status) or {}

    total = (arr - dep).total_seconds()
    progress = max(0.0, min(100.0, (now - dep).total_seconds() / total * 100))

    return {
        "user_id": user.get("id"),
        "name": first(user, "displayName", "username", default="?"),
        "username": user.get("username"),
        "avatar": user.get("profilePicture"),
        "profile_url": f"https://traewelling.de/@{user['username']}"
        if user.get("username")
        else None,
        "line": first(checkin, "lineName", "number"),
        "category": checkin.get("category"),
        "origin": origin.get("name"),
        "destination": dest.get("name"),
        "departure": _iso(dep),
        "arrival": _iso(arr),
        "origin_platform": first(origin, "departurePlatformReal", "departurePlatformPlanned", "platform"),
        "destination_platform": first(dest, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"),
        "departure_planned": first(origin, "departurePlanned", "departure"),
        "arrival_planned": first(dest, "arrivalPlanned", "arrival"),
        "delay_arrival": delay_minutes(arrival(status, real=False), arr),
        "progress": round(progress, 1),
        "minutes_left": max(0, int((arr - now).total_seconds() // 60)),
        "distance_km": meters_to_km(checkin.get("distance")),
        "body": status.get("body"),
        "status_id": status.get("id"),
        "likes": status.get("likes") if isinstance(status.get("likes"), int) else None,
        "liked": bool(status.get("liked")),
        "likable": status.get("isLikable", True) is not False,
        "url": f"https://traewelling.de/status/{status['id']}" if status.get("id") else None,
    }


def active_friend_trips(
    statuses: list[dict[str, Any]] | None, own_user: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Laufende Fahrten aller gefolgten Accounts, eine pro Person, nach Ankunft sortiert."""
    if not isinstance(statuses, list):
        return []
    own = own_user or {}
    own_ids = {str(v) for v in (own.get("id"), own.get("uuid")) if v is not None}
    own_name = own.get("username")

    now = dt_util.utcnow()
    trips: dict[str, dict[str, Any]] = {}
    for status in statuses:
        if not isinstance(status, dict):
            continue
        user = _user_of(status)
        if str(user.get("id")) in own_ids or (own_name and user.get("username") == own_name):
            continue
        trip = trip_of(status, now)
        if trip is None:
            continue
        key = str(user.get("id") or user.get("username"))
        # Pro Person nur die zuletzt begonnene Fahrt behalten.
        if key not in trips or (trip["departure"] or "") > (trips[key]["departure"] or ""):
            trips[key] = trip

    return sorted(trips.values(), key=lambda t: t["arrival"] or "")
