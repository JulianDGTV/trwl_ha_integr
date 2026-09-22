"""Basisklasse für alle Träwelling-Entitäten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import TraewellingCoordinator


class TraewellingEntity(CoordinatorEntity[TraewellingCoordinator]):
    """Gemeinsames Gerät und Namensschema."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self, coordinator: TraewellingCoordinator, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Träwelling",
            name=coordinator.entry.title,
            configuration_url="https://traewelling.de/dashboard",
        )
