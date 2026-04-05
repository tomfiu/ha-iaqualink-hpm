"""The iAqualink HPM integration."""

from __future__ import annotations

from datetime import timedelta
import inspect
import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.ssl import SSL_ALPN_HTTP11_HTTP2

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .local_api import AqualinkClient

SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
_LOGGER = logging.getLogger(__name__)

IaqualinkHpmConfigEntry = ConfigEntry
_SKIP_CLOSE_ATTR = "_iaqualink_hpm_skip_close"
_REDACT_KEYS = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "key",
}

def _safe_username(username: str) -> str:
    """Return a masked username for logs."""
    username = username.strip()
    if "@" in username:
        name, domain = username.split("@", 1)
        return f"{name[:2]}***@{domain}"
    return f"{username[:2]}***"


def _sanitize(value: Any) -> Any:
    """Redact secrets from nested structures for debug logging."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if key_s.lower() in _REDACT_KEYS:
                sanitized[key_s] = "***REDACTED***"
            else:
                sanitized[key_s] = _sanitize(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    return value


def _describe_systems(systems: list[Any]) -> list[dict[str, Any]]:
    """Compact system summary for logs."""
    return [
        {
            "serial_number": getattr(system, "serial_number", None),
            "name": getattr(system, "name", None),
            "type": getattr(system, "type", None),
            "model": getattr(system, "model", None),
            "device_count": len(getattr(system, "devices", [])),
        }
        for system in systems
    ]


def _snapshot_system_full(system: Any) -> dict[str, Any]:
    """Detailed, diagnostics-oriented system snapshot."""
    data = {
        "serial_number": getattr(system, "serial_number", None),
        "name": getattr(system, "name", None),
        "type": getattr(system, "type", None),
        "model": getattr(system, "model", None),
        "version": getattr(system, "version", None),
        "class_name": system.__class__.__name__,
    }
    try:
        for key, value in vars(system).items():
            if key in {"devices", "client"}:
                continue
            data[key] = _sanitize(value)
    except TypeError:
        # Some classes may not expose __dict__.
        pass
    data["devices"] = [_snapshot_device(device) for device in getattr(system, "devices", [])]
    return data


def _extract_raw_systems(payload: Any) -> list[dict[str, Any]]:
    """Extract raw system records from unknown iaqualink payload shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("systems", "devices", "response", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _is_hpm_system(system: Any) -> bool:
    """Best-effort check if system represents a heat pump installation."""
    system_type = str(getattr(system, "type", "") or "").strip().lower()
    if system_type in {"hpm", "heatpump", "heat_pump", "hp"}:
        return True

    model = str(getattr(system, "model", "") or "").lower()
    name = str(getattr(system, "name", "") or "").lower()
    if "z400" in model or "heat pump" in name:
        return True

    for device in getattr(system, "devices", []):
        device_type = device.__class__.__name__.lower()
        if (
            "heatpump" in device_type
            or hasattr(device, "operation_mode")
            or callable(getattr(device, "set_operation_mode", None))
        ):
            return True
    return False


async def _async_await_if_needed(value: Any) -> Any:
    """Await a value only when it is awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


async def _async_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call an iaqualink method that may be sync or async."""
    _LOGGER.debug(
        "Calling iaqualink method '%s' with args=%s kwargs=%s",
        getattr(func, "__name__", repr(func)),
        _sanitize(args),
        _sanitize(kwargs),
    )
    return await _async_await_if_needed(func(*args, **kwargs))


def _create_aqualink_client(
    hass: HomeAssistant,
    username: str,
    password: str,
    serial: str | None = None,
) -> Any:
    """Create local Aqualink client with Home Assistant networking."""
    httpx_client = get_async_client(hass, alpn_protocols=SSL_ALPN_HTTP11_HTTP2)
    _LOGGER.debug(
        "Creating local iaqualink client class=%s serial=%s",
        AqualinkClient.__name__,
        serial,
    )
    client = AqualinkClient(
        username=username,
        password=password,
        serial_number=serial,
        httpx_client=httpx_client,
    )
    setattr(client, _SKIP_CLOSE_ATTR, True)
    return client


async def _async_login_if_supported(client: Any) -> None:
    """Login client if the installed iaqualink version requires it."""
    login = getattr(client, "login", None)
    if callable(login):
        await _async_call(login)
        _LOGGER.debug("iaqualink login completed")


async def _async_close_if_supported(client: Any) -> None:
    """Close client if supported."""
    if getattr(client, _SKIP_CLOSE_ATTR, False):
        _LOGGER.debug("Skipping client close (managed by Home Assistant httpx client)")
        return
    close = getattr(client, "close", None)
    if callable(close):
        try:
            await _async_call(close)
        except RuntimeError as err:
            # Do not fail config flow/unload if library closes on a dead loop.
            if "event loop is closed" in str(err).lower():
                _LOGGER.debug("Skipping iaqualink close on closed event loop")
                return
            raise


async def _async_get_systems_from_client(client: Any) -> list[Any]:
    """Fetch systems from a logged-in client across iaqualink versions."""
    systems = await _async_call(client.get_systems)
    if isinstance(systems, dict):
        systems_list = list(systems.values())
    else:
        systems_list = list(systems)
    _LOGGER.debug(
        "Received %s systems from iaqualink: %s",
        len(systems_list),
        _sanitize(_describe_systems(systems_list)),
    )
    return systems_list


async def _async_probe_raw_systems_payload(client: Any) -> list[dict[str, Any]]:
    """Try to read raw systems payload directly from iaqualink client internals."""
    send_systems_request = getattr(client, "_send_systems_request", None)
    if not callable(send_systems_request):
        _LOGGER.debug("Raw systems probe unavailable: _send_systems_request not found")
        return []

    payload = await _async_call(send_systems_request)
    records = _extract_raw_systems(payload)
    _LOGGER.debug(
        "Raw systems payload probe count=%s records=%s",
        len(records),
        _sanitize(records),
    )
    return records


def _merge_system_state(existing_system: Any, latest_system: Any) -> None:
    """Merge latest state into existing system/device objects used by entities."""
    try:
        latest_attrs = vars(latest_system)
    except TypeError:
        latest_attrs = {}

    # Preserve existing device object identity to keep entity references valid.
    for key, value in latest_attrs.items():
        if key == "devices":
            continue
        setattr(existing_system, key, value)

    existing_devices = list(getattr(existing_system, "devices", []))
    latest_devices = list(getattr(latest_system, "devices", []))

    def _device_key(device: Any) -> str | None:
        key = getattr(device, "key", None)
        if key is None:
            return None
        return str(key).lower()

    existing_by_key = {
        key: device
        for device in existing_devices
        if (key := _device_key(device)) is not None
    }

    merged_devices: list[Any] = []
    for latest_device in latest_devices:
        latest_key = _device_key(latest_device)
        if latest_key is None:
            merged_devices.append(latest_device)
            continue

        existing_device = existing_by_key.pop(latest_key, None)
        if existing_device is None:
            merged_devices.append(latest_device)
            continue

        try:
            for attr, value in vars(latest_device).items():
                if value is None and getattr(existing_device, attr, None) is not None:
                    continue
                existing_device.__dict__[attr] = value
        except TypeError:
            pass
        merged_devices.append(existing_device)

    # Keep previously known devices that are temporarily missing from payload.
    merged_devices.extend(existing_by_key.values())
    existing_system.devices = merged_devices


def _snapshot_device(device: Any) -> dict[str, Any]:
    """Return a diagnostics-friendly device snapshot."""
    attrs = (
        "key",
        "name",
        "status",
        "temperature",
        "target_temperature",
        "air_temperature",
        "operation_mode",
        "preset_mode",
        "can_heat",
        "can_cool",
        "temperature_unit",
        "min_temperature",
        "max_temperature",
        "fan_speed",
        "water_flow",
        "cooling_active",
        "heating_active",
        "led_on",
        "reason_code",
        "board_firmware",
        "wifi_rssi",
    )
    snapshot = {attr: getattr(device, attr, None) for attr in attrs}
    snapshot["raw"] = dict(getattr(device, "_raw", {}))
    return snapshot


def _snapshot_system(system: Any) -> dict[str, Any]:
    """Return a diagnostics-friendly system snapshot."""
    attrs = ("serial_number", "name", "type", "model", "version")
    snapshot = {attr: getattr(system, attr, None) for attr in attrs}
    snapshot["devices"] = [
        _snapshot_device(device) for device in getattr(system, "devices", [])
    ]
    return snapshot


def _map_runtime_error(ex: Exception) -> Exception:
    """Map iaqualink runtime exceptions to Home Assistant exceptions."""
    err_name = ex.__class__.__name__
    err_text = str(ex).lower()
    if err_name == "AqualinkAuthenticationException":
        return ConfigEntryAuthFailed()
    if err_name == "AqualinkApiConnectionException":
        return UpdateFailed(f"Error communicating with API: {ex}")
    if err_name == "AqualinkServiceException":
        if "401" in err_text or "403" in err_text or "unauthorized" in err_text:
            return ConfigEntryAuthFailed()
        return UpdateFailed(f"Service error from API: {ex}")
    return UpdateFailed(f"Unexpected iaqualink error: {ex}")


async def async_setup_entry(hass: HomeAssistant, entry: IaqualinkHpmConfigEntry) -> bool:
    """Set up iAqualink HPM from a config entry."""
    username = entry.data[CONF_USERNAME].strip()
    password = entry.data[CONF_PASSWORD]
    _LOGGER.debug("Setting up integration for user=%s", _safe_username(username))

    account_client = _create_aqualink_client(hass, username, password)
    try:
        await _async_login_if_supported(account_client)
        systems = await _async_get_systems_from_client(account_client)
        _LOGGER.debug(
            "Account systems full snapshot count=%s payload=%s",
            len(systems),
            _sanitize([_snapshot_system_full(system) for system in systems]),
        )
    except Exception as ex:  # noqa: BLE001
        try:
            raw_records = await _async_probe_raw_systems_payload(account_client)
            if raw_records:
                _LOGGER.debug(
                    "Account systems raw probe after setup failure count=%s records=%s",
                    len(raw_records),
                    _sanitize(raw_records),
                )
        except Exception as probe_ex:  # noqa: BLE001
            _LOGGER.debug("Raw systems probe failed during setup: %s", probe_ex)
        await _async_close_if_supported(account_client)
        raise _map_runtime_error(ex) from ex

    hpm_systems = [system for system in systems if _is_hpm_system(system)]
    _LOGGER.debug(
        "Filtered HPM systems: total=%s hpm=%s details=%s",
        len(systems),
        len(hpm_systems),
        _sanitize(_describe_systems(hpm_systems)),
    )
    if not hpm_systems:
        await _async_close_if_supported(account_client)
        return False

    scan_seconds = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = AqualinkDataUpdateCoordinator(
        hass, account_client, hpm_systems, systems,
        update_interval=timedelta(seconds=scan_seconds),
    )
    coordinator.async_set_updated_data(
        {
            system.serial_number: _snapshot_system(system)
            for system in hpm_systems
            if getattr(system, "serial_number", None)
        }
    )
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    _LOGGER.debug("Forwarding config entry to platforms=%s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: IaqualinkHpmConfigEntry) -> None:
    """React to options changes by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IaqualinkHpmConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: AqualinkDataUpdateCoordinator = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await coordinator.async_close()
    return unload_ok


class AqualinkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the API."""

    config_entry: IaqualinkHpmConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        account_client: Any,
        systems: list[Any],
        all_account_systems: list[Any] | None = None,
        update_interval: timedelta = SCAN_INTERVAL,
    ) -> None:
        """Initialize."""
        self._account_client = account_client
        self.systems = systems
        self.all_account_systems = all_account_systems or systems
        self.all_account_systems_snapshot = [
            _snapshot_system_full(system) for system in self.all_account_systems
        ]
        self._systems_by_serial: dict[str, Any] = {
            system.serial_number: system
            for system in systems
            if getattr(system, "serial_number", None)
        }
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh systems and mutate existing objects so entities update cleanly."""
        _LOGGER.debug("Starting coordinator refresh for %s tracked systems", len(self._systems_by_serial))
        try:
            latest_systems = await self._fetch_systems_with_relogin()
            latest_by_serial = {
                system.serial_number: system
                for system in latest_systems
                if getattr(system, "serial_number", None)
            }
            for serial, existing_system in self._systems_by_serial.items():
                latest_system = latest_by_serial.get(serial)
                if latest_system is None:
                    _LOGGER.debug("System %s not present in latest payload", serial)
                    continue
                _merge_system_state(existing_system, latest_system)
                if _is_hpm_system(existing_system):
                    _LOGGER.debug(
                        "Refreshed HPM system '%s' (%s), devices=%s",
                        getattr(existing_system, "name", serial),
                        serial,
                        len(getattr(existing_system, "devices", [])),
                    )
            return {
                serial: _snapshot_system(system)
                for serial, system in self._systems_by_serial.items()
            }
        except Exception as ex:  # noqa: BLE001
            # On rate-limiting keep the previous data so entities stay available.
            if "429" in str(ex) or "rate limit" in str(ex).lower():
                _LOGGER.warning(
                    "Zodiac API rate limit hit, retaining previous sensor values until next poll"
                )
                if self.data is not None:
                    return self.data
            _LOGGER.debug("Coordinator refresh failed: type=%s error=%s", ex.__class__.__name__, ex)
            raise _map_runtime_error(ex) from ex

    async def _fetch_systems_with_relogin(self) -> list[Any]:
        """Fetch systems, refreshing tokens once if authentication has expired."""
        try:
            return await _async_get_systems_from_client(self._account_client)
        except Exception as ex:  # noqa: BLE001
            if ex.__class__.__name__ == "AqualinkAuthenticationException":
                refresh = getattr(self._account_client, "refresh_tokens", None)
                if callable(refresh):
                    _LOGGER.debug("Token expired during refresh, refreshing tokens")
                    await _async_call(refresh)
                else:
                    _LOGGER.debug("Token expired during refresh, re-logging in")
                    await _async_login_if_supported(self._account_client)
                return await _async_get_systems_from_client(self._account_client)
            raise

    async def async_call_api(
        self,
        call: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a device API method that may be sync or async."""
        result = await _async_call(call, *args, **kwargs)
        _LOGGER.debug(
            "iaqualink device API call completed method=%s result=%s",
            getattr(call, "__name__", repr(call)),
            _sanitize(result),
        )
        return result

    async def async_close(self) -> None:
        """Close client resources."""
        await _async_close_if_supported(self._account_client)


async def async_get_systems(
    hass: HomeAssistant,
    username: str,
    password: str,
    hpm_only: bool = False,
) -> list[Any]:
    """Authenticate and return available iAqualink systems."""
    _LOGGER.debug(
        "Authenticating account user=%s hpm_only=%s",
        _safe_username(username),
        hpm_only,
    )
    client = _create_aqualink_client(hass, username.strip(), password)
    try:
        await _async_login_if_supported(client)
        try:
            systems = await _async_get_systems_from_client(client)
            _LOGGER.debug(
                "Account auth systems full snapshot count=%s payload=%s",
                len(systems),
                _sanitize([_snapshot_system_full(system) for system in systems]),
            )
        except Exception as ex:  # noqa: BLE001
            try:
                raw_records = await _async_probe_raw_systems_payload(client)
                if raw_records:
                    _LOGGER.debug(
                        "Account auth raw probe systems count=%s records=%s",
                        len(raw_records),
                        _sanitize(raw_records),
                    )
            except Exception as probe_ex:  # noqa: BLE001
                _LOGGER.debug("Raw systems probe failed during auth: %s", probe_ex)
            raise ex
    finally:
        try:
            await _async_close_if_supported(client)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Ignoring iaqualink close failure during auth: %s", err)

    if not hpm_only:
        _LOGGER.debug("Returning all systems count=%s", len(systems))
        return systems
    filtered = [system for system in systems if _is_hpm_system(system)]
    _LOGGER.debug("Returning HPM systems count=%s", len(filtered))
    return filtered
