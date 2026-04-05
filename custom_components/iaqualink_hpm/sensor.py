"""Sensor entities for iAqualink HPM - temperature, mode, and status metrics."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IaqualinkHpmConfigEntry
from .entity import AqualinkEntity
from .local_api import AqualinkHeatPump, AqualinkThermostat

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: IaqualinkHpmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up iAqualink sensors from config entry."""
    coordinator = config_entry.runtime_data

    entities: list[SensorEntity] = []
    for system in coordinator.systems:
        for device in system.devices:
            if not isinstance(device, (AqualinkHeatPump, AqualinkThermostat)):
                continue
            entities.append(AqualinkTemperatureSensor(coordinator, system, device))
            entities.append(AqualinkTargetTemperatureSensor(coordinator, system, device))
            entities.append(AqualinkStatusSensor(coordinator, system, device))
            if isinstance(device, AqualinkHeatPump):
                entities.append(AqualinkAirTemperatureSensor(coordinator, system, device))
                entities.append(AqualinkModeSensor(coordinator, system, device))
                entities.append(AqualinkPresetSensor(coordinator, system, device))
                # Diagnostic / advanced sensors — disabled by default.
                entities.append(AqualinkFanSpeedSensor(coordinator, system, device))
                entities.append(AqualinkWaterFlowSensor(coordinator, system, device))
                entities.append(AqualinkHeatingActiveSensor(coordinator, system, device))
                entities.append(AqualinkCoolingActiveSensor(coordinator, system, device))
                entities.append(AqualinkLedSensor(coordinator, system, device))
                entities.append(AqualinkReasonCodeSensor(coordinator, system, device))
                entities.append(AqualinkBoardFirmwareSensor(coordinator, system, device))
                entities.append(AqualinkWifiRssiSensor(coordinator, system, device))
                entities.append(AqualinkShadowFetchStatusSensor(coordinator, system, device))

    _LOGGER.debug("Adding %s sensor entities", len(entities))
    async_add_entities(entities)


def _ha_temperature_unit(device: Any) -> str:
    unit = str(getattr(device, "temperature_unit", "C")).upper()
    return UnitOfTemperature.FAHRENHEIT if unit.startswith("F") else UnitOfTemperature.CELSIUS


class _AqualinkSensorBase(AqualinkEntity, SensorEntity):
    """Base class for iAqualink sensor entities."""

    def __init__(self, coordinator: Any, system: Any, device: Any, suffix: str) -> None:
        super().__init__(coordinator, system, device)
        device_key = str(getattr(device, "key", "unknown")).lower()
        self._attr_unique_id = f"{system.serial_number}_{device_key}_{suffix}"


class AqualinkTemperatureSensor(_AqualinkSensorBase):
    """Current water temperature reported by the device."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Temperature"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "temperature")

    @property
    def native_unit_of_measurement(self) -> str:
        return _ha_temperature_unit(self._device)

    @property
    def native_value(self) -> float | None:
        return getattr(self._device, "temperature", None)


class AqualinkTargetTemperatureSensor(_AqualinkSensorBase):
    """Target (set-point) temperature of the device."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Target Temperature"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "target_temperature")

    @property
    def native_unit_of_measurement(self) -> str:
        return _ha_temperature_unit(self._device)

    @property
    def native_value(self) -> float | None:
        return getattr(self._device, "target_temperature", None)


