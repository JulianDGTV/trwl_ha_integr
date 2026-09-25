"""Binärsensor: Bin ich gerade unterwegs?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TraewellingConfigEntry
from .entity import TraewellingEntity

DESCRIPTION = BinarySensorEntityDescription(
    key="travelling",
    name="Unterwegs",
    icon="mdi:train-car",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TraewellingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TraewellingTravellingSensor(entry.runtime_data, DESCRIPTION)])


class TraewellingTravellingSensor(TraewellingEntity, BinarySensorEntity):
    """An, solange ein aktiver Check-in existiert."""

    @property
    def is_on(self) -> bool:
        return isinstance((self.coordinator.data or {}).get("active"), dict)

    @property
    def icon(self) -> str:
        return "mdi:train-car" if self.is_on else "mdi:home"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .sensor import _journey_attrs  # lokaler Import: vermeidet Zyklus

        return _journey_attrs(self.coordinator.data or {})
