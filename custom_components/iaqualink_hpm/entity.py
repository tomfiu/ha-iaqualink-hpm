"""Entity base for iAqualink HPM."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqualinkDataUpdateCoordinator


class AqualinkEntity(CoordinatorEntity[AqualinkDataUpdateCoordinator]):
    """Representation of a iAqualink entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AqualinkDataUpdateCoordinator,
        system: Any,
        device: Any,
    ) -> None:
        """Initialize the iAqualink entity."""
        super().__init__(coordinator)
        self._device = device
        self._system = system
        device_key = str(getattr(device, "key", "unknown")).lower()
        self._attr_unique_id = f"{system.serial_number}_{device_key}"
        self._attr_device_info = {
            "identifiers": {("iaqualink_hpm", system.serial_number)},
            "manufacturer": "Zodiac",
            "model": getattr(system, "model", None),
            "name": getattr(system, "name", system.serial_number),
            "sw_version": getattr(system, "version", None),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "serial_number": self._system.serial_number,
            "system_type": self._system.type,
            "device_key": getattr(self._device, "key", None),
        }
