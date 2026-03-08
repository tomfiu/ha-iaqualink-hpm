"""Diagnostics support for iAqualink HPM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import AqualinkDataUpdateCoordinator

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
}


def _to_serializable(value: Any) -> Any:
    """Convert nested library objects into JSON-serializable structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Mapping):
        return {str(key): _to_serializable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_serializable(item) for item in value]

    if hasattr(value, "__dict__"):
        return _to_serializable(vars(value))

    return repr(value)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: AqualinkDataUpdateCoordinator = config_entry.runtime_data

    return {
        "config_entry": async_redact_data(dict(config_entry.as_dict()), TO_REDACT),
        "selected_systems": [
            {
                "serial_number": system.serial_number,
                "name": system.name,
                "model": system.model,
                "type": system.type,
                "version": system.version,
                "device_count": len(system.devices),
            }
            for system in coordinator.systems
        ],
        "all_account_systems": _to_serializable(
            getattr(coordinator, "all_account_systems_snapshot", None)
        ),
        "last_coordinator_data": _to_serializable(coordinator.data) if coordinator.data else None,
    }
