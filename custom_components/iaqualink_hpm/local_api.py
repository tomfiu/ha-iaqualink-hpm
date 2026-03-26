"""Local iAqualink API client focused on HPM systems.

This replaces the external ``iaqualink`` package so we can iterate on HPM
support directly inside this integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

LOGIN_URL = "https://prod.zodiac-io.com/users/v1/login"
SYSTEMS_URL = "https://r-api.iaqualink.net/devices.json"
DEVICE_SHADOW_URL = "https://prod.zodiac-io.com/devices/v1/{serial}/shadow"
DEVICE_COMMAND_URL = "https://prod.zodiac-io.com/devices/v1/{serial}/shadow"
API_KEY = "EOOEMOW4YR6QNB07"
SYMBOLS = "!@#$%^&*()"


class AqualinkAuthenticationException(Exception):
    """Raised when authentication fails."""


class AqualinkApiConnectionException(Exception):
    """Raised when API transport fails."""


class AqualinkServiceException(Exception):
    """Raised when API returns an unexpected service response."""


def _resolve_first(raw: dict[str, Any], *keys: str) -> Any:
    """Resolve first non-empty value for known payload aliases."""
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalize_mode(mode: str | None) -> str:
    value = str(mode or "").strip().lower()
    if value in {"off", "heat", "cool", "auto"}:
        return value
    return "off"


def _normalize_preset(preset: str | None) -> str:
    value = str(preset or "").strip().lower()
    if value in {"boost", "quiet", "silent", "normal"}:
        return "quiet" if value == "silent" else value
    return "normal"


@dataclass
class AqualinkSystem:
    """Minimal system model expected by this integration."""

    client: AqualinkClient
    serial_number: str
    name: str
    type: str
    model: str
    version: str | None
    devices: list[Any] = field(default_factory=list)


class AqualinkDevice:
    """Base Aqualink device."""

    def __init__(self, client: AqualinkClient, serial_number: str, raw: dict[str, Any]) -> None:
        self._client = client
        self._serial_number = serial_number
        self._raw: dict[str, Any] = {}
        self.key = ""
        self.name = ""
        self.status: str | None = None
        self.temperature: float | None = None
        self.target_temperature: float | None = None
        self.temperature_unit = "C"
        self.min_temperature = 5
        self.max_temperature = 40
        self.update_from_raw(raw)

    def update_from_raw(self, raw: dict[str, Any]) -> None:
        self._raw = dict(raw)
        self.key = str(
            _resolve_first(
                raw,
                "key",
                "device_key",
                "id",
                "name",
            )
            or "unknown"
        )
        self.name = str(_resolve_first(raw, "name", "label", "device_name") or self.key)
        raw_status = _resolve_first(raw, "status", "state", "connection_state")
        self.status = str(raw_status) if raw_status is not None else None
        self.temperature = _to_float(
            _resolve_first(
                raw,
                "temperature",
                "temp",
                "water_temp",
                "current_temperature",
                "value",
            )
        )
        self.target_temperature = _to_float(
            _resolve_first(
                raw,
                "target_temperature",
                "setpoint",
                "set_point",
                "target",
                "desired_temperature",
            )
        )
        unit = str(_resolve_first(raw, "temperature_unit", "unit", "temp_unit") or "").upper()
        self.temperature_unit = "F" if unit.startswith("F") else "C"
        self.min_temperature = int(_to_float(_resolve_first(raw, "min_temperature", "min")) or 5)
        self.max_temperature = int(_to_float(_resolve_first(raw, "max_temperature", "max")) or 40)

    async def set_temperature(self, value: float) -> Any:
        rounded = int(round(value))
        return await self._client.send_device_command(
            serial=self._serial_number,
            device=self,
            action_candidates=(
                "setpoint",
                "set_point",
                "target_temperature",
                "temperature_setpoint",
                "spa_htr_set_point",
            ),
            value=rounded,
        )


class AqualinkThermostat(AqualinkDevice):
    """Thermostat model used by HA climate entity."""


class AqualinkHeatPump(AqualinkDevice):
    """Heat pump model used by HA climate entity."""

    def __init__(self, client: AqualinkClient, serial_number: str, raw: dict[str, Any]) -> None:
        self.operation_mode = "off"
        self.can_heat = True
        self.can_cool = True
        self.preset_mode = "normal"
        self.air_temperature: float | None = None
        super().__init__(client, serial_number, raw)

    def update_from_raw(self, raw: dict[str, Any]) -> None:
        super().update_from_raw(raw)
        self.operation_mode = _normalize_mode(
            _resolve_first(raw, "operation_mode", "mode", "state", "hvac_mode")
        )
        can_heat = _resolve_first(raw, "can_heat", "heat_enabled")
        can_cool = _resolve_first(raw, "can_cool", "cool_enabled")
        self.can_heat = True if can_heat is None else _to_bool(can_heat)
        self.can_cool = True if can_cool is None else _to_bool(can_cool)

        self.air_temperature = _to_float(
            _resolve_first(
                raw,
                "air_temperature",
                "air_temp",
                "ambient_temp",
                "ambient_temperature",
                "outdoor_temp",
                "outside_temp",
                "inlet_air_temp",
            )
        )

        # Derive preset from dedicated fields or boolean flags.
        raw_preset = _resolve_first(raw, "preset", "preset_mode")
        if raw_preset is not None:
            self.preset_mode = _normalize_preset(str(raw_preset))
        elif _to_bool(_resolve_first(raw, "boost", "turbo", "boost_mode")):
            self.preset_mode = "boost"
        elif _to_bool(_resolve_first(raw, "quiet", "silent", "quiet_mode", "silent_mode")):
            self.preset_mode = "quiet"
        else:
            self.preset_mode = "normal"

    async def set_operation_mode(self, mode: str) -> Any:
        normalized = _normalize_mode(mode)
        numeric_map = {"off": 0, "heat": 1, "cool": 2, "auto": 3}
        return await self._client.send_device_command(
            serial=self._serial_number,
            device=self,
            action_candidates=(
                "pool_htr",
                "operation_mode",
                "set_mode",
                "mode",
            ),
            value=numeric_map.get(normalized, 0),
            text_value=normalized,
        )

    async def set_preset_mode(self, preset: str) -> Any:
        normalized = _normalize_preset(preset)
        numeric_map = {"normal": 0, "boost": 1, "quiet": 2}
        return await self._client.send_device_command(
            serial=self._serial_number,
            device=self,
            action_candidates=(
                "preset",
                "boost",
                "silent",
                "quiet_mode",
                "preset_mode",
            ),
            value=numeric_map.get(normalized, 0),
            text_value=normalized,
        )


class AqualinkClient:
    """Async iAqualink client with just the features needed by this integration."""

    def __init__(
        self,
        username: str,
        password: str,
        serial_number: str | None = None,
        httpx_client: Any | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self.serial_number = serial_number
        self._token: str | None = None
        self._user_id: str | None = None
        self.client_id: str | None = None
        self._client = httpx_client

    async def login(self) -> None:
        """Authenticate and cache bearer token."""
        last_error: Exception | None = None
        for payload in _build_login_payloads(self._username, self._password):
            try:
                data = await self._request_json("POST", LOGIN_URL, json=payload, auth_required=False)
            except Exception as err:  # noqa: BLE001
                last_error = err
                continue

            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    code = int(error.get("code") or 0)
                    if code in {40, 41, 42, 43}:
                        last_error = AqualinkAuthenticationException(
                            error.get("message") or "Invalid credentials"
                        )
                        continue
                    last_error = AqualinkServiceException(str(error))
                    continue

            token = _extract_auth_token(data)
            user_id = _extract_user_id(data)
            session_id = _extract_session_id(data)
            if token and user_id:
                self._token = token
                self._user_id = user_id
                self.client_id = session_id
                return

            last_error = AqualinkAuthenticationException(
                "Authentication token or user_id missing in login response"
            )

        if last_error:
            _LOGGER.warning(
                "iAqualink login failed after trying %s payload variants (type=%s): %s",
                len(_build_login_payloads(self._username, self._password)),
                last_error.__class__.__name__,
                last_error,
            )
            raise last_error
        raise AqualinkAuthenticationException("Login failed")

    async def get_systems(self) -> list[AqualinkSystem]:
        """Fetch and parse account systems/devices."""
        payload = await self._send_systems_request()
        systems = _parse_systems(self, payload)
        if self.serial_number:
            systems = [system for system in systems if system.serial_number == self.serial_number]
        # Enrich each system's devices with shadow/telemetry data.
        for system in systems:
            await self._enrich_system_from_shadow(system)
        return systems

    async def _enrich_system_from_shadow(self, system: AqualinkSystem) -> None:
        """Fetch device shadow and update device state with operational data."""
        serial = system.serial_number
        try:
            shadow = await self._request_json(
                "GET",
                DEVICE_SHADOW_URL.format(serial=serial),
                auth_required=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Shadow fetch failed for serial=%s type=%s: %s",
                serial,
                err.__class__.__name__,
                err,
            )
            return

        _LOGGER.debug("Shadow payload for serial=%s: %s", serial, shadow)
        reported = _extract_shadow_reported(shadow)
        if not reported:
            _LOGGER.debug("No reported shadow state for serial=%s", serial)
            return

        for device in system.devices:
            merged = {**device._raw, **reported}
            device.update_from_raw(merged)

    async def _send_systems_request(self) -> Any:
        """Expose raw systems payload for integration diagnostics."""
        return await self._request_json(
            "GET",
            SYSTEMS_URL,
            params={"api_key": API_KEY, **self._auth_params()},
            auth_required=True,
        )

    async def send_device_command(
        self,
        *,
        serial: str,
        device: AqualinkDevice,
        action_candidates: tuple[str, ...],
        value: int | float,
        text_value: str | None = None,
    ) -> Any:
        """Best-effort device command dispatch across endpoint variants."""
        errors: list[Exception] = []

        # Try the shadow desired-state endpoint first (Zodiac cloud IoT pattern).
        shadow_url = DEVICE_COMMAND_URL.format(serial=serial)
        for action in action_candidates:
            for v in ([value] if text_value is None else [value, text_value]):
                try:
                    return await self._request_json(
                        "POST",
                        shadow_url,
                        json={"state": {"desired": {action: v}}},
                        auth_required=True,
                    )
                except AqualinkServiceException as err:
                    errors.append(err)
                    continue

        if errors:
            raise errors[-1]
        raise AqualinkServiceException("Unable to execute command")

    async def close(self) -> None:
        """Compatibility no-op: HA owns the shared httpx session."""
        return None

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth_required: bool,
    ) -> Any:
        if self._client is None:
            raise AqualinkApiConnectionException("HTTP client is not configured")

        headers: dict[str, str] = {"Accept": "application/json"}
        headers["User-Agent"] = "okhttp/3.14.7"
        headers["Content-Type"] = "application/json"
        if auth_required:
            if not self._token or not self._user_id:
                raise AqualinkAuthenticationException("Client is not authenticated")

        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=20.0,
            )
        except Exception as err:  # noqa: BLE001
            raise AqualinkApiConnectionException(err) from err

        if response.status_code in {401, 403}:
            raise AqualinkAuthenticationException(f"Unauthorized ({response.status_code})")
        if response.status_code == 400:
            body = response.text.lower()
            if any(token in body for token in ("unauthorized", "authentication", "invalid token")):
                raise AqualinkAuthenticationException(f"Unauthorized ({response.status_code})")
            raise AqualinkServiceException(
                f"Service error ({response.status_code}): {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise AqualinkApiConnectionException(f"API unavailable ({response.status_code})")
        if response.status_code >= 400:
            raise AqualinkServiceException(
                f"Service error ({response.status_code}): {response.text[:200]}"
            )

        try:
            return response.json()
        except Exception as err:  # noqa: BLE001
            raise AqualinkServiceException(f"Invalid JSON response: {err}") from err

    def _auth_params(self) -> dict[str, str]:
        if not self._token or not self._user_id:
            raise AqualinkAuthenticationException("Client is not authenticated")
        return {
            "authentication_token": self._token,
            "user_id": self._user_id,
        }


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


def _hmac_password(username: str, password: str) -> str:
    secret = f"{username.lower()}|{SYMBOLS}"
    return hmac.new(secret.encode(), password.encode(), hashlib.sha1).hexdigest()


def _sha1_password(password: str) -> str:
    return hashlib.sha1(password.encode()).hexdigest()


def _build_login_payloads(username: str, password: str) -> list[dict[str, Any]]:
    """Build login payload variants for API drift across account types."""
    payloads = [
        {
            "api_key": API_KEY,
            "email": username,
            "password": password,
        },
        {
            "api_key": API_KEY,
            "email": username,
            "password": _hmac_password(username, password),
        },
        {
            "api_key": API_KEY,
            "username": username,
            "password": _hmac_password(username, password),
        },
        {
            "api_key": API_KEY,
            "username": username,
            "password": password,
        },
        {
            "api_key": API_KEY,
            "email": username,
            "password": _sha1_password(password),
        },
    ]
    unique: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for payload in payloads:
        key = tuple(sorted((str(k), str(v)) for k, v in payload.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(payload)
    return unique


def _extract_auth_token(payload: Any) -> str | None:
    """Extract auth token from nested response payloads."""
    keys = {"authentication_token", "auth_token", "token", "access_token", "id_token"}
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and len(value) >= 8:
                return value
        for value in payload.values():
            token = _extract_auth_token(value)
            if token:
                return token
        return None
    if isinstance(payload, list):
        for item in payload:
            token = _extract_auth_token(item)
            if token:
                return token
    return None


def _extract_user_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("id") or payload.get("user_id")
        if value is not None and str(value).strip():
            return str(value)
        for item in payload.values():
            nested = _extract_user_id(item)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _extract_user_id(item)
            if nested:
                return nested
    return None


def _extract_session_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("session_id")
        if value is not None and str(value).strip():
            return str(value)
        for item in payload.values():
            nested = _extract_session_id(item)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _extract_session_id(item)
            if nested:
                return nested
    return None


def _extract_system_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("systems", "devices", "response", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _device_type(raw: dict[str, Any]) -> str:
    value = str(_resolve_first(raw, "device_type", "type", "class", "name") or "").lower()
    return value


def _is_heat_pump_device(raw: dict[str, Any]) -> bool:
    value = _device_type(raw)
    if any(token in value for token in ("heatpump", "heat_pump", "hpm", "z400")):
        return True
    name = str(_resolve_first(raw, "name", "label") or "").lower()
    if "heat pump" in name or "z400" in name:
        return True
    # Offline payloads can omit explicit device type but still carry HPM controls.
    return any(
        key in raw
        for key in (
            "pool_htr",
            "setpoint",
            "set_point",
            "target_temperature",
            "cool_enabled",
            "heat_enabled",
            "operation_mode",
        )
    )


def _is_thermostat_device(raw: dict[str, Any]) -> bool:
    value = _device_type(raw)
    if "thermostat" in value:
        return True
    name = str(_resolve_first(raw, "name", "label") or "").lower()
    return "thermostat" in name


def _system_type(records: list[dict[str, Any]], devices: list[dict[str, Any]]) -> str:
    for raw in records:
        explicit = str(_resolve_first(raw, "type", "system_type") or "").strip().lower()
        if explicit:
            return explicit
    if any(_is_heat_pump_device(device) for device in devices):
        return "hpm"
    for raw in records:
        model = str(_resolve_first(raw, "model", "device_model", "product_name") or "").lower()
        name = str(_resolve_first(raw, "name", "system_name", "label") or "").lower()
        if "z400" in model or "heat pump" in name:
            return "hpm"
    return "unknown"


def _parse_devices(
    client: AqualinkClient,
    serial_number: str,
    raw_devices: list[dict[str, Any]],
) -> list[Any]:
    devices: list[Any] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_devices):
        raw_record = dict(raw)
        if not _resolve_first(raw_record, "key", "device_key", "id", "name"):
            raw_record["key"] = f"device_{index}"
        if _is_heat_pump_device(raw):
            parsed = AqualinkHeatPump(client, serial_number, raw_record)
        elif _is_thermostat_device(raw):
            parsed = AqualinkThermostat(client, serial_number, raw_record)
        else:
            parsed = None

        if parsed is None:
            continue

        key = parsed.key.lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        devices.append(parsed)
    return devices


def _parse_systems(client: AqualinkClient, payload: Any) -> list[AqualinkSystem]:
    records = _extract_system_records(payload)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in records:
        serial = str(
            _resolve_first(raw, "serial_number", "serial", "serialNo", "system_id")
            or ""
        ).strip()
        if not serial:
            continue
        grouped.setdefault(serial, []).append(raw)

    systems: list[AqualinkSystem] = []
    for serial, serial_records in grouped.items():
        raw_devices: list[dict[str, Any]] = []
        for raw in serial_records:
            nested = raw.get("devices")
            if isinstance(nested, list):
                raw_devices.extend(item for item in nested if isinstance(item, dict))
            else:
                raw_devices.append(raw)

        devices = _parse_devices(client, serial, raw_devices)
        sys_type = _system_type(serial_records, raw_devices)
        if not devices and sys_type in {"hpm", "heatpump", "heat_pump", "hp"}:
            fallback_name = str(_resolve_first(serial_records[0], "name", "label") or "Heat Pump")
            devices = [
                AqualinkHeatPump(
                    client,
                    serial,
                    {**serial_records[0], "key": "heat_pump", "name": fallback_name},
                )
            ]

        if not devices:
            continue

        model = str(_resolve_across_records(serial_records, "model", "device_model", "product_name") or "")
        name = str(_resolve_across_records(serial_records, "name", "system_name", "label") or serial)
        version = _resolve_across_records(serial_records, "version", "firmware", "software_version")

        systems.append(
            AqualinkSystem(
                client=client,
                serial_number=serial,
                name=name,
                type=sys_type,
                model=model,
                version=str(version) if version is not None else None,
                devices=devices,
            )
        )

    _LOGGER.debug("Parsed local API systems count=%s", len(systems))
    return systems


def _resolve_across_records(records: list[dict[str, Any]], *keys: str) -> Any:
    for raw in records:
        value = _resolve_first(raw, *keys)
        if value is not None and value != "":
            return value
    return None


def _extract_shadow_reported(payload: Any) -> dict[str, Any] | None:
    """Extract the reported state dict from an AWS IoT device shadow payload.

    Handles both the full shadow format ``{"state": {"reported": {...}}}`` and a
    flat dict returned by some Zodiac proxy endpoints.
    """
    if not isinstance(payload, dict):
        return None
    # Full shadow: {"state": {"reported": {...}}}
    state = payload.get("state")
    if isinstance(state, dict):
        reported = state.get("reported")
        if isinstance(reported, dict):
            return reported
        # Some endpoints nest under "desired" only when offline; try both.
        desired = state.get("desired")
        if isinstance(desired, dict):
            return desired
    # Flat payload — treat the whole dict as reported state if it has sensor keys.
    sensor_keys = {
        "temperature", "temp", "water_temp", "target_temperature", "setpoint",
        "operation_mode", "mode", "air_temperature", "air_temp", "status",
        "state", "preset", "boost", "quiet",
    }
    if any(k in payload for k in sensor_keys):
        return payload
    return None
