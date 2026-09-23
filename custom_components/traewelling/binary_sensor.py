"""Binärsensoren: Bin ich unterwegs – oder gleich?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATE_IDLE, STATE_TRAVELLING
from .coordinator import TraewellingCoordinator
from .entity import TraewellingEntity

TRAVELLING = BinarySensorEntityDescription(
    key="travelling",
    name="Unterwegs",
    icon="mdi:train-car",
)

CHECKED_IN = BinarySensorEntityDescription(
    key="checked_in",
    name="Check-in aktiv",
    icon="mdi:ticket-confirmation",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TraewellingCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TraewellingTravellingSensor(coordinator, TRAVELLING),
            TraewellingCheckedInSensor(coordinator, CHECKED_IN),
        ]
    )


class _TraewellingBinary(TraewellingEntity, BinarySensorEntity):
    """Gemeinsame Attribute für beide Binärsensoren."""

    @property
    def _state(self) -> str:
        return (self.coordinator.data or {}).get("trip_state") or STATE_IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .sensor import _journey_attrs  # lokaler Import: vermeidet Zyklus

        return _journey_attrs(self.coordinator.data or {})


class TraewellingTravellingSensor(_TraewellingBinary):
    """An, solange eine Fahrt tatsächlich läuft."""

    @property
    def is_on(self) -> bool:
        return self._state == STATE_TRAVELLING

    @property
    def icon(self) -> str:
        return "mdi:train-car" if self.is_on else "mdi:home"


class TraewellingCheckedInSensor(_TraewellingBinary):
    """An, solange eine Fahrt läuft ODER in Kürze startet.

    Das ist der Sensor für die Lovelace-Karte: er geht bereits an, sobald ein
    Check-in für die nächste Stunde existiert.
    """

    @property
    def is_on(self) -> bool:
        return self._state != STATE_IDLE

    @property
    def icon(self) -> str:
        if self._state == STATE_TRAVELLING:
            return "mdi:train-car"
        return "mdi:ticket-confirmation" if self.is_on else "mdi:ticket-outline"
