"""Konstanten für die Träwelling-Integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "traewelling"

CONF_BASE_URL = "base_url"
CONF_ACTIVE_INTERVAL = "active_interval"
CONF_STATS_INTERVAL = "stats_interval"
CONF_STATS_FROM = "stats_from"
CONF_LOOKAHEAD = "lookahead"

DEFAULT_BASE_URL = "https://traewelling.de"

# Aktive Fahrt wird häufig gepollt, Statistiken selten (serverseitig 1-6h gecacht).
DEFAULT_ACTIVE_INTERVAL = 60  # Sekunden
DEFAULT_STATS_INTERVAL = 30  # Minuten

# Ein geplanter Check-in gilt so viele Minuten vor Abfahrt als "bevorstehend".
# 0 schaltet die Vorschau ab.
DEFAULT_LOOKAHEAD = 60  # Minuten

# Träwelling ging 2019 online – das reicht als "seit Anbeginn" für die Statistik.
DEFAULT_STATS_FROM = "2019-01-01"

MIN_ACTIVE_INTERVAL = timedelta(seconds=30)

ATTRIBUTION = "Daten von traewelling.de"

# Zustände des Sensors "Fahrtstatus"
STATE_TRAVELLING = "unterwegs"
STATE_UPCOMING = "bevorstehend"
STATE_IDLE = "keine"
