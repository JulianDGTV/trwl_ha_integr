"""Reisekette: aktive Fahrt → Anschluss → Anschluss … mit Umstiegszeiten.

Reine Logik ohne Home-Assistant-Abhängigkeiten (außer dt_util über helpers),
damit sie sich einfach testen lässt.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from .helpers import checkin_of, destination_of, first, origin_of, parse_dt

# Ein Anschluss gehört zur Kette, wenn er höchstens so lange nach der
# (planmäßigen) Ankunft der vorherigen Fahrt startet.
MAX_TRANSFER = timedelta(hours=3)
# Plan-Abfahrt darf minimal vor der Plan-Ankunft liegen (Rundungen, Minutentakt).
EARLY_TOLERANCE = timedelta(minutes=1)
# Mehr als so viele Fahrten zeigt niemand am Stück an.
MAX_LEGS = 8

# Mindest-Umstiegszeit am selben Bahnhof (Minuten).
MIN_SAME_STATION = 2
# Gehtempo für Umstiege zwischen verschiedenen Stationen (Meter pro Minute).
WALK_M_PER_MIN = 70


def _manual(status: dict[str, Any] | None, key: str) -> datetime | None:
    return parse_dt((checkin_of(status) or {}).get(key))


def dep_planned(status: dict[str, Any] | None) -> datetime | None:
    return parse_dt(first(origin_of(status) or {}, "departurePlanned", "departure"))


def arr_planned(status: dict[str, Any] | None) -> datetime | None:
    return parse_dt(first(destination_of(status) or {}, "arrivalPlanned", "arrival"))


def dep_live(status: dict[str, Any] | None) -> datetime | None:
    """Wie Träwelling: manuell > Echtzeit > Plan."""
    return (
        _manual(status, "manualDeparture")
        or parse_dt(first(origin_of(status) or {}, "departureReal"))
        or dep_planned(status)
    )


def arr_live(status: dict[str, Any] | None) -> datetime | None:
    return (
        _manual(status, "manualArrival")
        or parse_dt(first(destination_of(status) or {}, "arrivalReal"))
        or arr_planned(status)
    )


def _has_live(stop: dict[str, Any], key: str) -> bool:
    return bool(stop.get(key))


def station_of(stop: dict[str, Any] | None) -> dict[str, Any]:
    """Station eines Halts: neu `station{…}`, früher direkt am Halt."""
    stop = stop or {}
    station = stop.get("station") if isinstance(stop.get("station"), dict) else {}
    return {
        "id": first(station, "id", default=None),
        "name": first(station, "name", default=None) or stop.get("name"),
        "lat": first(station, "latitude", default=None),
        "lon": first(station, "longitude", default=None),
    }


def _distance_m(a: dict[str, Any], b: dict[str, Any]) -> int | None:
    try:
        lat1, lon1, lat2, lon2 = (float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
    except (TypeError, ValueError, KeyError):
        return None
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(h))))


def _same_station(a: dict[str, Any], b: dict[str, Any], dist: int | None) -> bool:
    if a.get("id") is not None and a.get("id") == b.get("id"):
        return True
    if a.get("name") and a.get("name") == b.get("name"):
        return True
    return dist is not None and dist <= 50


def _minutes(delta: timedelta) -> int:
    return int(math.floor(delta.total_seconds() / 60 + 0.5))


def transfer(prev: dict[str, Any] | None, nxt: dict[str, Any] | None) -> dict[str, Any] | None:
    """Umstieg zwischen zwei Fahrten – Plan- und Echtzeit-Minuten plus Einschätzung."""
    if not isinstance(prev, dict) or not isinstance(nxt, dict):
        return None
    arr_p, dep_p = arr_planned(prev), dep_planned(nxt)
    arr_l, dep_l = arr_live(prev), dep_live(nxt)
    if arr_l is None or dep_l is None:
        return None

    stop_in = destination_of(prev) or {}
    stop_out = origin_of(nxt) or {}
    st_in, st_out = station_of(stop_in), station_of(stop_out)
    dist = _distance_m(st_in, st_out)
    same = _same_station(st_in, st_out, dist)
    walk = None if same or dist is None else max(1, math.ceil(dist / WALK_M_PER_MIN))
    need = MIN_SAME_STATION if same else max(5, walk or 0)

    minutes = _minutes(dep_l - arr_l)
    planned = _minutes(dep_p - arr_p) if arr_p and dep_p else None
    cancelled = bool(stop_in.get("cancelled")) or bool(stop_out.get("cancelled"))

    if cancelled:
        rating = "cancelled"
    elif minutes < 0:
        rating = "missed"
    elif minutes < need:
        rating = "risk"
    elif minutes < need + 3:
        rating = "tight"
    else:
        rating = "ok"

    return {
        "minutes": minutes,
        "minutes_planned": planned,
        "change": (minutes - planned) if planned is not None else None,
        "rating": rating,
        "live": _has_live(stop_in, "arrivalReal") or _has_live(stop_out, "departureReal"),
        "station": st_in.get("name"),
        "to_station": None if same else st_out.get("name"),
        "same_station": same,
        "walk_m": None if same else dist,
        "walk_minutes": walk,
        "arrival_platform": first(stop_in, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"),
        "departure_platform": first(
            stop_out, "departurePlatformReal", "departurePlatformPlanned", "platform"
        ),
    }


def build_chain(
    anchor: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    now: datetime,
    horizon: timedelta,
) -> list[dict[str, Any]]:
    """Anschlusskette ermitteln.

    Mit `anchor` (laufende Fahrt) beginnt die Kette beim ersten Anschluss
    danach. Ohne `anchor` beginnt sie mit der frühesten eigenen Fahrt, die
    innerhalb von `horizon` startet. Danach wird jeweils der früheste
    Check-in gesucht, der nach der Ankunft der vorherigen Fahrt startet
    (höchstens MAX_TRANSFER später) – und so weiter.
    """
    anchor_id = anchor.get("id") if isinstance(anchor, dict) else None
    pool = []
    for status in candidates:
        if not isinstance(status, dict) or status.get("id") is None:
            continue
        if status.get("id") == anchor_id:
            continue
        dep = dep_planned(status) or dep_live(status)
        arr = arr_live(status)
        if dep is None or (arr is not None and arr < now):
            continue
        pool.append((dep, status))
    pool.sort(key=lambda x: (x[0], str(x[1].get("id"))))

    chain: list[dict[str, Any]] = []
    prev = anchor if isinstance(anchor, dict) else None
    if prev is None:
        for dep, status in pool:
            live = dep_live(status) or dep
            if live >= now - timedelta(minutes=1) and min(dep, live) <= now + horizon:
                prev = status
                chain.append(status)
                break
        if prev is None:
            return []

    used = {id(x) for x in chain}
    while len(chain) < MAX_LEGS:
        ref = arr_planned(prev) or arr_live(prev)
        if ref is None:
            break
        nxt = None
        for dep, status in pool:
            if id(status) in used:
                continue
            if ref - EARLY_TOLERANCE <= dep <= ref + MAX_TRANSFER:
                nxt = status
                break
        if nxt is None:
            break
        chain.append(nxt)
        used.add(id(nxt))
        prev = nxt
    return chain
