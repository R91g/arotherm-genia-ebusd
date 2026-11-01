<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/custom_components/arotherm_genia_ebusd/brand/icon.png" alt="aroTHERM & GeniaAir (eBUS)" width="150">
</p>

# aroTHERM & GeniaAir (eBUS) — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.4%2B-41BDF5.svg?style=for-the-badge)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-local__push-00B050.svg?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![Protocol](https://img.shields.io/badge/Protocol-eBUS%20%2F%20MQTT%20JSON-FF8C00.svg?style=for-the-badge)](https://github.com/john30/ebusd)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://github.com/R91g/arotherm-genia-ebusd/blob/main/LICENSE)

**🇬🇧 English** | [🇪🇸 Leer en Español](README_es.md)

---

**aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) is a **100% local (`local_push`), cloud-independent Home Assistant custom integration** for **Vaillant** and **Saunier Duval** R290 air-to-water heat pumps managed by **`sensoCOMFORT` (`VRC 720`)** or **`MiPro Sense` (`SRC 720`)** system controllers via [**eBUSd**](https://github.com/john30/ebusd).

Designed directly around the native eBUS protocol shared by Vaillant Group heat pumps (`08.hmux0`, `15.bass3`, `76.vwzio`, `04.netx3`), this integration replaces raw MQTT auto-discovery clutter and cloud API dependencies with **148 strongly typed entities**, real-time thermodynamic & COP/EER calculations, firmware sentinel filtering, automatic Double-Lock cooling management, and Smart Forced DHW Boost.

---

## Table of Contents

1. [Why Local eBUS?](#why-local-ebus)
2. [Supported Hardware & Brand Equivalence](#supported-hardware--brand-equivalence)
3. [Key Features & Engineering Highlights](#key-features--engineering-highlights)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
   - [Step 1: Deploy Optimized eBUSd CSV Configuration](#step-1-deploy-optimized-ebusd-csv-configuration)
   - [Step 2: Install the Integration (HACS or Manual)](#step-2-install-the-integration-hacs-or-manual)
   - [Step 3: Configure in Home Assistant](#step-3-configure-in-home-assistant)
6. [Reconfiguration & Runtime Options](#reconfiguration--runtime-options)
7. [Custom Actions (Services)](#custom-actions-services)
8. [Home Assistant Energy Dashboard Setup](#home-assistant-energy-dashboard-setup)
9. [Diagnostics, Troubleshooting & FAQ](#diagnostics-troubleshooting--faq)
10. [Technical Reference & Reverse Engineering](#technical-reference--reverse-engineering)
11. [Development & Testing](#development--testing)
12. [License & Disclaimer](#license--disclaimer)

---

## Why Local eBUS?

| Capability | Cloud Integrations (`myVAILLANT` / `MiGo Link`) | Default `ebusd` (`ebusd-configuration` + `mqtt-hassio.cfg`) | **aroTHERM & GeniaAir (eBUS)** |
| :--- | :---: | :---: | :---: |
| **Modern R290 Heat Pump CSV Support** | ✅ Proprietary cloud | ❌ **Incompatible default CSVs** (built for legacy boilers / old VRC 700) | ✅ **Reverse-engineered & custom-optimized CSVs** |
| **2400-Baud eBUS Bus Collisions** | ✅ Native gateway (`f1`) | ❌ **Frequent bus collisions** from uncoordinated active polling | ✅ **Collision-free** (passive `u` synergy + paced arbitration) |
| **100% Local Operation (Works offline)** | ❌ Cloud-dependent | ✅ Local | ✅ **100% Local (`local_push`)** |
| **Zero Cloud Rate Limits / Outages** | ❌ Subject to API throttling | ✅ Unlimited | ✅ **Sub-second MQTT push** |
| **Clean Device Hierarchy** | ⚠️ Limited telemetry | ❌ Hundreds of flat/cryptic entities | ✅ **4 structured logical devices** |
| **Cooling Double-Lock Automation** | ✅ Handled in vendor app | ❌ Manual multi-register hex/date edits | ✅ **Automatic Lock 1 & Lock 2** |
| **Anti-Sentinel Setpoint Filtering** | ✅ Hidden by vendor app | ❌ Exposes `5.0 °C` & `99.0 °C` spikes | ✅ **Filtered + seasonal memory** |
| **Smart Forced DHW Boost (`ΔT < 5 K`)** | ❌ Blocked by `5.0 K` hysteresis | ❌ Blocked by `5.0 K` hysteresis | ✅ **Automatic hysteresis bypass** |
| **Live Thermal Power & COP / EER** | ❌ Coarse daily/monthly estimates | ❌ Raw unlinked registers | ✅ **Real-time ΔT, W, Live & Mode COP/EER** |

---

## Supported Hardware & Brand Equivalence

Vaillant and Saunier Duval aerothermal heat pumps share **100% identical eBUS electronic control boards and register maps**. During setup (or at any time via **Reconfigure**), selecting your manufacturer tailors all device names, commercial model labels, and controller designations to your installation.

### 1. Outdoor Units — Heat Pumps (`08.hmux0`)

| Generation | Vaillant Commercial Models | Saunier Duval Commercial Models | Refrigerant / Board |
| :--- | :--- | :--- | :--- |
| **Current Generation (`/7.1` ES)** | `aroTHERM plus ES VWL 55/7.1 A 230V`<br>`aroTHERM plus ES VWL 85/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 400V`<br>`aroTHERM plus ES VWL 155/7.1 A 230V`<br>`aroTHERM plus ES VWL 155/7.1 A 400V` | `GeniaAir Max ES 5`<br>`GeniaAir Max ES 8`<br>`GeniaAir Max ES 12`<br>`GeniaAir Max ES 15`<br>`GeniaAir Iso ES` | R290 (`08.hmux0`) |
| **Previous Generation (`/6` & `Max` Legacy)** | `aroTHERM plus VWL 35/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 55/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 75/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 105/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 125/6 A (Legacy)` | `GeniaAir Max 4 (Legacy)`<br>`GeniaAir Max 6 (Legacy)`<br>`GeniaAir Max 8 (Legacy)`<br>`GeniaAir Max 11 (Legacy)`<br>`GeniaAir Max 15 (Legacy)` | R290 (`08.hmux0`) |

### 2. Indoor Hydraulic Modules, Interfaces & Towers (`76.vwzio`)

| Component Type | Vaillant Models | Saunier Duval Models | eBUS Address |
| :--- | :--- | :--- | :---: |
| **Wall Hydraulic Module (with backup heater)** | `VWZ MEH 97/7` | `HPIM 7 230V` / `Módulo Hidráulico HE 9-7 W` | `76` (`VWZIO`) |
| **Wall Hydraulic Module / Appliance Interface** | `VWZ MH 97/7` / `VWZ AI 7/230V` | `HPIM 7 230V` | `76` (`VWZIO`) |
| **All-in-One Hydraulic Tower (Integrated DHW)** | `uniTOWER VIH QW 190/7` | `GeniaSet FEW/FIW 200-7` | `76` (`VWZIO`) |

### 3. System Controllers & Optional Accessories

| Component Role | Vaillant Models | Saunier Duval Models | eBUS Address |
| :--- | :--- | :--- | :---: |
| **System Climate Controller (Required)** | `sensoCOMFORT VRC 720` (`720/2`, `720/3`) | `MiPro Sense SRC 720` (`720/2`, `720/3`) | `15` (`BASS3`) |
| **Wireless Room Thermostat / RF Receiver (Optional)** | `sensoCOMFORT RF VRC 720f` (`NETX3`) | `MiPro Sense RF SRC 720f` (`NETX3`) | `04` / `f6` |
| **Official Cloud Gateway (Optional — Passive Synergy)** | `myVAILLANT connect VR 940f` / `sensoNET VR 921` | `MiGo Link SR 940f` | Master `f1` |

> **Note:** An official cloud gateway (`myVAILLANT connect` / `MiGo Link`) is **not required**. If installed, the integration passively listens to its periodic eBUS queries with zero extra bus traffic. If absent, disable the cloud gateway toggle during setup and the integration will automatically run a gentle, collision-safe `/get` fallback polling loop.

---

## Key Features & Engineering Highlights

### 1. 100% Autonomous Native MQTT JSON Architecture (`local_push`)
- Subscribes directly to `ebusd`'s JSON topic tree (`<mqtt_prefix>/#` with `--mqttjson` enabled) and publishes targeted `/get` and `/set` payloads.
- **Zero dependency on `mqtt-hassio.cfg`:** You do not need `ebusd`'s MQTT discovery integration (`--mqttint`), keeping your Home Assistant MQTT registry completely clean.

### 2. 2400-Baud eBUS Collision Safety & Paced Initial Hydration
- Physical eBUS is a 2-wire multi-master CSMA/CD bus operating at **2400 bps (~240 bytes/s)**. Unthrottled polling causes bus collisions with wall controllers.
- **Startup Hydration Queue:** On Home Assistant startup, the coordinator waits `5.0 s` to absorb retained MQTT payloads at zero bus cost, then requests **only missing registers** sequentially with `0.8 s` spacing.
- **Optimistic Updates & Selective Confirmation:** Writes to passive `u` registers (setpoints, modes, schedules, dates) apply immediate optimistic UI state updates without triggering redundant `/get` cache rebounds, while multi-step transitions use `0.3 s`–`0.6 s` bus pacing.

### 3. 148 Native Entities Organized into 4 Logical Devices

| Logical Device | eBUS Circuit | Highlights |
| :--- | :---: | :--- |
| **1. Outdoor Unit** (`<Outdoor Model>`) | `08.hmux0` | Live operating monitor (52+ `S.xx`/`S.xxx` states), compressor RPM/RPS/modulation, R290 high pressure, EEV steps, fan speeds, primary flow rate, high-precision flow/return temps, IEEE 754 (`EXP`) per-mode electrical, thermal & environmental yield counters (`Wh`), runtime hours/starts, and **calculated thermodynamic & system energy sensors**. |
| **2. Climate Controller** (`sensoCOMFORT` / `MiPro Sense`) | `15.bass3` | **Zone 1 Climate (`climate`)**, **Domestic Hot Water (`water_heater`)**, heating curves, flow temperature limits, bivalence points, water pressure, service energy counters (`PrEnergySumHc` / `PrEnergySumHwc`), weekly schedule summaries, and configuration switches. |
| **3. Hydraulic Interface** (`<Indoor Model>`) | `76.vwzio` | Secondary circuit operating state (heating, cooling, DHW, overrun, standby), instantaneous electrical power (`W`), `b5 16` auxiliary/secondary energy counters (`Wh`), 3-way diverter valve / secondary pump diagnostics, and active error monitoring (`OK` or fault codes). |
| **4. Wireless Room Thermostat** *(Optional)* | `04.netx3` / `f6` / `broadcast` | Wireless room dial temperature, wireless target setpoint, broadcast outdoor temperature, and eBUS system date/time. *(If no wireless unit is installed, broadcast sensors automatically attach to the Climate Controller).* |

**Platform Breakdown (148 entities total across 8 platforms):**
- `climate` (**1**): Unified Heating/Cooling/Auto thermostat for Zone 1 with presets (`Scheduled (Comfort)`, `Continuous Manual`, `Eco (Night setback)`, `Quick Veto Override`, `Away / Holiday Mode`).
- `water_heater` (**1**): Domestic Hot Water (DHW) cylinder controller (`Off`, `Time-controlled (Schedule)`, `Continuous (24h)`, `Boost`).
- `sensor` (**98**): 94 telemetry, `Wh`-precision energy, diagnostic, and calculated thermodynamic sensors + 4 weekly timer schedule summary sensors (with full daily slot attributes).
- `binary_sensor` (**8**): Compressor running, primary pump, defrost active, energy integration active, Zone 1 heating demand, hardware cooling lock release, broadcast cooling cycle, and physical eBUS signal.
- `number` (**25**): All installer and user numeric parameters (heating curve, excess temp, min/max flow setpoints, summer limit, day/night/manual/veto/cooling/holiday setback setpoints, DHW setpoint & hysteresis/offset/timers, bivalence points, max room humidity).
- `select` (**5**): Zone 1 heating mode, Zone 1 cooling mode, DHW mode, night lowering mode (`eco`/`night`/`off`), and room temperature modulation mode (`off`/`modulating`/`thermostat`).
- `switch` (**6**): Away Mode (`Holiday Mode`), One-Time DHW Charge (`Boost`), Cooling Season Authorization (`Lock 1`), Adaptive Heating Curve, DHW Parallel Loading, and Global System Off *(disabled by default for safety)*.
- `datetime` (**4**): Interactive UI controls for Away Mode Start (`datetime`), Away Mode End (`datetime`), Manual Cooling Start Date (`datetime`), and Manual Cooling End Date (`datetime`).

### 4. Zone 1 Climate: Anti-Sentinel Filter & Automatic Double-Lock Cooling
- **Firmware Anti-Sentinel Filtering:**
  - When heating is turned off (`Z1OpMode = off`), the controller reports `5.0 °C` (frost protection) in `Z1ActualRoomTempDesired`.
  - When cooling is turned off (`Z1OpModeCooling = off`), the controller reports `99.0 °C` (`0000c642` IEEE 754 float) in `Z1CoolingTempDesired`.
  - The integration filters out both sentinel values, memorizes your real heating and cooling comfort targets independently across Home Assistant restarts (`RestoreEntity`), and prevents out-of-range UI spikes.
- **Transparent Double-Lock Cooling Automation & Custom Calendar Periods:**
  - Vaillant / Saunier Duval controllers guard active cooling behind two independent locks: **Lock 1** (a calendar date window `CoolingStartDate`–`CoolingEndDate`) and **Lock 2** (`Z1OpModeCooling`).
  - **Open-Ended Mode (Default):** Selecting **`Cool`** on the thermostat automatically turns off heating, opens **Lock 1** indefinitely (`01;01;26` to `01;01;99`), activates **Lock 2** (`Z1OpModeCooling = day`), and restores your saved cooling target temperature.
  - **Custom Window Mode:** If you set custom dates via `Manual Cooling Start Date` and `Manual Cooling End Date` (either before switching on or while running), the integration programs your specific date window without forcing indefinite operation, automatically restricting active cooling to that timeframe.
  - Switching back to **`Heat`** or **`Off`** automatically closes **Lock 1** (`01;01;19` epoch, matching the official `myVAILLANT` / `MiGo Link` app behavior) and restores your heating setpoint.

### 5. Domestic Hot Water (`water_heater`): Smart Forced DHW Boost
- By factory design, `sensoCOMFORT` / `MiPro Sense` enforces a strict charging hysteresis (`CylinderChargeHyst = 5.0 K`). If your DHW setpoint is `50.0 °C` and the tank is currently at `47.0 °C`, activating standard one-time boost (`HwcSFMode = load`) does **not** start the compressor because `47.0 °C > (50.0 - 5.0) °C`.
- With **Smart Forced DHW Boost** enabled (default):
  1. Whenever `T_tank > (T_target - Hysteresis)`, triggering **`Boost`** (via the `water_heater` card, the **One-Time DHW Charge (Boost)** switch, or the `arotherm_genia_ebusd.force_dhw_boost` action) saves your current setpoint, dynamically raises `HwcTempDesired` to **`T_tank + Hysteresis + 1.5 °C`** (capped at `68.0 °C`), and sends `HwcSFMode = load` `1.0 s` later to guarantee immediate compressor ignition regardless of your normal DHW setpoint.
  2. The coordinator continuously monitors the charging cycle and **automatically restores your original DHW setpoint** as soon as charging finishes (`HwcSFMode == auto`), the target is reached, boost is manually cancelled, or the 60-minute safety timeout elapses.

### 6. Real-Time Thermodynamic & COP / EER Engine
Computed automatically inside the coordinator whenever live `08.hmux0` and `76.vwzio` telemetry arrives:
```text
Primary ΔT (K)               = T_flow (RunDataFlowTemp) - T_return (RunDataReturnTemp)
Instantaneous Thermal Power  = Flow_Rate (L/h) × |ΔT| (K) × 1.163   [Watts]
Live Instantaneous COP / EER = Thermal_Power (W) / Electric_Power (W)
Mode & Global COP / EER      = (HMUX0_Thermal_Wh + VWZIO_Thermal_Wh) / (HMUX0_Elec_Wh + VWZIO_Elec_Wh)
Total System Energy (Wh)     = Heating_Total_Wh + DHW_Total_Wh + Cooling_Total_Wh
```
*(Includes zero-clamping during defrost cycles and compressor standby to avoid phantom COP spikes from residual circulation pump flow).*

### 7. Touch-Safe Controls (`NumberMode.BOX`) & Brand-Neutral `unique_id`s
- **Touch Safety:** Every `number` entity enforces `NumberMode.BOX` (numeric input field with `+`/`-` steppers) rather than sliders, preventing accidental changes to heating curves or bivalence points while scrolling on a smartphone.
- **Zero-Loss Reconfiguration:** All 148 entity `unique_id`s follow `{entry_id}_{circuit}_{message}_{field}` with zero brand strings. Reconfiguring manufacturer or hardware models never orphans entities or breaks historical energy graphs.

---

## Prerequisites

1. **Physical eBUS Adapter:** Connected in parallel to the 2-wire eBUS terminals (`+`/`-`, polarity-insensitive) of your heat pump / hydraulic module / wall controller — for example, the [eBUS Adapter Shield v5 / C6](https://adapter.ebusd.eu/) (Ethernet, Wi-Fi, or USB).
2. **`ebusd` Daemon (`v23.2` or newer):** Running either as the **Home Assistant eBUSd Add-on** or as a standalone Linux service / Docker container, connected to your MQTT broker with **`--mqttjson`** enabled.
3. **Home Assistant (`2024.4.0` or newer):** With the core **[MQTT integration](https://www.home-assistant.io/integrations/mqtt/)** installed and connected to the same MQTT broker as `ebusd`.

### Physical Wiring & Coexistence Architecture

eBUS is a 2-wire, 24V differential serial bus designed to connect all heating devices in parallel. You can connect your eBUS adapter at any point where the bus is accessible (indoor hydraulic station, outdoor unit, or wall controller).

<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/docs/images/ebus_wiring_diagram.svg" alt="eBUS Hardware Wiring Diagram" width="900">
</p>

#### Key Hardware & Wiring Guidelines:
* **Terminal `BUS (+ / -)` (Red header):** Intended for system accessories. In typical installations, the official cloud gateway (`myVAILLANT connect` / `MiGo Link`) connects here. You can connect the eBUS adapter in parallel into this same port (by double-crimping the wires into the screw terminal or using a pair of WAGO 221 lever connectors).
* **Terminal `X25 (A / B)` (Orange header):** The communication line coming from the outdoor unit (`aroTHERM plus` / `GeniaAir Max`) lands here.
* **Shared Electrical Rail:** Connectors `BUS` and `X25` are interconnected on the PCB traces—they belong to the exact same electrical bus. Connecting your eBUS adapter to `BUS` or `X25` is functionally identical.
* **Zero Polarity:** The eBUS protocol is polarity-insensitive. All devices feature internal bridge rectifiers, so you do not need to worry about reversing `+` and `-` (or `A` and `B`).
* **100% Coexistence with Official Gateway:** If you have `myVAILLANT connect` or `MiGo Link` installed, **do not remove or disconnect it**. This integration coexists peacefully on the bus: it passively captures telemetry requested by the cloud gateway, drastically reducing bus utilization.

<details>
<summary>📸 <b>View Real-World Installation Photograph (Indoor Hydraulic Board)</b></summary>
<br>

<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/docs/images/real_installation_pcb.jpg" alt="Real installation photo inside the indoor unit" width="650">
  <br>
  <em>Real installation inside a Saunier Duval GeniaSet / Vaillant uniTOWER electrical enclosure. Notice the eBUS Adapter C6 powered via USB-C at the bottom, connected in parallel with the official MiGo Link gateway into the red <code>BUS</code> terminal, while the outdoor unit bus enters through the orange <code>X25 (A/B)</code> connector.</em>
</p>

</details>

---

## Installation

### Step 1: Deploy Optimized eBUSd CSV Configuration

> **Why are the bundled CSV files mandatory?**
> The default CSV definitions distributed with `ebusd` (`ebusd.eu` / upstream `ebusd-configuration`) were written for legacy Vaillant gas boilers and older `VRC 700` controllers — they are **not compatible** with modern R290 aerothermal heat pumps and frequently trigger **eBUS arbitration collisions** through aggressive active polling.
>
> All CSV files in [`ebusd-configuration/`](ebusd-configuration/) have been **reverse-engineered and validated on live hardware** for modern `08.hmux0`, `15.bass3`, `76.vwzio`, and `04.netx3` boards — accurately decoding R290 IEEE 754 (`EXP`) energy counters, `b5 55` weekly timer schedules, cooling Double-Lock calendar registers, and all 52+ `HMUStatusCode` states while prioritizing passive `u` frame capture for **collision-free** bus operation.

Copy the CSV files into your `ebusd` configuration directory preserving the exact folder structure below:

```text
<ebusd-config-root>/en/
├── broadcast.csv              <-- MUST be placed in the root of en/ (NEVER inside vaillant/)
└── vaillant/
    ├── 04.netx3.csv           <-- Wireless room thermostat receiver
    ├── 08.hmux0.csv           <-- Outdoor heat pump board (aroTHERM plus / GeniaAir Max)
    ├── 15.bass3.csv           <-- Climate controller (sensoCOMFORT VRC 720 / MiPro Sense SRC 720)
    ├── 76.vwzio.csv           <-- Hydraulic module / tower (VWZ MEH / uniTOWER / HPIM 7 / GeniaSet)
    └── f6.netx3.csv           <-- Wireless room thermostat passive RF frames
```

#### Option A: Home Assistant eBUSd Add-on
1. Copy `ebusd-configuration/broadcast.csv` to:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/broadcast.csv`
2. Copy all 5 files inside `ebusd-configuration/vaillant/*.csv` to:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/vaillant/`
3. Configure your eBUSd Add-on startup parameters to load the local CSVs, enable JSON MQTT output, and allow write commands:
   ```text
   --configpath=/config/ebusd-configuration/en --scanconfig --accesslevel=* --mqttjson --mqtttopic=ebusd/%circuit/%name --mqttvar=filter-direction=r|u|^w
   ```
   > **What does each parameter do?**
   > - `--configpath=/config/ebusd-configuration/en`: Loads the optimized CSV files from this repository instead of outdated defaults fetched online.
   > - `--scanconfig`: Automatically probes the eBUS upon startup and binds circuits (`08`, `15`, `76`, `04`) to their respective CSV definitions.
   > - `--accesslevel=*`: Mandatory to allow reading and writing installer-level parameters (heating curves, bivalence points, limits).
   > - `--mqttjson`: Publishes messages in rich JSON format (`{"value": ...}`), required by the integration coordinator.
   > - `--mqtttopic=ebusd/%circuit/%name`: Structures MQTT topics per circuit and message without splitting into individual fields.
   > - `--mqttvar=filter-direction=r|u|^w`: **Mandatory to enable write operations.** The eBUSd Add-on includes `mqtt-hassio.cfg` by default with `filter-direction = r|u` (which blocks write commands to the bus). Adding this argument overrides that restriction and explicitly permits writes (`^w`) for setpoints, cooling mode, and heating curves.
   > - *(Note: Flags like `--enablehex` are omitted as raw hex debugging is not needed by the integration. Similarly, `--pollinterval` is omitted so eBUSd adopts its standard default 5-second cycle (`--pollinterval=5`), which is the exact baseline calibrated for our CSV `r` read priorities).*
4. Restart the **eBUSd** add-on and verify in its log that circuits `08.hmux0`, `15.bass3`, and `76.vwzio` are loaded upon bus scan.

#### Option B: Standalone Linux / Docker `ebusd`
1. Copy `ebusd-configuration/broadcast.csv` to `/etc/ebusd/en/broadcast.csv` (or your mapped Docker volume).
2. Copy `ebusd-configuration/vaillant/*.csv` to `/etc/ebusd/en/vaillant/`.
3. Add to `/etc/default/ebusd` (`EBUSD_OPTS`) or your `docker-compose.yml` command:
   ```text
   --configpath=/etc/ebusd/en --scanconfig --accesslevel=* --mqttjson --mqtttopic=ebusd/%circuit/%name --mqttvar=filter-direction=r|u|^w --mqtthost=<BROKER_IP> --mqttport=1883 --mqttuser=<USER> --mqttpass=<PASS>
   ```
4. Restart `ebusd` (`sudo systemctl restart ebusd` or `docker compose restart ebusd`).

---

### Step 2: Install the Integration (HACS or Manual)

#### Method A: Install via HACS (Recommended)

Click the button below to open this repository directly inside HACS on your Home Assistant instance:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=R91g&repository=arotherm-genia-ebusd&category=integration)

Or add it manually in HACS:

1. Open **HACS** in your Home Assistant sidebar.
2. Click the **three-dot menu (`⋮`)** in the top-right corner and select **Custom repositories**.
3. Fill in the dialog:
   - **Repository:** `https://github.com/R91g/arotherm-genia-ebusd`
   - **Category / Type:** Select **Integration**.
4. Click **Add**.
5. Close the dialog, search for **aroTHERM & GeniaAir (eBUS)** in HACS, open it, and click **Download**.
6. **Restart Home Assistant** (**Settings → System → Restart**) so Python loads the new custom component.

#### Method B: Manual Installation

1. Download the latest release (or clone this repository).
2. Copy the `custom_components/arotherm_genia_ebusd` folder into your Home Assistant `/config/custom_components/` directory:
   ```text
   /config/custom_components/arotherm_genia_ebusd/
   ```
3. **Restart Home Assistant**.

---

### Step 3: Configure in Home Assistant

Setup is performed 100% through the Home Assistant graphical UI (no `configuration.yaml` edits required):

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=arotherm_genia_ebusd)

1. Go to **Settings → Devices & Services** (or click the My Home Assistant button above).
2. Click **+ Add Integration** in the bottom-right corner and search for **aroTHERM & GeniaAir (eBUS)**.
3. **Step 1 — MQTT & Manufacturer:**
   - **eBUSd MQTT topic prefix:** Default is `ebusd` (matching `--mqtttopic=ebusd/%circuit/%name`).
   - **Equipment manufacturer:** Choose **`Vaillant`** or **`Saunier Duval`**.
4. **Step 2 — Equipment Hardware Models:**
   - **Outdoor unit model (Heat Pump):** Filtered automatically for your chosen brand (e.g. `aroTHERM plus ES VWL 85/7.1 A 230V` or `GeniaAir Max ES 15`).
   - **Indoor hydraulic interface / module model:** Filtered for your brand (e.g. `VWZ MEH 97/7`, `uniTOWER VIH QW 190/7`, `HPIM 7 230V`, `GeniaSet FEW/FIW 200-7`).
   - **Wireless room thermostat (`04.netx3` radio receiver):** Enable if you have a wireless `sensoCOMFORT RF` / `MiPro Sense RF` room unit; disable for wired-only setups.
   - **Official cloud gateway (`MiGo Link` / `myVAILLANT connect` on eBUS `f1`):** Enable if an official internet gateway is connected to your eBUS (passive listening mode); disable if you have no cloud gateway (activates paced fallback `/get` polling).
5. Click **Submit**. Within ~60 seconds, the staggered initial hydration queue will populate all live registers across your 4 devices.

---

## Reconfiguration & Runtime Options

### Changing Hardware Models or Brand Later (`Reconfigure`)
Need to change the selected heat pump model, switch brand labels, or toggle the wireless thermostat / cloud gateway later?
- Go to **Settings → Devices & Services → aroTHERM & GeniaAir (eBUS)**, click the **three-dot menu (`⋮`)** next to the config entry, and select **Reconfigure**.
- All device titles and hardware specs update cleanly while preserving **100% of entity IDs and historical statistics**.

### Tuning Live Algorithms (`Configure`)
Click **Configure** on the integration card in **Settings → Devices & Services** to adjust runtime behavior on the fly without restarting Home Assistant:

| Option | Default | Range | Description |
| :--- | :---: | :---: | :--- |
| **Enable Smart Forced DHW Boost** (`force_dhw_boost`) | `True` | On / Off | Dynamically elevates `HwcTempDesired` to `T_current + Hysteresis + 1.5 °C` when `ΔT < Hysteresis` during one-time DHW Boost, restoring the original setpoint automatically afterward. |
| **Automatically open Cooling Lock 1** (`auto_cooling_lock_bypass`) | `True` | On / Off | Automatically sets `CoolingStartDate = 01;01;26` and `CoolingEndDate = 01;01;99` when switching Zone 1 Climate to `Cool`, and locks back to `01;01;19` in `Heat` / `Off`. |
| **Fallback `/get` polling interval** (`fallback_poll_interval`) | `300 s` | `60` – `3600 s` | Interval for gentle active `/get` polling of core registers. **Only active when the official cloud gateway (`f1`) option is disabled.** |

---

## Custom Actions (Services)

The integration registers two custom actions under the `arotherm_genia_ebusd` domain, available in **Developer Tools → Actions** and Home Assistant Automations / Scripts.

### 1. `arotherm_genia_ebusd.set_weekly_timer`

[![Open your Home Assistant instance and show your service developer tools.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.set_weekly_timer)

Modifies native `b5 55` weekly time programs directly inside the `sensoCOMFORT` / `MiPro Sense` (`15.bass3`) controller, with automatic `600 ms` bus pacing across multi-day writes.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `circuit_type` | Yes | `heating`, `dhw`, `cooling`, `circulation` | Target weekly schedule (`Z1Timer`, `HwcTimer`, `CoolingTimer`, or `CirculationTimer`). |
| `day` | Yes | `Monday`..`Sunday`, `Weekdays`, `All` | Single day, Monday–Friday (`Weekdays`), or Monday–Sunday (`All`). |
| `slot` | No | `1`, `2`, `3` *(default: `1`)* | Daily time window slot (`1` to `3`). |
| `start_time` | Yes | `"HH:MM"` *(e.g. `"13:00"`)* | Window start time (24h format, 10-minute controller resolution). |
| `end_time` | Yes | `"HH:MM"` *(e.g. `"15:30"`)* | Window end time (24h format). |

**Automation Example — Align DHW schedule with peak solar PV hours every day:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: All
  slot: 1
  start_time: "13:00"
  end_time: "15:30"
```

### 2. `arotherm_genia_ebusd.force_dhw_boost`

[![Open your Home Assistant instance and show your service developer tools.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.force_dhw_boost)

Triggers an immediate one-time DHW cylinder charge (`HwcSFMode = load`) using the Smart Forced Boost hysteresis bypass, optionally specifying a custom temporary boost temperature for that cycle (ideal for solar PV surplus diverters).

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `boost_temp` | No | `40.0` – `68.0` *(°C)* | Optional temporary setpoint override for this single boost cycle (e.g. `60.0 °C` for solar PV surplus). If omitted, automatically applies `T_current + Hysteresis + 1.5 °C`. |

**Automation Example — Heat DHW tank to 60 °C when solar PV export exceeds 2.5 kW:**
```yaml
action: arotherm_genia_ebusd.force_dhw_boost
data:
  boost_temp: 60.0
```

### 3. `arotherm_genia_ebusd.set_holiday_mode`
Activates the Away / Holiday Mode (`PRESET_AWAY`) on the `MiPro Sense` controller, suspending DHW heating and reducing space heating to the selected setback temperature for a specific or open-ended timeframe.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `5.0` – `24.0` *(°C)* | Setback room temperature during absence (default: `12.0 °C`). |
| `start_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Absence start date (default: today). |
| `start_time` | No | `HH:MM` | Absence start time (default: current time). |
| `end_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Absence return date. If omitted, mode stays active indefinitely until cancelled. |
| `end_time` | No | `HH:MM` | Absence return time (default: `23:59`). |

**Automation Example — Depart on holiday until November 10th with 12 °C frost protection:**
```yaml
action: arotherm_genia_ebusd.set_holiday_mode
data:
  temperature: 12.0
  end_date: "2026-11-10"
  end_time: "18:00"
```

### 4. `arotherm_genia_ebusd.cancel_holiday_mode`
Immediately terminates the Away / Holiday Mode on `15.bass3` and restores automatic heating and DHW operation. No parameters required.

```yaml
action: arotherm_genia_ebusd.cancel_holiday_mode
```

---

## Home Assistant Energy Dashboard Setup

The integration exposes sub-kWh (`Wh`, IEEE 754 `EXP`) cumulative `TOTAL_INCREASING` energy sensors combining the outdoor heat pump (`08.hmux0`) and the indoor hydraulic module (`76.vwzio`), structured specifically for Home Assistant's **Individual Devices** energy hierarchy (with parent/child nesting so `Parent == Heating + DHW + Cooling` with zero double-counting):

1. Open **Settings → Dashboards → Energy → Individual devices** and click **Add device**.
2. **Add the Parent (Total Heat Pump) Sensor:**
   - Select **`Total System Electrical Energy`** (`calculated_system_total_energy`, in `Wh`, on the **Outdoor Unit** device).
   - Give it a friendly name (e.g. `Heat Pump (Total)`).
3. **Add the 3 Nested Child Sensors** (marking **`Included in`** → `Total System Electrical Energy` on each one):
   - **Heating:** `Total Heating Electrical Energy` (`calculated_heating_total_energy`, in `Wh`, on the Outdoor Unit device).
   - **Domestic Hot Water (DHW):** `Total DHW Electrical Energy` (`calculated_dhw_total_energy`, in `Wh`, on the Outdoor Unit device).
   - **Cooling:** `Total Cooling Electrical Energy` (`energy_electric_cool`, in `Wh`, on the Outdoor Unit device).

Home Assistant automatically calculates hourly, daily, monthly, and yearly deltas from these `Wh`-resolution hardware counters and displays an expandable `>` breakdown of **Heating vs. DHW vs. Cooling** electricity consumption inside your Energy Dashboard and Sankey chart without counting a single watt-hour twice. *(Component-level `08.hmux0` vs `76.vwzio` counters remain available under Diagnostic sensors if you ever wish to inspect compressor vs. hydraulic module consumption separately).*

---

## Diagnostics, Troubleshooting & FAQ

### Downloading Sanitized Diagnostics
If you open a bug report or want to inspect the raw cached JSON payloads from `ebusd`, go to **Settings → Devices & Services → aroTHERM & GeniaAir (eBUS) → `⋮` → Download diagnostics**. Sensitive MQTT topic details are automatically redacted.

### Frequently Asked Questions

<details>
<summary><b>1. Why do some entities show <code>Unknown</code> for the first 30–60 seconds after restarting Home Assistant?</b></summary>

This is completely normal and by design. To protect the 2400-baud physical eBUS from collision storms, the coordinator waits `5.0 s` for retained MQTT messages and then queries missing registers one by one every `0.8 s`. All active sensors populate automatically within ~1 minute.
</details>

<details>
<summary><b>2. I switched Zone 1 Climate to <code>Cool</code>, why does <code>Cooling Release Status (Hardware Lock 1)</code> still show Locked?</b></summary>

The integration automatically opens the calendar dates (`01;01;26` to `01;01;99`) and sets `Z1OpModeCooling = day`. However, the physical `CoolingReleaseStatus` register in `15.bass3` firmware **only unlocks when BOTH calendar dates are open AND the outdoor temperature exceeds the controller's hardware cooling threshold (typically ≥ 15 °C)**. Below that outdoor temperature, the heat pump firmware blocks cooling in hardware for compressor protection.
</details>

<details>
<summary><b>3. How can I verify that <code>ebusd</code> is publishing JSON messages properly to MQTT?</b></summary>

Subscribe to your MQTT broker using `mosquitto_sub` (or **Settings → Devices & Services → MQTT → Configure → Listen to a topic** in Home Assistant) on `ebusd/#`:
```bash
mosquitto_sub -h <MQTT_BROKER_IP> -u <USER> -P <PASS> -t "ebusd/#" -v
```
You should see JSON-formatted payloads (e.g. `ebusd/hmux0/RunDataFlowTemp {"value": {"value": 34.25}}`). If you see plain numbers instead of JSON objects, add `--mqttjson` to your `ebusd` startup flags and restart `ebusd`.
</details>

<details>
<summary><b>4. Why is <code>Global System Off (Installer)</code> disabled by default?</b></summary>

Writing `yes` to `15.bass3/GlobalSystemOff` puts the entire aerothermal installation (including DHW and frost routines depending on firmware) into installer standby. It is disabled by default in the Home Assistant entity registry to prevent accidental voice-assistant or dashboard toggles; advanced users can enable it manually from the Climate Controller device page.
</details>

---

## Technical Reference & Reverse Engineering

A detailed technical breakdown of the reverse-engineered eBUS protocol is documented in:  
👉 **[eBUS Protocol Technical Reference (English)](docs/technical_reference.md)** | **[(Versión en Español)](docs/technical_reference_es.md)**

Key topics covered in the reference:
- **eBUS Topology & Address Mapping:** Full breakdown of master/slave pairings (`03/08`, `10/15`, `71/76`, `f1/f6`).
- **High-Precision Energy Telemetry (`b5 16`):** The lifetime cumulative energy matrix (`Hc`, `Hwc`, `Cool` for electrical, thermal, and environmental yields) and instantaneous power draw (`PowerStatus` in Watts).
- **Compressor Dynamics:** Empirical proof of the `/16` divisor for `0x38` modulation data type and the $0.8\%$ agreement on the `0D5E` water-side heat meter.
- **Weekly Schedule Programming (`b5 55`):** 3-slot daily multi-timer structure and the `=FFFF` padding requirements.
- **Hardware Locks & Safety Latches:** The seasonal cooling double-lock mechanism, the `HwcSFMode = load` latch behavior, and quick-veto overrides.
- **Probe Standardization:** Using `tempv` with 4-byte padding (`IGN:4`) to prevent invalid sensor states on absent physical probes.
- **2400-Baud Bus Management:** Multi-tier polling strategy and software write locks to prevent bus collision storms.

---

## Development & Testing

This repository includes an offline unit test suite (requiring zero live Home Assistant runtime dependencies) and GitHub Actions workflows for **Hassfest**, **HACS Validation**, and **Ruff** linting:

```bash
# Run all 39 unit tests (thermodynamics, config flow, unique_id registry, schema parity)
python -m unittest discover tests -v

# Run Ruff linter & formatting checks
ruff check .
ruff format --check .
```

---

## License & Disclaimer

Distributed under the **[MIT License](LICENSE)** — Copyright (c) 2026 [@R91g](https://github.com/R91g).

This is an independent open-source community project and is **not** affiliated with, endorsed by, or supported by **Vaillant GmbH** or **Saunier Duval**. Use at your own responsibility; modifying installer-level hydraulic or bivalence parameters should only be performed if you understand your heating system design.
