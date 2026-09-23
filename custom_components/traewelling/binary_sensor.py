"""Binärsensor: Bin ich gerade unterwegs?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TraewellingCoordinator
from .entity import TraewellingEntity

DESCRIPTION = BinarySensorEntityDescription(
    key="travelling",
    name="Unterwegs",
    icon="mdi:train-car",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TraewellingCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TraewellingTravellingSensor(coordinator, DESCRIPTION)])


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
