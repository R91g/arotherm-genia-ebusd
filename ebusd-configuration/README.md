# Optimized eBUSd CSV Configuration — aroTHERM & GeniaAir (eBUS)

**🇬🇧 English** | [🇪🇸 Documentación en Español](../README_es.md#paso-1-desplegar-los-archivos-csv-optimizados-en-ebusd) | [🇬🇧 Main README](../README.md#step-1-deploy-optimized-ebusd-csv-configuration)

This directory contains **reverse-engineered and collision-free** eBUS message definitions (`.csv`) purpose-built for modern **Vaillant** and **Saunier Duval** R290 air-to-water heat pump installations (replacing upstream default `ebusd` CSVs, which target legacy boilers/controllers and are incompatible with these platforms):

- **Outdoor Heat Pumps (`08.hmux0`):** Vaillant `aroTHERM plus ES` (`VWL 55–155/7.1 A`) / `aroTHERM plus` (`VWL 35–125/6 A`) & Saunier Duval `GeniaAir Max ES` (`5–15`) / `GeniaAir Iso ES` / `GeniaAir Max` (`4–15`).
- **System Climate Controllers (`15.bass3` / `15.basv3`):** Vaillant `sensoCOMFORT` (`VRC 720/2`, `VRC 720/3`) & Saunier Duval `MiPro Sense` (`SRC 720/2`, `SRC 720/3`).
- **Indoor Hydraulic Modules & Towers (`76.vwzio`):** Vaillant `VWZ MEH 97/7`, `VWZ MH 97/7`, `VWZ AI 7/230V`, `uniTOWER VIH QW 190/7` & Saunier Duval `HPIM 7 230V`, `HE 9-7 W`, `GeniaSet FEW/FIW 200-7`.
- **Wireless Room Thermostats (`04.netx3` / `f6.netx3`):** Vaillant `sensoCOMFORT RF` (`VRC 720f`) & Saunier Duval `MiPro Sense RF` (`SRC 720f`).
- **Official Cloud Gateways (Optional, eBUS `f1`):** Vaillant `myVAILLANT connect` (`VR 940f`) / `sensoNET` (`VR 921`) & Saunier Duval `MiGo Link` (`SR 940f`).

---

## File Map & eBUS Device Addresses

| File | eBUS Address | Physical Component | Primary Function |
| :--- | :---: | :--- | :--- |
| **`broadcast.csv`** | `broadcast` / `FE` | Global bus | Broadcast outdoor temperature, eBUS system date/time, active cooling broadcast status. |
| **`vaillant/08.hmux0.csv`** | `08` (`HMUX0`) | Outdoor unit PCB | Compressor telemetry, R290 high pressure, flow rate, instantaneous power, IEEE 754 (`EXP`) energy counters, runtime hours/starts, and 52+ `HMUStatusCode` states. |
| **`vaillant/15.bass3.csv`** | `15` (`BASS3`) | `MiPro Sense` / `sensoCOMFORT` | Day/night/cooling setpoints, heating curves, DHW control & hysteresis, Cooling Double-Lock dates, service energy totals, and `b5 55` weekly timers. |
| **`vaillant/15.basv3.csv`** | `15` (`BASV3`) | `sensoCOMFORT` (reporting `BASV3`) | Twin definition of `15.bass3.csv` for Vaillant `sensoCOMFORT` controllers that identify as `ID=BASV3`. |
| **`vaillant/76.vwzio.csv`** | `76` (`VWZIO`) | Hydraulic module / tower | 3-way diverter valve (heating/DHW), secondary circuit status, backup heater diagnostics, and active error registers. |
| **`vaillant/04.netx3.csv`** | `04` | Wireless RF receiver | Reference room dial temperature and zone target setpoint. |
| **`vaillant/f6.netx3.csv`** | `f6` | Wireless RF receiver (alt) | Passive reception of wireless thermostat RF broadcast frames. |

---

## Deployment

### 1. Home Assistant eBUSd Add-on (`b4d7ad18_ebusd`)

1. Copy `broadcast.csv` → `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/broadcast.csv`
   > **Important:** `broadcast.csv` **must** be placed in the root `en/` directory, **never** inside `en/vaillant/`.
2. Copy `vaillant/*.csv` → `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/vaillant/`
3. In the Add-on **Configuration** tab:
   - **Disable "Seed HA MQTT integration config (only needed once)"** toggle (`seed_mqtt_cfg: false`). This prevents eBUSd from loading the legacy `mqtt-hassio.cfg` filter which triggers bus collisions and floods Home Assistant with raw MQTT entities.
   - In **commandline_options**, add the following arguments (one per entry):
     ```text
     --mqttjson
     --configpath=/config/ebusd-configuration/en
     --scanconfig
     --accesslevel=*
     --mqtttopic=ebusd/%circuit/%name
     --mqttvar=filter-direction=r|u|^w
     ```
     > **Note:** Adding `--mqttjson` explicitly is mandatory when `seed_mqtt_cfg` is disabled.
4. Restart the eBUSd add-on to load the updated CSV definitions.

### 2. Standalone Linux / Docker `ebusd`

1. Copy `broadcast.csv` to `/etc/ebusd/en/broadcast.csv`.
2. Copy `vaillant/*.csv` to `/etc/ebusd/en/vaillant/`.
3. Restart the service: `sudo systemctl restart ebusd` (or `docker compose restart ebusd`).

---

## License & Attribution

For full licensing details and legal notices, see [`LICENSE.md`](LICENSE.md).

- **GPL-3.0 Licensed Files:** Baseline templates and message definitions derived or adapted from [john30/ebusd-configuration](https://github.com/john30/ebusd-configuration) (including `broadcast.csv`) are licensed under the **GNU General Public License v3.0 (GPL-3.0)**, Copyright (c) John30 and eBUSd contributors.
- **Dual-Licensed Files (MIT & GPL-3.0):** Original reverse-engineered message definitions developed specifically for this project (`08.hmux0.csv`, `15.bass3.csv`, `15.basv3.csv`, `76.vwzio.csv`, `04.netx3.csv`, `f6.netx3.csv`) are dual-licensed under both the **MIT License** and **GPL-3.0** to allow seamless upstream contributions to the eBUSd project.
