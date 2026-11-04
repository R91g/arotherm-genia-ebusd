# Changelog

All notable changes to **aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.4] - Unreleased

> [!IMPORTANT]
> **Action Required:** Please update `ebusd-configuration/vaillant/08.hmux0.csv` in your `ebusd` configuration folder and restart `ebusd` to fix the `StateCompressor` `D2C` data type, enable the real-time vortex water flow sensor (`RunDataFlowRate` `540200090b`), and apply the optimized bus polling priorities.

### Fixed
- **`StateCompressor` `D2C` Data Type Fix (`08.hmux0.csv` — [#2](https://github.com/R91g/arotherm-genia-ebusd/issues/2)):**
  - Replaced invalid `DATA2c` type token with the standard eBUSd type `D2C` in `StateCompressor` (`b511,00` in `ebusd-configuration/vaillant/08.hmux0.csv:32`), resolving the `[main error] error readingconfigfiles ... vaillant/08.hmux0.csv: ERR: invalid part type in line 32` error on `ebusd` startup.
  - Added automated schema test `test_ebusd_csv_field_types` in `tests/test_schema_integrity.py` to validate every field data type across all `.csv` files against official eBUSd type specifications.
- **Real-Time Primary Circuit Volumetric Water Flow Sensor (`RunDataFlowRate` `540200090b`):**
  - Updated `RunDataFlowRate` (`ebusd-configuration/vaillant/08.hmux0.csv:53`) from the static nominal/design flow parameter `540200680b` (which permanently reported `900 l/h`) to the live primary circuit vortex flow sensor register `b509 540200090b` (`flow_rate`, `UIN`, `l/h`), reporting `0 l/h` in standby and `850–2,500+ l/h` dynamically during heating, cooling, and DHW operation.
  - Extended the `outdated_hmux0_csv` Home Assistant Repair check to automatically detect pre-v1.2.4 `RunDataFlowRate` payloads (via the legacy `value` JSON key vs `flow_rate`, independent of the nominal flow number) and clear the warning once the v1.2.4+ `08.hmux0.csv` (`flow_rate` or `RunDataNominalFlowRate`) is loaded.
  - Retained `540200680b` as a passive (`u`) definition (`RunDataNominalFlowRate`) so `ebusd` continues decoding passive gateway reads without logging unknown telegrams.
- **HACS & Home Assistant Hassfest CI Validation:**
  - Restored root `LICENSE` to standard MIT text for GitHub SPDX license detection while documenting `ebusd-configuration/` GPL-3.0 attribution in `ebusd-configuration/LICENSE.md`.
  - Removed single quotes around the `{mqtt_prefix}` placeholder in `strings.json`, `translations/en.json`, and `translations/es.json` to comply with Hassfest translation placeholder checks.

### Changed
- **Empirical eBUS Polling Optimization (`08.hmux0.csv`):**
  - Audited 1.26M bus telegrams (`telegrams.db`) to optimize active `ebusd` polling (`0x31`) alongside passive master traffic from `MiPro Sense` (`0x10`) and `MiGo Link` (`0xf1`):
    - Kept active polling (`r1..r9`) on registers never queried passively (`RunDataElectricPowerConsumption` `r1`, `RunDataFlowTemp` `r2`, `RunDataReturnTemp` `r2`, `RunDataHighPressure` `r3`, and refrigerant temperatures `r9`) and configured `RunDataFlowRate` (`540200090b`) as `r2` (~3.5 min refresh) for accurate live thermal power and COP calculation.
    - Reverted `HMUStatusCode` (`b503 0003`, passively queried every 2.5 min by `0xf1`), `RunDataCompressorSpeed` (`5402000d0a`, every 9.8 min by `0xf1`), `RunDataBuildingCPumpPower` (`540200c509`, every 9.8 min by `0xf1`), and `RunDataFan1Speed` (`540200470a`, every 60 min by `0xf1`) to passive `u`, reducing multi-master bus collisions while maintaining active `/get` polling for standalone installations via `has_migo_link: false` and startup hydration (`ESSENTIAL_HYDRATION_MESSAGES`).

---

## [1.2.3] - 2026-11-03

> [!IMPORTANT]
> **Action Recommended:** Please update `ebusd-configuration/vaillant/08.hmux0.csv` in your `ebusd` configuration folder and restart `ebusd` to enable active `r2`/`r3` polling (`RunDataCompressorSpeed`, `RunDataFan1Speed`, `RunDataFlowRate`, `RunDataBuildingCPumpPower`, `HMUStatusCode`) and the corrected `StateCompressor` field definitions. Home Assistant will automatically display a **Repairs** notice until the updated `08.hmux0.csv` is loaded.

### Added
- **Automated Home Assistant Repairs for eBUSd & MQTT Diagnostics (`issue_registry`):**
  - `outdated_hmux0_csv`: Passively inspects incoming `ebusd/hmux0/StateCompressor` MQTT JSON keys (`comp_speed` vs `flow_temp`), raising a native Home Assistant Repair warning when an older `08.hmux0.csv` is detected and clearing it automatically in real time once `ebusd` reloads the v1.2.3+ file.
  - `missing_custom_csv`: Automatically raises a Home Assistant Repair warning if `ebusd` has active bus signal (`global/signal = true`) or publishes default `ebusd.eu` messages (`WaterThroughput`, `CurrentConsumedPower`) without loading the custom `08.hmux0.csv` definitions, clearing itself immediately once custom telemetry arrives.
  - `no_ebusd_mqtt_traffic`: Raises a Repair warning after initial hydration if zero MQTT messages have arrived on `<mqtt_prefix>/#` (wrong MQTT topic prefix or `ebusd` disconnected from broker), clearing itself automatically on the first message.
  - `mqttjson_not_enabled`: Raises a Repair warning if multi-field telemetry arrives as semicolon-separated plain text instead of JSON objects (missing `--mqttjson` startup argument in `ebusd`), clearing itself once JSON payloads arrive.

### Fixed
- **9-Byte `StateCompressor` (`b5 11 00`) Decoding, Compressor State & Modulation Fix:**
  - Fixed `binary_sensor.compressor_active` (`Compressor running`) remaining permanently `On` in standby because `StateCompressor` bytes `0..1` (`comp_speed` in earlier CSVs) actually encode `flow_temp` in $1/16\ ^\circ\text{C}$ (`D2C`).
  - Fixed `sensor.compressor_modulation` (`Compressor modulation`) staying stuck at `4.0%` during full-power heating and jumping to `31.0%` during pump overrun because byte `4` encodes a mode/valve bitmask (`0` standby, `4` heating, `24` DHW, `31` overrun, `104` cooling), whereas **true compressor modulation (`0–102%`)** resides in byte `3` and is mirrored in byte `8` (4th byte of `state_bytes`).
  - Implemented backward-compatible `state_bytes` decoding in Python (`_check_compressor_active` reading byte `5`: `0x09` = active, `0x00`/`0x08` = off; `_get_compressor_modulation` reading byte `8` with fallback to `modulation`), ensuring accurate state and modulation even before updating `08.hmux0.csv`.
  - Removed redundant `compressor_speed_rpm` entity (and added automatic Entity Registry cleanup in `DEPRECATED_UNIQUE_ID_SUFFIXES`), standardizing on the true rotational speed sensor `compressor_speed_rps` (`RunDataCompressorSpeed`, `r/s`).
- **Missing MDI Icons Fixed (`icons.json`):**
  - Replaced non-existent `mdi:snowflake-clock` on `number.z1_cooling_temp_time_controlled` with valid `mdi:snowflake-thermometer`, and `mdi:pump-clock` on `*_overrun` states with valid `mdi:pump` (validated all 71 unique icon names against the official `@mdi/svg` catalog).

### Changed
- **Active `r2`/`r3` Telemetry Polling in `08.hmux0.csv`:**
  - Updated `StateCompressor` (`b511,00`) field layout in `08.hmux0.csv` (`flow_temp`, `modulation` at byte 3, `mode_flags` at byte 4, `state_bytes`).
  - Promoted `RunDataCompressorSpeed`, `RunDataFlowRate`, and `HMUStatusCode` from passive `u` to active `r2`, and `RunDataFan1Speed` and `RunDataBuildingCPumpPower` to `r3` (plus added them to `ESSENTIAL_HYDRATION_MESSAGES`), ensuring 1–3 minute refresh intervals instead of waiting 10–60 minutes for cloud gateway (`f1`) sweeps.
- **Cleanup:** Removed unused `ebusd-configuration/mqtt-hassio.cfg.default` reference file.

---

## [1.2.2] - 2026-11-02

### Added
- **Native Vaillant sensoCOMFORT (VRC 720) Dual-Circuit Architecture (`basv3`):**
  - Added twin configuration template `ebusd-configuration/vaillant/15.basv3.csv` alongside `15.bass3.csv`, enabling out-of-the-box recognition by eBUSd for Vaillant sensoCOMFORT systems reporting eBUS device ID `BASV3`.
  - Implemented bidirectional controller circuit aliasing (`bass3` <-> `basv3`) in the coordinator. Home Assistant entities seamlessly subscribe and publish without needing code branching across individual entity platforms.
  - Added passive controller circuit auto-detection from eBUS address `15` scan messages (`ID=BASV3` dynamically selects `basv3`; `ID=BASS3` selects `bass3`).
  - Added dynamic routing for parameter write commands (`/set`) and active telemetry requests (`/get`), targeting the system's active controller circuit while applying instant optimistic UI updates across both circuits.
  - Comprehensive unit test suite coverage (`test_controller_circuit_aliasing_bass3_and_basv3` and `test_code_quality`) ensuring full linting, formatting, and behavioral compliance.
  - Closes Issue #1 (reported by `@john-cooper-lumera`).

## [1.2.1] - 2026-11-01

### Added
- **Declarative Dynamic Icons (`icons.json`):**
  - Fully implemented Home Assistant icon translation schema via `icons.json` replacing hardcoded icons with dynamic, state-reactive Material Design Icons.
  - `water_heater.dhw_water_heater`: Dynamic icon states for idle, eco, performance, and boost override (`mdi:water-boiler-off`, `mdi:water-boiler`, `mdi:water-boiler-alert`).
  - `climate.zone_1_climate`: Responsive HVAC mode icons for heating, cooling, and auto (`mdi:radiator`, `mdi:snowflake`, `mdi:thermostat-auto`, `mdi:thermostat-box`).
  - `select`: Dynamic icons for zone operating modes (`mdi:calendar-clock`, `mdi:white-balance-sunny`, `mdi:weather-night`, `mdi:power-off`).
  - `switch`: Reactive icons for DHW boost (`mdi:lightning-bolt`), cooling authorization (`mdi:snowflake-check`), and holiday mode (`mdi:bag-suitcase`).
  - `binary_sensor`: Real-time state icons for compressor operation (`mdi:heat-pump`), circulating pump (`mdi:pump`), and defrost cycles (`mdi:snowflake-melt`).
  - `sensor.hmu_status_code`: Comprehensive state mapping for over 50 Live Monitor status codes (standby, pre-run, modulation, overrun, deicing, backup heaters, and inverter/fan faults).
  - `services`: Native UI action icons for `set_weekly_timer`, `force_dhw_boost`, `set_holiday_mode`, and `cancel_holiday_mode`.
- **Comprehensive eBUS Protocol Reverse Engineering Technical Reference:**
  - Published exhaustive bilingual technical reference (`docs/technical_reference.md` and `docs/technical_reference_es.md`) with responsive vector SVG architecture flowcharts.
  - Documents 2400-baud physical layer, master/slave addressing, telemetry timing cycles, enthalpy heat metering (`0D5E`), compressor modulation divisor (`/16`), cooling double-lock safety envelopes, weekly timer format (`b5 55`), and firmware latch behavior (`HwcSFMode = load`).
- **Automated Schema Integrity Unit Tests:**
  - Expanded test suite to 39 unit tests with automated MDI icon schema validation and parity checks against `services.yaml` and `strings.json`.

### Changed
- Removed redundant legacy `_attr_icon` definitions across `switch.py` and `datetime.py` in favor of declarative `icons.json`.

---

## [1.2.0] - 2026-11-01

### Added
- **Passive Hardware Detection & Serial Numbers (eBUSd Scan):**
  - Zero-overhead passive listening to `ebusd/scan.*` and `ebusd/Scan.*/#` without active bus polling.
  - Automatic extraction and assembly of 28-character hardware serial numbers (`Scan.<zz>/Id`) for Outdoor Unit, Hydraulic Interface, Climate Controller, and Wireless Thermostat.
  - Dynamic detection of firmware `SW` and hardware `HW` versions (supporting both CSV semicolon-delimited strings and JSON payloads).
  - Real-time Device Registry propagation via `dr.async_update_device` and `DeviceInfo`.
  - Robust fallback defaults (`0407`/`0504`, `0708`/`4304`, `0500`/`0504`, `0129`/`0404`) ensuring metadata is available even before bus scan finishes.
- **Home Assistant Energy Dashboard Native Integration:**
  - Direct integration of verified 32-bit IEEE 754 float (`EXP`) registers in `Wh` with `total_increasing` state class:
    - Heating Electrical & Thermal Energy (`PrEnergyElectricHc`, `PrEnergyThermalHc`).
    - Domestic Hot Water Electrical & Thermal Energy (`PrEnergyElectricHwc`, `PrEnergyThermalHwc`).
    - Cooling Electrical & Thermal Energy (`PrEnergyElectricCool`, `PrEnergyThermalCool`).
    - Monthly mode energy yield tracking (`PrEnergySumHcThisMonth`, `PrEnergySumHwcThisMonth`, `PrEnergySumCoolThisMonth`).
- **Thermodynamic Performance Metrics:**
  - Real Historical Heating SCOP (`PrEnergyThermalHc / PrEnergyElectricHc`).
  - Real Historical DHW COP (`PrEnergyThermalHwc / PrEnergyElectricHwc`).
  - Real Historical Cooling EER (`PrEnergyThermalCool / PrEnergyElectricCool`).
  - Global Historical System Efficiency (SCOP Global: total thermal energy / total electrical energy).
- **Device Registry Modernization:**
  - Full compliance with Home Assistant 2026/2027 Device Registry architecture: migrated deprecated `via_device` parameter to `via_device_id`.
  - Pre-registration of parent Outdoor Unit device during `async_setup_entry` guaranteeing child devices link into topology seamlessly without deprecation warnings.

### Changed
- **Paced Hydration Queue Pruning:**
  - Reduced essential hydration queue strictly to 54 active-read (`r`/`r9`) messages, eliminating `ERR: invalid position` errors on passive eBUS registers.
  - Retained strict 2400-baud half-duplex CSMA/CD delay pacing to prevent bus arbitration storms with wall units (sensoCOMFORT / MiPro Sense).
- **Automated Migration of Legacy Virtual Entities:**
  - Integrated `_async_cleanup_deprecated_entities` to automatically purge deprecated virtual COP unique IDs from earlier versions upon startup.

---

## [1.1.0] - 2026-10-30

### Added
- **DateTime Platform (8th native platform):**
  - `datetime.holiday_start_datetime`: Interactive selector for Away Mode start date and time.
  - `datetime.holiday_end_datetime`: Interactive selector for Away Mode end date and time.
  - `datetime.cooling_start_datetime`: Interactive selector for Manual Cooling season start date and time.
  - `datetime.cooling_end_datetime`: Interactive selector for Manual Cooling season end date and time.
- **Away / Holiday Mode (`Holiday Mode`):**
  - `switch.holiday_mode`: Bidirectional toggle switch for system-wide Away Mode.
  - `climate` Preset Support: Added native `away` preset to Zone 1 climate entity with dynamic fallback to `HolidayTemp` (15.0 °C by default). Changing presets automatically triggers safe eBUS cancellation.
  - `number.holiday_temp`: Touch-safe numeric box control for away temperature setpoint (5.0 °C – 24.0 °C).
  - `sensor.holiday_duration_remaining`: Live countdown sensor returning `Inactivo` when off, `Final abierto` when open-ended (year 99), and positive day counts (`N d`) when active.
  - Actions / Services: `arotherm_genia_ebusd.set_holiday_mode` and `arotherm_genia_ebusd.cancel_holiday_mode`.
- **Dual Cooling Season Control:**
  - Automated Open-Ended Mode: Switching to `Cool` or turning on the cooling switch opens Lock 1 indefinitely (`01;01;26` to `01;01;99`).
  - Calendar Window Mode: Setting start/end dates via the new `datetime` entities programs the exact timeframe on the controller without open-ended override.
  - `sensor.cooling_duration_remaining`: Live countdown sensor returning `Inactivo` when off, `Final abierto` when open-ended, and positive day counts (`N d`) during active scheduled windows.
- **Protocol eBUS Definitions (`15.bass3.csv`):**
  - Full read/write support for `HolidayStartDate`, `HolidayStartTime`, `HolidayEndDate`, `HolidayEndTime`, `HolidayTemp`, and `HolidayCancel`.
- **Release Automation:**
  - Added `.github/workflows/release.yml` for automated HACS distribution packaging (`arotherm_genia_ebusd.zip`).

---

## [1.0.0] - 2026-10-29

### Added
- **Unified Multi-Brand Support:** Native support for both **Vaillant** (`aroTHERM plus ES` / `aroTHERM plus`) and **Saunier Duval** (`GeniaAir Max ES` / `GeniaAir Iso ES` / `GeniaAir Max Legacy`) air-to-water heat pumps.
- **Full Controller Compatibility:** Complete integration with **`sensoCOMFORT` (`VRC 720/2`, `VRC 720/3`)** and **`MiPro Sense` (`SRC 720/2`, `SRC 720/3`)** system controllers over local eBUS via `ebusd`.
- **4 Logical Devices in Home Assistant:**
  - Outdoor Unit (`08.hmux0`)
  - Climate Controller (`15.bass3`)
  - Indoor Hydraulic Module / Interface (`76.vwzio`)
  - Wireless Room Thermostat (`04.netx3` / `f6.netx3` / `broadcast`)
- **134 Native Entities across 7 Platforms:**
  - `climate` (1): Zone 1 thermostat supporting Heating, Cooling, and Auto modes with seasonal setpoint memory.
  - `water_heater` (1): Domestic Hot Water cylinder controller with operation modes (`off`, `eco`/schedule, `performance`/24h, `boost`).
  - `sensor` (90): Telemetry, IEEE 754 (`EXP`) energy counters, operational statistics, and 4 weekly schedule summaries (`b5 55`).
  - `binary_sensor` (8): Compressor state, primary pump, defrost cycle, heating demand, hardware cooling release, broadcast cooling, and eBUS bus signal.
  - `number` (24): Configuration parameters strictly in `NumberMode.BOX` to prevent accidental mobile touch drags.
  - `select` (5): Heating/cooling operating modes, DHW mode, night setback lowering mode, and room temperature modulation feedback.
  - `switch` (5): DHW Boost, Cooling Season Authorization (`Lock 1`), Adaptive Heat Curve, DHW Parallel Loading, and Global System Off.
- **Thermodynamic & Efficiency Engine:**
  - Real-time Primary Delta T ($\Delta T$).
  - Instantaneous Thermal Power ($P = \dot{V} \times \Delta T \times 1.163\text{ W}$) with zero-clamping during defrost and standby.
  - Live Instantaneous COP / EER.
  - Daily Real COP, Monthly Real COP, and Historical Total SCOP.
  - Combined Total Historical Electrical Energy sensor for Home Assistant Energy Dashboard.
- **Zone 1 Climate Double-Lock & Anti-Sentinel Protection:**
  - Automatic filtering of firmware sentinel values (`5.0 °C` when heating is off, `99.0 °C` when cooling is off).
  - Transparent management of cooling **Lock 1** (`CoolingStartDate` = `01;01;26`, `CoolingEndDate` = `01;01;99` vs. `01;01;19`) and **Lock 2** (`Z1OpModeCooling`).
- **Smart Forced DHW Boost (Dynamic Hysteresis Bypass):**
  - Overcomes the factory `5.0 K` hysteresis (`CylinderChargeHyst`) when the cylinder is warm ($\Delta T < 5.0\text{ K}$) by automatically applying $T_{\text{actual}} + \text{Hysteresis} + 1.5\ ^\circ\text{C}$ and restoring the original setpoint upon cycle completion or timeout.
- **2400-Baud Collision Safety & Paced Initial Hydration:**
  - Passive `u` frame listening when an official gateway (`myVAILLANT connect` / `MiGo Link` on `f1`) is present.
  - $5.0\text{ s}$ retained payload absorption + $0.8\text{ s}$ paced initial hydration queue for missing registers.
  - $0.3\text{ s}$–$0.6\text{ s}$ arbitration write pacing.
  - Fallback gentle polling loop when no official cloud gateway is connected.
- **Brand-Neutral Architecture & Live Reconfiguration:**
  - Every `unique_id` is hardware-derived (`{entry_id}_{circuit}_{message}_{field}`) without brand strings.
  - Reconfiguration flow (`Reconfigure`) updates manufacturer, outdoor/indoor models, or accessories without losing history or entity IDs.
- **Custom Services (Actions):**
  - `arotherm_genia_ebusd.set_weekly_timer`: Schedule weekly time slots (`heating`, `dhw`, `cooling`, `circulation`) with multi-day bus pacing.
  - `arotherm_genia_ebusd.force_dhw_boost`: Trigger immediate DHW boost with optional custom temperature override.
- **Local Brand Assets:**
  - Bundled `brand/icon.png`, `brand/icon@2x.png`, `brand/logo.png`, and `brand/logo@2x.png` with anti-aliased transparency for Home Assistant 2026.3+ native brand support.
- **Reverse-Engineered eBUSd CSV Files:**
  - Bundled custom CSV definitions in `ebusd-configuration/` for `08.hmux0`, `15.bass3`, `76.vwzio`, `04.netx3`, `f6.netx3`, and `broadcast.csv`.

