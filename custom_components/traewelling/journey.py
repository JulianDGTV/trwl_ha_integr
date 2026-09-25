"""Reisekette: aktive Fahrt → Anschluss → Anschluss … mit Umstiegszeiten.

Reine Logik ohne Home-Assistant-Abhängigkeiten (außer dt_util über helpers),
damit sie sich einfach testen lässt.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from .helpers import checkin_of, destination_of, distance_m, first, origin_of, parse_dt

# Ein Anschluss gehört zur Kette, wenn er höchstens so lange nach der
# (planmäßigen) Ankunft der vorherigen Fahrt startet.
MAX_TRANSFER = timedelta(hours=3)
# Plan-Abfahrt darf minimal vor der Plan-Ankunft liegen (Rundungen, Minutentakt).
EARLY_TOLERANCE = timedelta(minutes=1)
# Findet sich nichts Passendes, werden auch „unlogische“ Check-ins, die laut
# Fahrplan bis zu so lange vor der Ankunft abfahren, in die Kette genommen –
# mit Warnung, statt sie zu verschweigen.
CONFLICT_WINDOW = timedelta(minutes=60)
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
    """Ankunft: manuell > Echtzeit > Schätzung (Abfahrtsverspätung) > Plan."""
    return (
        _manual(status, "manualArrival")
        or parse_dt(first(destination_of(status) or {}, "arrivalReal"))
        or _arr_estimate(status)
        or arr_planned(status)
    )


def _arr_estimate(status: dict[str, Any] | None) -> datetime | None:
    """Fährt eine Fahrt verspätet ab, hat aber (noch) keine Ankunfts-Echtzeit,
    kommt sie voraussichtlich mit derselben Verspätung an."""
    if not (
        _manual(status, "manualDeparture")
        or (origin_of(status) or {}).get("departureReal")
    ):
        return None
    dep_p, arr_p = dep_planned(status), arr_planned(status)
    dep_l = _manual(status, "manualDeparture") or parse_dt(
        first(origin_of(status) or {}, "departureReal")
    )
    if dep_p is None or arr_p is None or dep_l is None or dep_l <= dep_p:
        return None
    return arr_p + (dep_l - dep_p)


def arr_is_live(status: dict[str, Any] | None) -> bool:
    return bool(
        _manual(status, "manualArrival")
        or (destination_of(status) or {}).get("arrivalReal")
    )


def dep_is_live(status: dict[str, Any] | None) -> bool:
    return bool(
        _manual(status, "manualDeparture")
        or (origin_of(status) or {}).get("departureReal")
    )


def dep_source(status: dict[str, Any] | None) -> str:
    """Woher die Abfahrtszeit stammt: manual, board (Live-Abfahrtstafel), live, plan."""
    if _manual(status, "manualDeparture"):
        return "manual"
    if (origin_of(status) or {}).get("departureReal"):
        return "board" if (status or {}).get("_board") else "live"
    return "plan"


def arr_source(status: dict[str, Any] | None) -> str:
    if _manual(status, "manualArrival"):
        return "manual"
    if (destination_of(status) or {}).get("arrivalReal"):
        return "live"
    return "estimate" if _arr_estimate(status) else "plan"


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
        coords = (float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
    except (TypeError, ValueError, KeyError):
        return None
    return round(distance_m(*coords))


def _same_station(a: dict[str, Any], b: dict[str, Any], dist: int | None) -> bool:
    if a.get("id") is not None and a.get("id") == b.get("id"):
        return True
    if a.get("name") and a.get("name") == b.get("name"):
        return True
    return dist is not None and dist <= 50


def _minutes(delta: timedelta) -> int:
    return int(math.floor(delta.total_seconds() / 60 + 0.5))


def transfer(
    prev: dict[str, Any] | None, nxt: dict[str, Any] | None
) -> dict[str, Any] | None:
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
    arr_delay = _minutes(arr_l - arr_p) if arr_p else 0
    dep_delay = _minutes(dep_l - dep_p) if dep_p else 0
    src_in, src_out = arr_source(prev), dep_source(nxt)
    where = st_in.get("name") or "Umstieg"

    warning = None
    if cancelled:
        rating = "cancelled"
        warning = (
            "Anschluss fällt aus" if stop_out.get("cancelled") else "Ankunft fällt aus"
        )
    elif planned is not None and planned < 0:
        # Schon laut Fahrplan unmöglich → Check-in prüfen.
        rating = "conflict"
        warning = (
            f"Abfahrt laut Fahrplan {-planned} min vor der Ankunft – Check-in prüfen"
        )
    elif minutes < need and src_in != "plan" and src_out == "plan" and arr_delay > 0:
        # Ankunft hat Echtzeit (verspätet), der Anschluss nicht – er kann
        # genauso verspätet sein. Nicht als „verpasst“ werten.
        rating = "unknown"
        warning = (
            f"Ankunft {'voraussichtlich ' if src_in == 'estimate' else ''}+{arr_delay} min, "
            "für den Anschluss gibt es noch keine Echtzeit – er ist evtl. auch verspätet"
        )
    elif minutes < 0:
        rating = "missed"
        warning = f"Nach Echtzeit {-minutes} min zu spät für den Anschluss in {where}"
    elif minutes < need:
        rating = "risk"
        warning = f"Nur {minutes} min zum Umsteigen in {where}" + (
            "" if same else f" (Fußweg ca. {walk} min)" if walk else ""
        )
    elif minutes < need + 3:
        rating = "tight"
    else:
        rating = "ok"

    return {
        "minutes": minutes,
        "minutes_planned": planned,
        "change": (minutes - planned) if planned is not None else None,
        "rating": rating,
        "warning": warning,
        "live": src_in != "plan" or src_out != "plan",
        "arrival_source": src_in,
        "departure_source": src_out,
        "arrival_delay": arr_delay,
        "departure_delay": dep_delay,
        "station": st_in.get("name"),
        "to_station": None if same else st_out.get("name"),
        "same_station": same,
        "walk_m": None if same else dist,
        "walk_minutes": walk,
        "arrival_platform": first(
            stop_in, "arrivalPlatformReal", "arrivalPlatformPlanned", "platform"
        ),
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
        # Obergrenze ab der späteren von Plan- und Echtzeit-Ankunft, damit
        # eine große Verspätung die Kette nicht abreißen lässt.
        late = max(ref, arr_live(prev) or ref)
        # Frühester Check-in, der nach der Ankunft startet. Auch „unlogische“,
        # die laut Fahrplan schon vor der Ankunft abfahren (aber danach
        # ankommen), gehören dazu – sie werden mit Warnung angezeigt.
        nxt = None
        for dep, status in pool:
            if id(status) in used:
                continue
            if not ref - CONFLICT_WINDOW <= dep <= late + MAX_TRANSFER:
                continue
            end = arr_planned(status) or arr_live(status)
            if dep < ref - EARLY_TOLERANCE and (end is None or end <= ref):
                continue
            nxt = status
            break
        if nxt is None:
            break
        chain.append(nxt)
        used.add(id(nxt))
        prev = nxt
    return chain