class AqualinkAirTemperatureSensor(_AqualinkSensorBase):
    """Ambient air temperature measured by the heat pump."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Air Temperature"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "air_temperature")

    @property
    def native_unit_of_measurement(self) -> str:
        return _ha_temperature_unit(self._device)

    @property
    def native_value(self) -> float | None:
        return getattr(self._device, "air_temperature", None)


_STATUS_MAP = {
    "0": "off",
    "1": "standby",
    "2": "heating",
}


class AqualinkStatusSensor(_AqualinkSensorBase):
    """Operational/connection status of the device."""

    _attr_name = "Status"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "status")

    @property
    def native_value(self) -> str | None:
        raw = getattr(self._device, "status", None)
        if raw is None:
            return None
        return _STATUS_MAP.get(str(raw), str(raw))


class AqualinkModeSensor(_AqualinkSensorBase):
    """Current operation mode of the heat pump (off/heat/cool/auto)."""

    _attr_name = "Mode"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "mode")

    @property
    def native_value(self) -> str | None:
        return getattr(self._device, "operation_mode", None)


class AqualinkPresetSensor(_AqualinkSensorBase):
    """Current preset of the heat pump (normal/boost/quiet)."""

    _attr_name = "Preset"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "preset")

    @property
    def native_value(self) -> str | None:
        return getattr(self._device, "preset_mode", None)


# ---------------------------------------------------------------------------
# Diagnostic / advanced sensors — disabled by default.
# ---------------------------------------------------------------------------

class AqualinkFanSpeedSensor(_AqualinkSensorBase):
    """Fan speed level reported by the heat pump."""

    _attr_name = "Fan Speed"
    _attr_entity_registry_enabled_default = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:fan"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "fan_speed")

    @property
    def native_value(self) -> int | None:
        return getattr(self._device, "fan_speed", None)


class AqualinkWaterFlowSensor(_AqualinkSensorBase):
    """Water flow status (wf flag from the heat pump equipment block)."""

    _attr_name = "Water Flow"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:water-pump"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "water_flow")

    @property
    def native_value(self) -> str | None:
        value = getattr(self._device, "water_flow", None)
        if value is None:
            return None
        return "on" if value else "off"


class AqualinkHeatingActiveSensor(_AqualinkSensorBase):
    """Whether the heat pump is actively heating (hp flag)."""

    _attr_name = "Heating Active"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:heat-wave"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "heating_active")

    @property
    def native_value(self) -> str | None:
        value = getattr(self._device, "heating_active", None)
        if value is None:
            return None
        return "on" if value else "off"


class AqualinkCoolingActiveSensor(_AqualinkSensorBase):
    """Whether the heat pump is actively cooling (cl flag)."""

    _attr_name = "Cooling Active"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:snowflake"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "cooling_active")

    @property
    def native_value(self) -> str | None:
        value = getattr(self._device, "cooling_active", None)
        if value is None:
            return None
        return "on" if value else "off"


class AqualinkLedSensor(_AqualinkSensorBase):
    """LED indicator status of the heat pump."""

    _attr_name = "LED"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:led-on"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "led")

    @property
    def native_value(self) -> str | None:
        value = getattr(self._device, "led_on", None)
        if value is None:
            return None
        return "on" if value else "off"


class AqualinkReasonCodeSensor(_AqualinkSensorBase):
    """Reason / error code from the heat pump equipment block."""

    _attr_name = "Reason Code"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "reason_code")

    @property
    def native_value(self) -> int | None:
        return getattr(self._device, "reason_code", None)


class AqualinkBoardFirmwareSensor(_AqualinkSensorBase):
    """Firmware version of the heat pump main board."""

    _attr_name = "Board Firmware"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "board_firmware")

    @property
    def native_value(self) -> str | None:
        return getattr(self._device, "board_firmware", None)


class AqualinkWifiRssiSensor(_AqualinkSensorBase):
    """WiFi signal strength of the heat pump module."""

    _attr_name = "WiFi Signal"
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "wifi_rssi")

    @property
    def native_value(self) -> int | None:
        return getattr(self._device, "wifi_rssi", None)


class AqualinkShadowFetchStatusSensor(_AqualinkSensorBase):
    """HTTP status code of the last shadow fetch (200, 429, etc.)."""

    _attr_name = "Shadow Fetch Status"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:cloud-sync"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: Any, system: Any, device: Any) -> None:
        super().__init__(coordinator, system, device, "shadow_fetch_status")

    @property
    def native_value(self) -> int | None:
        return getattr(self._device, "last_shadow_status", None)
