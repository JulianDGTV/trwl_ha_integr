"""Konstanten für die Träwelling-Integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "traewelling"

CONF_BASE_URL = "base_url"
CONF_ACTIVE_INTERVAL = "active_interval"
CONF_STATS_INTERVAL = "stats_interval"
CONF_STATS_FROM = "stats_from"

DEFAULT_BASE_URL = "https://traewelling.de"

# Aktive Fahrt wird häufig gepollt, Statistiken selten (serverseitig 1-6h gecacht).
DEFAULT_ACTIVE_INTERVAL = 60  # Sekunden
DEFAULT_STATS_INTERVAL = 60  # Minuten (Träwelling cacht die Statistik ohnehin ~1 h)

# Träwelling ging 2019 online – das reicht als "seit Anbeginn" für die Statistik.
DEFAULT_STATS_FROM = "2019-01-01"

MIN_ACTIVE_INTERVAL = timedelta(seconds=30)

ATTRIBUTION = "Daten von traewelling.de"
