"""Unit tests for local iAqualink API helpers and client behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "iaqualink_hpm"
    / "local_api.py"
)
_SPEC = importlib.util.spec_from_file_location("iaqualink_hpm_local_api", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load local_api module from {_MODULE_PATH}")
_LOCAL_API = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _LOCAL_API
_SPEC.loader.exec_module(_LOCAL_API)

AqualinkApiConnectionException = _LOCAL_API.AqualinkApiConnectionException
AqualinkAuthenticationException = _LOCAL_API.AqualinkAuthenticationException
AqualinkClient = _LOCAL_API.AqualinkClient
AqualinkHeatPump = _LOCAL_API.AqualinkHeatPump
AqualinkServiceException = _LOCAL_API.AqualinkServiceException
AqualinkThermostat = _LOCAL_API.AqualinkThermostat
_build_login_payloads = _LOCAL_API._build_login_payloads
_extract_auth_token = _LOCAL_API._extract_auth_token
_hmac_password = _LOCAL_API._hmac_password
_parse_systems = _LOCAL_API._parse_systems
_sha1_password = _LOCAL_API._sha1_password


class _DummyResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str = "",
        json_data: object | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class _DummyHttpClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _DummyResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if not self._responses:
            raise AssertionError("No prepared response")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response  # type: ignore[return-value]


class TestLocalApiHelpers(unittest.TestCase):
    def test_build_login_payloads_are_unique_and_expected(self) -> None:
        username = "user@example.com"
        password = "s3cret"
        payloads = _build_login_payloads(username, password)

        self.assertEqual(len(payloads), 5)
        unique = {tuple(sorted(payload.items())) for payload in payloads}
        self.assertEqual(len(unique), len(payloads))

        self.assertIn(
            {"api_key": payloads[0]["api_key"], "email": username, "password": password},
            payloads,
        )
        self.assertIn(
            {
                "api_key": payloads[0]["api_key"],
                "email": username,
                "password": _hmac_password(username, password),
            },
            payloads,
        )
        self.assertIn(
            {
                "api_key": payloads[0]["api_key"],
                "username": username,
                "password": _hmac_password(username, password),
            },
            payloads,
        )
        self.assertIn(
            {
                "api_key": payloads[0]["api_key"],
                "username": username,
                "password": password,
            },
            payloads,
        )
        self.assertIn(
            {
                "api_key": payloads[0]["api_key"],
                "email": username,
                "password": _sha1_password(password),
            },
            payloads,
        )

    def test_extract_auth_token_from_nested_payload(self) -> None:
        payload = {
            "meta": {"status": "ok"},
            "result": [
                {"id": 1},
                {"session": {"access_token": "abcdefghi"}},
            ],
        }
        self.assertEqual(_extract_auth_token(payload), "abcdefghi")

    def test_parse_systems_parses_devices_and_deduplicates_keys(self) -> None:
        payload = {
            "systems": [
                {
                    "serial_number": "SER1",
                    "name": "Main system",
                    "devices": [
                        {"key": "HP1", "device_type": "heatpump", "operation_mode": "heat"},
                        {"key": "hp1", "device_type": "heatpump", "operation_mode": "cool"},
                        {"key": "TH1", "device_type": "thermostat", "temperature": "21"},
                    ],
                },
                {"serial_number": "SER1", "model": "Z400iq"},
                {"serial_number": "SER2", "type": "hpm", "name": "Fallback"},
            ]
        }

        systems = _parse_systems(SimpleNamespace(), payload)
        by_serial = {system.serial_number: system for system in systems}

        self.assertEqual(set(by_serial), {"SER1", "SER2"})
        self.assertEqual(by_serial["SER1"].type, "hpm")
        self.assertEqual(len(by_serial["SER1"].devices), 2)
        self.assertTrue(
            any(isinstance(device, AqualinkHeatPump) for device in by_serial["SER1"].devices)
        )
        self.assertTrue(
            any(isinstance(device, AqualinkThermostat) for device in by_serial["SER1"].devices)
        )

        self.assertEqual(by_serial["SER2"].type, "hpm")
        self.assertEqual(len(by_serial["SER2"].devices), 1)
        self.assertIsInstance(by_serial["SER2"].devices[0], AqualinkHeatPump)


class TestAqualinkClientAsync(unittest.IsolatedAsyncioTestCase):
    async def test_request_json_raises_when_auth_required_and_missing(self) -> None:
        client = AqualinkClient("u", "p", httpx_client=_DummyHttpClient([]))
        with self.assertRaises(AqualinkAuthenticationException):
            await client._request_json("GET", "https://example.invalid", auth_required=True)

    async def test_request_json_success(self) -> None:
        http_client = _DummyHttpClient(
            [_DummyResponse(status_code=200, json_data={"ok": True})]
        )
        client = AqualinkClient("u", "p", httpx_client=http_client)
        client._token = "token1234"
        client._user_id = "user1"

        payload = await client._request_json(
            "GET",
            "https://example.invalid",
            params={"serial": "abc"},
            auth_required=True,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(http_client.calls), 1)
        call = http_client.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["timeout"], 20.0)
        self.assertEqual(call["headers"]["Accept"], "application/json")

    async def test_request_json_maps_unauthorized_400_to_auth_exception(self) -> None:
        http_client = _DummyHttpClient(
            [_DummyResponse(status_code=400, text="invalid token supplied")]
        )
        client = AqualinkClient("u", "p", httpx_client=http_client)
        client._token = "token1234"
        client._user_id = "user1"

        with self.assertRaises(AqualinkAuthenticationException):
            await client._request_json("GET", "https://example.invalid", auth_required=True)

    async def test_request_json_maps_500_to_connection_exception(self) -> None:
        http_client = _DummyHttpClient([_DummyResponse(status_code=503, text="upstream down")])
        client = AqualinkClient("u", "p", httpx_client=http_client)
        client._token = "token1234"
        client._user_id = "user1"

        with self.assertRaises(AqualinkApiConnectionException):
            await client._request_json("GET", "https://example.invalid", auth_required=True)

    async def test_send_device_command_falls_back_to_text_value(self) -> None:
        client = AqualinkClient("u", "p", httpx_client=_DummyHttpClient([]))
        client._token = "token1234"
        client._user_id = "user1"

        calls: list[dict[str, object]] = []

        async def _fake_request_json(
            method: str,
            url: str,
            *,
            params: dict[str, object] | None = None,
            json: dict[str, object] | None = None,
            auth_required: bool,
        ) -> object:
            del method, url, json, auth_required
            assert params is not None
            calls.append(params)
            if params["value"] == "heat":
                return {"ok": True}
            raise AqualinkServiceException("unsupported numeric value")

        client._request_json = _fake_request_json  # type: ignore[method-assign]

        result = await client.send_device_command(
            serial="SER1",
            device=SimpleNamespace(key="dev1"),
            action_candidates=("mode",),
            value=1,
            text_value="heat",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual([call["value"] for call in calls], [1, 1, 1, "heat"])

    async def test_send_device_command_raises_last_service_error(self) -> None:
        client = AqualinkClient("u", "p", httpx_client=_DummyHttpClient([]))
        client._token = "token1234"
        client._user_id = "user1"
        calls: list[dict[str, object]] = []

        async def _always_fail(
            method: str,
            url: str,
            *,
            params: dict[str, object] | None = None,
            json: dict[str, object] | None = None,
            auth_required: bool,
        ) -> object:
            del method, url, json, auth_required
            assert params is not None
            calls.append(params)
            raise AqualinkServiceException(f"failure-{len(calls)}")

        client._request_json = _always_fail  # type: ignore[method-assign]

        with self.assertRaises(AqualinkServiceException) as ctx:
            await client.send_device_command(
                serial="SER1",
                device=SimpleNamespace(key="dev1"),
                action_candidates=("a", "b"),
                value=7,
            )

        self.assertIn("failure-6", str(ctx.exception))
        self.assertEqual(len(calls), 6)
