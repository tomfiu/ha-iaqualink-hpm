# iAqualink Heat Pump

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1.0%2B-blue.svg)
![Integration](https://img.shields.io/badge/Integration-climate-green.svg)

Custom Home Assistant integration for iAqualink heat pump systems (`hpm`), including Zodiac Z400iq.

This project is community-maintained and is not affiliated with Zodiac / Fluidra.

## Motivation

The official Home Assistant iAqualink integration is focused on pool/spa systems.
It does not currently expose iAqualink heat pump (`hpm`) systems as Home Assistant `climate` entities.

This custom integration exists to close that gap and provide practical heat pump control and monitoring through Home Assistant.

## Scope

- Designed for iAqualink heat pump systems (`hpm`)
- Exposes heat pump controls through Home Assistant `climate`
- Keeps using iAqualink cloud authentication and APIs

If your setup is only a pool/spa system, the built-in Home Assistant integration is typically the better default choice.

## Features

- Native UI config flow (`username` / `password`)
- Cloud polling through the iAqualink API
- Automatic HPM system discovery
- Climate support for `AqualinkHeatPump`
- Climate support for `AqualinkThermostat` (when exposed by the account payload)
- HVAC mode mapping: iAqualink `off` / `heat` / `cool` / `auto`
- HVAC mode mapping: Home Assistant `off` / `heat` / `cool` / `heat_cool`

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

This integration currently creates `climate` entities only.

Typical behavior:
- The device can be discovered even while physically offline.
- In that case, entity values may be unavailable until the next successful cloud refresh.

## Polling

- Default refresh interval: `90 seconds`
- Integration type: `cloud_polling`

## Troubleshooting

### No entities appear

1. Confirm logs show at least one discovered system with `type: hpm`.
2. Confirm platform forwarding line appears in logs (`platforms=['climate']`).
3. Restart Home Assistant after updating the integration.

### Invalid authentication

- Re-enter credentials in the integration config flow.
- Verify login on the official iAqualink app/site with the same account.
- Check for failed auth entries in Home Assistant logs.

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
- Full discovered account systems snapshot
- Last coordinator payload

## License

- This repository is licensed under MIT: see [LICENSE](LICENSE).
- Third-party attribution and upstream licenses: see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
