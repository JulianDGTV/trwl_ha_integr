"""Aktive Fahrten der Leute, denen du folgst ("Freunde").

Quelle ist GET /api/v1/dashboard: die neuesten Status von dir und allen
Accounts, denen du folgst (inkl. privater Profile, die dich zugelassen haben).
Daraus werden alle Status herausgefiltert, deren Fahrt gerade läuft – oder
bald startet (Träwelling liefert im Dashboard Fahrten bis ca. 20 min vor
Abfahrt; weiter voraus gibt es für fremde Check-ins keinen Endpunkt).
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
    is_own,
    meters_to_km,
    origin_of,
    user_of,
)

# Kleiner Puffer, damit eine Fahrt nicht in der Sekunde der Abfahrt
# bzw. Ankunft zwischen "aktiv" und "nicht aktiv" hin- und herspringt.
GRACE = timedelta(minutes=2)
# Bevorstehende Fahrten von Freunden so weit voraus zeigen (wie bei den eigenen).
UPCOMING_HORIZON = timedelta(minutes=60)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def trip_of(status: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Status in ein flaches Dict für das Dashboard wandeln.

    None = weder aktiv noch bald. `upcoming` = startet innerhalb der nächsten
    Stunde.
    """
    dep = departure(status)
    arr = arrival(status)
    if dep is None or arr is None or arr <= dep:
        return None
    upcoming = now < dep - GRACE
    if upcoming and dep > now + UPCOMING_HORIZON:
        return None
    if not upcoming and now > arr + GRACE:
        return None

    user = user_of(status)
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
        "origin_platform": first(
            origin, "departurePlatformReal", "departurePlatformPlanned", "platform"
        ),
        "destination_platform": first(
            dest, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"
        ),
        "departure_planned": first(origin, "departurePlanned", "departure"),
        "arrival_planned": first(dest, "arrivalPlanned", "arrival"),
        "delay_arrival": delay_minutes(arrival(status, real=False), arr),
        "progress": round(progress, 1),
        "upcoming": upcoming,
        "minutes_until": max(0, int((dep - now).total_seconds() // 60)),
        "minutes_left": max(0, int((arr - now).total_seconds() // 60)),
        "distance_km": meters_to_km(checkin.get("distance")),
        "body": status.get("body"),
        "status_id": status.get("id"),
        "likes": status.get("likes") if isinstance(status.get("likes"), int) else None,
        "liked": bool(status.get("liked")),
        "likable": status.get("isLikable", True) is not False,
        "url": f"https://traewelling.de/status/{status['id']}"
        if status.get("id")
        else None,
    }


def active_friend_trips(
    statuses: list[dict[str, Any]] | None, own_user: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Fahrten aller gefolgten Accounts, eine pro Person.

    Laufende Fahrten zuerst (nach Ankunft), dann bald startende (nach
    Abfahrt). Wer gerade fährt und schon den Anschluss eingecheckt hat,
    bekommt ihn als `next` dazu.
    """
    if not isinstance(statuses, list):
        return []
    now = dt_util.utcnow()
    trips: dict[str, dict[str, Any]] = {}
    soon: dict[str, dict[str, Any]] = {}
    for status in statuses:
        if not isinstance(status, dict):
            continue
        if is_own(status, own_user):
            continue
        user = user_of(status)
        trip = trip_of(status, now)
        if trip is None:
            continue
        key = str(user.get("id") or user.get("username"))
        if trip["upcoming"]:
            # Pro Person die nächste bevorstehende Fahrt.
            if key not in soon or _dt(trip["departure"]) < _dt(soon[key]["departure"]):
                soon[key] = trip
        # Pro Person nur die zuletzt begonnene Fahrt behalten.
        elif key not in trips or _dt(trip["departure"]) > _dt(trips[key]["departure"]):
            trips[key] = trip

    for key, nxt in soon.items():
        if key in trips:
            trips[key]["next"] = {
                "line": nxt["line"],
                "category": nxt["category"],
                "origin": nxt["origin"],
                "destination": nxt["destination"],
                "origin_platform": nxt["origin_platform"],
                "departure": nxt["departure"],
                "departure_planned": nxt["departure_planned"],
                "minutes_until": nxt["minutes_until"],
            }

    running = sorted(trips.values(), key=lambda t: _dt(t["arrival"]))
    upcoming = sorted(
        (t for k, t in soon.items() if k not in trips),
        key=lambda t: _dt(t["departure"]),
    )
    return [*running, *upcoming]


def _dt(value: str | None) -> datetime:
    """ISO-String → datetime zum Sortieren (Zeitzonen-sicher)."""
    parsed = dt_util.parse_datetime(value) if value else None
    return parsed or datetime.min.replace(tzinfo=dt_util.UTC)
