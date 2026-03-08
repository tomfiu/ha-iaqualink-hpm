"""Support for iAqualink climate entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IaqualinkHpmConfigEntry
from .entity import AqualinkEntity
from .local_api import AqualinkHeatPump, AqualinkThermostat

OPERATION_TO_HVAC: dict[str, HVACMode] = {
    "off": HVACMode.OFF,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.HEAT_COOL,
}

HVAC_TO_OPERATION: dict[HVACMode, str] = {value: key for key, value in OPERATION_TO_HVAC.items()}
_LOGGER = logging.getLogger(__name__)


def _resolve_callable(device: Any, *method_names: str) -> Any:
    """Return the first supported callable method from a device."""
    for method_name in method_names:
        method = getattr(device, method_name, None)
        if callable(method):
            return method
    return None


def _supports_heatpump_semantics(device: Any) -> bool:
    return (
        hasattr(device, "operation_mode")
        or hasattr(device, "can_heat")
        or hasattr(device, "can_cool")
        or callable(getattr(device, "set_operation_mode", None))
    )


def _supports_thermostat_semantics(device: Any) -> bool:
    return callable(getattr(device, "set_temperature", None))


def _is_fahrenheit(device: Any) -> bool:
    return str(getattr(device, "temperature_unit", "C")).upper().startswith("F")


def _ha_temperature_unit(device: Any) -> str:
    if _is_fahrenheit(device):
        return UnitOfTemperature.FAHRENHEIT
    return UnitOfTemperature.CELSIUS


def _default_temp_bounds(device: Any) -> tuple[int, int]:
    if _is_fahrenheit(device):
        return (41, 104)
    return (5, 40)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: IaqualinkHpmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up iAqualink climate from config entry."""
    coordinator = config_entry.runtime_data

    entities: list[ClimateEntity] = []
    for system in coordinator.systems:
        for device in system.devices:
            device_type = device.__class__.__name__
            if isinstance(device, AqualinkThermostat):
                entities.append(AqualinkThermostatEntity(coordinator, system, device))
            elif isinstance(device, AqualinkHeatPump) or _supports_heatpump_semantics(device):
                entities.append(AqualinkHeatPumpEntity(coordinator, system, device))
            elif _supports_thermostat_semantics(device):
                entities.append(AqualinkThermostatEntity(coordinator, system, device))
            else:
                _LOGGER.debug(
                    "Skipping unsupported climate device type=%s key=%s",
                    device_type,
                    getattr(device, "key", None),
                )

    if not entities:
        _LOGGER.warning(
            "No climate entities discovered for tracked systems=%s",
            [getattr(system, "serial_number", None) for system in coordinator.systems],
        )
    _LOGGER.debug("Adding %s climate entities", len(entities))
    async_add_entities(entities)


class AqualinkThermostatEntity(AqualinkEntity, ClimateEntity):
    """Representation of an iAqualink thermostat."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_name = "Thermostat"

    def __init__(self, coordinator, system, device: Any) -> None:
        super().__init__(coordinator, system, device)
        self._attr_target_temperature_step = 1
        default_min, default_max = _default_temp_bounds(device)
        self._attr_min_temp = getattr(device, "min_temperature", default_min)
        self._attr_max_temp = getattr(device, "max_temperature", default_max)

    @property
    def temperature_unit(self) -> str:
        return _ha_temperature_unit(self._device)

    @property
    def current_temperature(self) -> float | None:
        return getattr(self._device, "temperature", None)

    @property
    def target_temperature(self) -> float | None:
        return getattr(self._device, "target_temperature", None)

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [HVACMode.HEAT]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs[ATTR_TEMPERATURE]
        _LOGGER.debug(
            "Thermostat set_temperature requested device=%s value=%s",
            getattr(self._device, "key", None),
            temperature,
        )
        set_temperature = _resolve_callable(
            self._device, "set_temperature", "async_set_temperature"
        )
        if set_temperature is None:
            return
        await self.coordinator.async_call_api(set_temperature, temperature)
        await self.coordinator.async_request_refresh()


class AqualinkHeatPumpEntity(AqualinkEntity, ClimateEntity):
    """Representation of an iAqualink heat pump (HPM systems)."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_name = "Heat Pump"

    def __init__(self, coordinator, system, device: Any) -> None:
        super().__init__(coordinator, system, device)
        self._attr_target_temperature_step = 1
        default_min, default_max = _default_temp_bounds(device)
        self._attr_min_temp = getattr(device, "min_temperature", default_min)
        self._attr_max_temp = getattr(device, "max_temperature", default_max)

    @property
    def temperature_unit(self) -> str:
        return _ha_temperature_unit(self._device)

    @property
    def current_temperature(self) -> float | None:
        return getattr(self._device, "temperature", None)

    @property
    def target_temperature(self) -> float | None:
        return getattr(self._device, "target_temperature", None)

    @property
    def hvac_mode(self) -> HVACMode:
        return OPERATION_TO_HVAC.get(getattr(self._device, "operation_mode", "off"), HVACMode.OFF)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes: list[HVACMode] = [HVACMode.OFF]
        if getattr(self._device, "can_heat", True):
            modes.append(HVACMode.HEAT)
        if getattr(self._device, "can_cool", True):
            modes.append(HVACMode.COOL)
        if getattr(self._device, "can_heat", True) and getattr(self._device, "can_cool", True):
            modes.append(HVACMode.HEAT_COOL)
        return modes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mode = HVAC_TO_OPERATION.get(hvac_mode)
        if mode is None:
            return
        _LOGGER.debug(
            "Heat pump set_hvac_mode requested device=%s hvac=%s api_mode=%s",
            getattr(self._device, "key", None),
            hvac_mode,
            mode,
        )
        set_operation_mode = _resolve_callable(
            self._device, "set_operation_mode", "async_set_operation_mode"
        )
        if set_operation_mode is None:
            return
        await self.coordinator.async_call_api(set_operation_mode, mode)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs[ATTR_TEMPERATURE]
        _LOGGER.debug(
            "Heat pump set_temperature requested device=%s value=%s",
            getattr(self._device, "key", None),
            temperature,
        )
        set_temperature = _resolve_callable(
            self._device, "set_temperature", "async_set_temperature"
        )
        if set_temperature is None:
            return
        await self.coordinator.async_call_api(set_temperature, temperature)
        await self.coordinator.async_request_refresh()
