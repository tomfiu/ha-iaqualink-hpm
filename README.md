# iAqualink Heat Pump

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1.0%2B-blue.svg)
![Platforms](https://img.shields.io/badge/Platforms-climate%20%7C%20sensor-green.svg)

Custom Home Assistant integration for iAqualink heat pump systems (`hpm`), including Zodiac Z400iq.

This project is community-maintained and is not affiliated with Zodiac / Fluidra.

## Motivation

The official Home Assistant iAqualink integration is focused on pool/spa systems.
It does not currently expose iAqualink heat pump (`hpm`) systems as Home Assistant `climate` entities.

This custom integration exists to close that gap and provide practical heat pump control and monitoring through Home Assistant.

## Scope

- Designed for iAqualink heat pump systems (`hpm`)
- Exposes heat pump controls through Home Assistant `climate`
- Exposes heat pump telemetry through Home Assistant `sensor`
- Keeps using iAqualink cloud authentication and APIs

If your setup is only a pool/spa system, the built-in Home Assistant integration is typically the better default choice.

## Features

- Native UI config flow (`username` / `password`)
- Cloud polling through the iAqualink API (device shadow endpoint)
- Automatic HPM system discovery
- Climate entity with HVAC mode and preset mode control
- Sensor entities for temperature, mode, and operational state
- HA Diagnostics support

## Requirements

- Home Assistant `2025.1.0` or newer
- Valid iAqualink cloud account
- Internet access from Home Assistant to iAqualink APIs

## Installation (HACS)

1. Open HACS.
2. Go to `Integrations`.
3. Add this repository as a **Custom repository** (`Integration` type).
4. Repository URL: `https://github.com/tomfiu/ha-iaqualink-hpm`
5. Install **iAqualink Heat Pump**.
6. Restart Home Assistant.

## Configuration

1. Open `Settings` -> `Devices & Services`.
2. Click `Add Integration`.
3. Search for `iAqualink Heat Pump`.
4. Enter your iAqualink account credentials.

If at least one HPM system is found, setup completes automatically.

## Entities

### Climate

One `climate` entity per heat pump device.

| Feature | Details |
|---------|---------|
| HVAC modes | `off` / `heat` / `cool` / `heat_cool` |
| Preset modes | `normal` / `boost` / `quiet` |
| Target temperature | Adjustable set-point |

### Sensors (always enabled)

| Entity | Description |
|--------|-------------|
| Temperature | Current water temperature |
| Target Temperature | Current set-point temperature |
| Air Temperature | Ambient air temperature measured by the unit |
| Status | Raw status code from the device |
| Mode | Current HVAC mode (`off` / `heat` / `cool` / `auto`) |
| Preset | Current preset (`normal` / `boost` / `quiet`) |

### Sensors (disabled by default)

These sensors are created but not enabled by default to keep the default view clean.
To enable one: `Settings` → `Devices & Services` → your device → click the entity → toggle **Enable**.

| Entity | Description |
|--------|-------------|
| Fan Speed | Fan speed level |
| Water Flow | Water flow status (`on` / `off`) |
| Heating Active | Whether the unit is actively heating |
| Cooling Active | Whether the unit is actively cooling |
| LED | LED indicator status |
| Reason Code | Internal reason / error code |
| Board Firmware | Firmware version of the heat pump main board |
| WiFi Signal | WiFi signal strength (dBm) |

## Polling

- Default refresh interval: `120 seconds` (configurable: 60–3600 seconds)
- Integration type: `cloud_polling`

### Rate limiting

The Zodiac cloud API enforces account-level rate limits on the device shadow endpoint.
To minimize `429` responses:

- A 2-second delay is inserted between the systems request and the shadow fetch within each polling cycle.
- On `429`, the integration retries up to 2 more times with increasing back-off (4 s, 8 s by default, or the server-provided `Retry-After` value).
- If all retries fail, the previous sensor values are preserved until the next successful poll — entities will **not** flip to `unknown`.

## Troubleshooting

### No entities appear

1. Confirm logs show at least one discovered system with `type: hpm`.
2. Confirm platform forwarding line appears in logs (`platforms=['climate', 'sensor']`).
3. Restart Home Assistant after updating the integration.

### Invalid authentication

- Re-enter credentials in the integration config flow.
- Verify login on the official iAqualink app/site with the same account.
- Check for failed auth entries in Home Assistant logs.

### Sensor values are unavailable

- The integration polls the Zodiac device shadow endpoint for telemetry.
- If the device is offline or not reporting to the cloud, values will be unavailable until the next successful refresh.
- Check that `Shadow payload for serial=...` appears in debug logs.

### Frequent 429 rate-limit errors

- The Zodiac API rate limit is per-account and shared with the official iAqualink / Zodiac mobile app. Close or force-stop the app to free up budget.
- Increase the polling interval in `Settings` -> `Devices & Services` -> `iAqualink Heat Pump` -> `Configure`.
- In debug logs, look for `Shadow 429 for serial=...` entries — they include the server's `Retry-After` header and rate-limit response details to help diagnose the limit.

### Enable debug logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.iaqualink_hpm: debug
```

Then restart Home Assistant.

View logs:
- UI: `Settings` -> `System` -> `Logs`
- File: `/config/home-assistant.log`

## Diagnostics

Diagnostics can be downloaded from:

`Settings` -> `Devices & Services` -> `iAqualink Heat Pump` -> `Download diagnostics`

Diagnostics include:
- Redacted config entry data
- Selected systems summary
- Full discovered account systems snapshot (including raw shadow payload)
- Last coordinator payload

## License

- This repository is licensed under MIT: see [LICENSE](LICENSE).
- Third-party attribution and upstream licenses: see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
