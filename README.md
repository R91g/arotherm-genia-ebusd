<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/custom_components/arotherm_genia_ebusd/brand/icon.png" alt="aroTHERM & GeniaAir (eBUS)" width="150">
</p>

# aroTHERM & GeniaAir (eBUS) - Home Assistant Integration

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/default)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-41BDF5.svg?style=for-the-badge)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-local__push-00B050.svg?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://github.com/R91g/arotherm-genia-ebusd/blob/main/LICENSE)

**🇬🇧 English** | [🇪🇸 Leer en Español](README_es.md)

---

**aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) is a Home Assistant custom integration for **Vaillant** and **Saunier Duval** R290 air-to-water heat pumps managed by `sensoCOMFORT` (`VRC 720`) or `MiPro Sense` (`SRC 720`) system controllers. It communicates with the heating system locally through [ebusd](https://github.com/john30/ebusd) over MQTT; no cloud account is required.

ebusd's default register definitions predate these R290 heat pump boards and do not cover most of their messages, so this project ships its own CSV definitions for the outdoor unit (`08.hmux0` / `08.hmu`), climate controller (`15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3`), hydraulic module (`76.vwzio`) and wireless receiver (`04.netx3`). On top of that decoded telemetry it adds typed entities grouped by physical device and local control: setpoints, operating modes, weekly schedules, quick veto, holiday mode and bus diagnostics.

## Features

- Local push over ebusd's MQTT JSON output; no ebusd MQTT auto-discovery entities in Home Assistant.
- Passive bus listening combined with ebusd's scheduled reads (`r1` for electric power, `r2` for core flow/return/flow rate); the integration adds a gentle fallback polling loop only when no official cloud gateway is present.
- Zone 1 climate (heat / cool / off) with presets (scheduled, continuous manual, eco, quick veto, holiday), firmware sentinel filtering, automatic cooling double-lock calendar handling and holiday priority over cooling.
- Domestic hot water with one-time boost that temporarily raises the setpoint to work around the factory charging hysteresis, plus weekly anti-legionella day/time control.
- Weekly schedule writing for heating, cooling, DHW, circulation and silent mode, up to 3 slots per day at 1-minute resolution.
- Native heating quick veto and a persistent timed cooling quick veto managed by the integration across restarts.
- Wh-resolution energy counters per mode, computed thermal power and COP/EER, ready for the Energy Dashboard.
- Optional ebusd TCP diagnostics (`info` and CSV `find` verification), missing-CSV detection, anonymized dumps and symbolic register read/write actions.
- UI in English, Spanish and German.

## Supported Hardware

The integration covers the Vaillant `aroTHERM plus` / Saunier Duval `GeniaAir Max` R290 families (current `/7.1` and previous `/6` generations), the `76.vwzio` hydraulic modules and towers (`VWZ MEH/MH`, `uniTOWER`, `HPIM 7`, `GeniaSet`), the `VRC 720` / `SRC 720` system controllers (including `720/2` and `720/3` variants) and the optional wireless room thermostat and cloud gateway.

The full model tables and the per-board validation status (which boards are verified on the developer's own hardware and which rely on register maps and community reports) are in **[docs/hardware.md](docs/hardware.md)**.

## Quick Start

1. **Deploy the ebusd CSV files** from [`ebusd-configuration/`](ebusd-configuration/) into your ebusd config directory and start ebusd with `--mqttjson`.
2. **Install the integration** from the HACS default catalog (or copy `custom_components/arotherm_genia_ebusd` manually) and restart Home Assistant.
3. **Add the integration** under **Settings → Devices & Services**, pick your manufacturer and hardware models, and wait about a minute for initial hydration.

The full guide, including wiring, ebusd startup flags and first-run verification, is in **[docs/installation.md](docs/installation.md)**.

## Documentation

| Document | Contents |
| :--- | :--- |
| [Supported Hardware](docs/hardware.md) ([ES](docs/hardware_es.md)) | Full model tables and per-board validation status |
| [Installation](docs/installation.md) ([ES](docs/installation_es.md)) | Prerequisites, wiring, ebusd CSV deployment, HACS/manual install, first-run checks |
| [Configuration](docs/configuration.md) ([ES](docs/configuration_es.md)) | Reconfiguration, runtime options, everyday use, Energy Dashboard setup |
| [Actions (Services)](docs/services.md) ([ES](docs/services_es.md)) | All `arotherm_genia_ebusd.*` actions with parameters and YAML examples |
| [Troubleshooting & FAQ](docs/troubleshooting.md) ([ES](docs/troubleshooting_es.md)) | Diagnostics, common questions, how to report an issue |
| [Technical Reference](docs/technical_reference.md) ([ES](docs/technical_reference_es.md)) | Reverse-engineered eBUS protocol: frames, registers, timers, locks |
| [Changelog](CHANGELOG.md) | Release history |

## Development & Testing

The repository includes an offline unit test suite (no live Home Assistant required) and GitHub Actions workflows for Hassfest, HACS validation, Ruff and Pyright:

```bash
python -m unittest discover tests -v
ruff check .
ruff format --check .
```

## Acknowledgements

- **[john30/ebusd](https://github.com/john30/ebusd) & [ebusd-configuration](https://github.com/john30/ebusd-configuration):** the eBUS daemon, protocol specifications and community register database that make local communication possible.
- **[signalkraft/ebusd-vaillant-component](https://github.com/signalkraft/ebusd-vaillant-component):** inspiration for the diagnostic dump and live topic recording services.
- **[MarkBovee/vaillant-ebus](https://github.com/MarkBovee/vaillant-ebus):** exploration of Vaillant controller registers and real-world capture fixtures.

## License & Disclaimer

Distributed under the **[MIT License](LICENSE)** - Copyright (c) 2026 [@R91g](https://github.com/R91g).

This is an independent open-source community project, not affiliated with, endorsed by, or supported by **Vaillant GmbH** or **Saunier Duval**. Use at your own responsibility; only modify installer-level hydraulic or bivalence parameters if you understand your heating system design.
