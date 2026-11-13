# Changelog

All notable changes to **aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - Unreleased

> [!IMPORTANT]
> **Action required when updating:**
> 1. Update **all** CSV files in your `ebusd` folder (`ebusd-configuration/vaillant/`): controller (`15.*`) and outdoor unit (`08.*`) definitions changed, then restart `ebusd`. Outdated files are flagged by the built-in Repair checks.
> 2. **If using the Home Assistant eBUSd Add-on ([LukasGrebe/ha-addons](https://github.com/LukasGrebe/ha-addons)):** Ensure **"Seed HA MQTT integration config"** is turned **OFF** (`seed_mqtt_cfg: false`) in the add-on configuration and `--mqttjson` is present in `commandline_options`. (This setting is exclusive to this add-on; standalone eBUSd or Docker setups are unaffected). A legacy seeded configuration queries 160+ registers every 16 minutes, saturating the eBUS and starving high-frequency telemetry. The integration now includes an automatic Repair issue (`ebusd_slow_polling_seed`) that warns you if power telemetry updates abnormally slowly.
> 3. **Home Assistant 2024.12.0 or newer is now required** (up from 2024.4.0).
> 4. The old `Z1DayTemp` setpoint entity is removed automatically; the cooling manual setpoint now lives in a new entity (`Z1CoolingManualTemp`). If your automations, scripts or dashboards referenced the old one, point them to the new entity.
> 5. `Z1MaxFlowTempDesired` was actually Zone 1 room humidity; it now appears as the "Zone 1 Room Humidity" sensor and as `current_humidity` on the climate entity.
> 6. Default device names migrate from Spanish to English automatically; any names you customized are preserved.

### Added
- **New hardware: CTLV2 / CTLV3 controllers (`sensoHOME` / `sensoCOMFORT` / `MiSet`) and Vaillant HMU00 (HW5103) / aroTHERM Split outdoor units.** New ebusd CSV templates (`15.ctlv2.csv`, `15.ctlv3.csv`, `08.hmu.HW5103.csv`) with automatic scan detection and circuit aliasing; Split water pressure, silent mode levels, compressor hours/starts fallbacks and native COP registers. Also added UK `aroTHERM pro 7.1` and `aroTHERM plus 8.1` models. Developed with the help of community testers and not yet validated on every model; please report any mismatch in GitHub issues.
- **Persistent overrides across restarts (Store):**
  - **Cooling Quick Veto:** Timed synthetic cooling veto for scheduled and manual cooling, stored in Home Assistant so active vetos resume after a restart and restore the previous operating mode and setpoint.
  - **Heating Quick Veto from Off:** Preserves and restores `Z1OpMode = "off"` upon veto expiration even if Home Assistant restarts mid-veto or if the eBUS daemon is offline.
  - **Smart Forced DHW Boost:** Preserves original `HwcTempDesired` across restarts, automatically restoring the setpoint upon charge completion or 60-minute timeout.
- **Quick veto controls.** Adjustable veto duration (0.5–12 h), heating and cooling boost deltas, and `quick_veto` / `cancel_quick_veto` actions.
- **Anti-legionella control.** Day selector, time entity and `set_legionella_protection` action across all controller CSVs.
- **Weekly schedules: 3 slots per day + silent mode.** Heating, cooling, DHW and circulation expand from 1 to 3 daily slots; new silent mode weekly schedule (with its own summary sensor); passive decoding of schedule writes made from the official app, without polling.
- **New telemetry sensors.** Refrigeration cycle (evaporation, condensation, superheat, subcooling and more), per-mode compressor hours and starts, hydraulic auxiliary heater statistics, active error sensors for the outdoor unit and the controller, and Zone 1 relative humidity.
- **100% explicit MDI icon coverage.** Added missing entity icons across all platforms in `icons.json` for full UI consistency without relying on fallback icons.
- **ebusd daemon health.** A daemon status binary sensor plus an optional advanced TCP connection (Options Flow) that reports daemon info, verifies loaded CSV files, detects devices missing CSV definitions, and adds reload-CSV and restart-scan buttons. Metrics that ebusd does not publish over MQTT stay disabled by default.
- **Slow eBUS telemetry repair issue (`ebusd_slow_polling_seed`):** Automatically detects if high-priority power telemetry (`RunDataElectricPowerConsumption`) updates abnormally slowly (≥ 5 minutes while eBUS is active), alerting users running the Home Assistant eBUSd Add-on ([LukasGrebe/ha-addons](https://github.com/LukasGrebe/ha-addons)) to disable the legacy `seed_mqtt_cfg` option that overloads the bus.
- **Diagnostic actions.** Symbolic `read_parameter` / `write_parameter`; `dump_mqtt_values` and `record_topic_changes` mask serial numbers and barcodes by default (still review the output before sharing it); `send_hex_command` is now behind an explicit opt-in switch.
- **German translation** and full EN/ES/DE parity across all 12 actions.
- **Restructured documentation:** shorter README plus modular English and Spanish guides under `docs/` (installation, configuration, hardware, services, troubleshooting).

### Changed
- **Faster live electric power:** moved to ebusd's highest polling priority (`r1`), with `PowerStatus` as fallback when the primary source goes stale and a 10-minute expiration to `unavailable` when updates stop.
- **Faster thermal telemetry:** flow temperature, return temperature and flow rate moved from the slowest to the second polling priority (`r2`), so thermal power and live COP refresh sooner.
- **Install from the HACS default catalog:** no custom repository URL needed anymore.
- **Limited background polling:** low-priority (`r9`) reads are restricted to registers the official gateway never queries, and unverified registers carry conservative names.
- **ebusd add-on setup docs updated:** Added explicit instructions for the Home Assistant eBUSd Add-on ([LukasGrebe/ha-addons](https://github.com/LukasGrebe/ha-addons)) regarding `seed_mqtt_cfg` and `--mqttjson` after a known configuration caused heavy polling and duplicate MQTT entities.
- Minimum supported Home Assistant version raised from 2024.4.0 to **2024.12.0**.

### Fixed
- **State persistence across Home Assistant restarts:** fixed elevated `HwcTempDesired` becoming permanent when restarting during a forced DHW boost, and fixed Zone 1 staying in `auto` instead of reverting to `off` when restarting during a heating quick veto started from off. Also fixed a startup race condition where `Z1Status` could cancel an active heating veto before `Z1SFMode` arrived. Restoration writes across DHW boost, heating quick veto, and cooling quick veto now preserve their persisted state and memory flags until the eBUS write confirms successfully, retrying automatically on transport failures.
- **Cooling quick veto cancellation consistency during preset changes:** fixed an issue where cancelling an active cooling quick veto during preset selection (`restore=False`) prematurely marked the veto as ended in memory while retaining the on-disk state on transport failures. In-memory state, expiration timers, and persistent storage are now preserved on offline bus conditions and write failures, re-arming expiration timers safely (`max(0.0, remaining)`) to guarantee natural expiration and preventing revived vetos from overriding subsequent user setpoints after a restart. Background restoration tasks also handle transport exceptions cleanly without unhandled task logs.
- **Dead references and CSV field cleanup:** removed obsolete `EnergyYieldPrecision` fallbacks, purged redundant `"value"` fallback in `HwcLegionellaTime`, and aligned `Status01` flow temperature with canonical CSV field `flow_temp`.
- **Heating and cooling setpoints decoupled:** register `2300` was mislabeled as `Z1DayTemp`; it is the cooling manual setpoint (`Z1CoolingManualTemp`), while heating uses `2200`. This fixes cases where changing the heating temperature wrote cooling setpoints and where Boost from cooling armed the heating quick veto.
- **Energy counters on HMU / Split units:** fixed the 65,535 kWh 16-bit overflow (now 32-bit) and restored cumulative energy, environmental yield and per-mode COP/EER on units without Monobloc EEPROM registers.
- **Weekly schedule writing hardened:** validates every day before writing anything, rejects overlaps and slots crossing midnight, serializes writes with a lock, and safely invalidates the cached schedule state if a write fails midway.
- **Climate behavior:** holiday/away mode now takes priority over cooling, `AUTO` picks the season dynamically, and the cooling ECO preset behaves symmetrically to heating.
- **Instantaneous power staleness:** prefers the primary power register while it is fresh (up to 3 minutes old), falls back to `PowerStatus` when stale, and expires power and live COP to `unavailable` after 10 minutes without updates instead of showing obsolete values.
- **Connection watchdog:** control entities go unavailable after 10 minutes without bus telemetry, while historical sensors stay available.
- **CSV compliance:** headers on line 1 for the ebusd 26.1 parser, byte-for-byte parity across controller CSVs, and incompatible queries filtered on HMU units.
- **Home Assistant 2026.8+ compatibility** in the device registry, and automatic migration of legacy Spanish device names.

---

## [1.2.4] - 2026-11-04

> [!IMPORTANT]
> **Action Required:** Please update `ebusd-configuration/vaillant/08.hmux0.csv`, `ebusd-configuration/vaillant/15.bass3.csv`, and `ebusd-configuration/vaillant/15.basv3.csv` in your `ebusd` configuration folder and restart `ebusd`. This release fixes the `StateCompressor` `D2C` data type, activates real-time primary circuit water flow tracking (`RunDataFlowRate` `540200090b`), maps Holiday Mode reading to Zone 1 registers, and enables active startup hydration for heating starts and cooling season parameters.

### Fixed
- **Code Quality, Privacy & Diagnostics Hardening:**
  - Added automatic redaction of sensitive device identifiers (`serial_number`, `serial`, `mac`) in `diagnostics.py` for both configuration entries and raw `bus_state` to safeguard user privacy when sharing diagnostics on GitHub.
  - Added explicit `strict=False` parameter to `zip()` layout unpacking in `coordinator.py` for enhanced payload parsing safety (`B905`).
  - Normalized ambiguous Unicode dash characters in `datetime.py` comments (`RUF003`).
- **`StateCompressor` `D2C` Data Type Fix (`08.hmux0.csv` — [#2](https://github.com/R91g/arotherm-genia-ebusd/issues/2)):**
  - Replaced invalid `DATA2c` type token with the standard eBUSd type `D2C` in `StateCompressor` (`b511,00` in `ebusd-configuration/vaillant/08.hmux0.csv:32`), resolving the `[main error] error readingconfigfiles ... vaillant/08.hmux0.csv: ERR: invalid part type in line 32` error on `ebusd` startup.
  - Added automated schema test `test_ebusd_csv_field_types` in `tests/test_schema_integrity.py` to validate every field data type across all `.csv` files against official eBUSd type specifications.
- **Real-Time Primary Circuit Volumetric Water Flow Sensor (`RunDataFlowRate` `540200090b`):**
  - Updated `RunDataFlowRate` (`ebusd-configuration/vaillant/08.hmux0.csv:53`) from the static nominal/design flow parameter `540200680b` (which permanently reported `900 l/h`) to the live primary circuit vortex flow sensor register `b509 540200090b` (`flow_rate`, `UIN`, `l/h`), reporting `0 l/h` in standby and `850–2,500+ l/h` dynamically during heating, cooling, and DHW operation.
  - Extended the `outdated_hmux0_csv` Home Assistant Repair check to automatically detect pre-v1.2.4 `RunDataFlowRate` payloads (via the legacy `value` JSON key vs `flow_rate`, independent of the nominal flow number) and clear the warning once the v1.2.4+ `08.hmux0.csv` (`flow_rate` or `RunDataNominalFlowRate`) is loaded.
  - Extended the `missing_custom_csv` Home Assistant Repair check to verify after startup hydration that all three core CSV circuits (`08.hmux0.csv`, `15.bass3.csv`/`15.basv3.csv`, and `76.vwzio.csv`) have loaded and reported telemetry, alerting the user if any CSV file failed to load or experienced an initial `scan config` timeout (`ERR: read timeout`) and clearing automatically once all three circuits respond.
  - Retained `540200680b` as a passive (`u`) definition (`RunDataNominalFlowRate`) so `ebusd` continues decoding passive gateway reads without logging unknown telegrams.
- **Holiday / Away Mode Read Registers (`15.bass3.csv` / `15.basv3.csv`) & Sentinel Handling (`datetime.py`):**
  - Added automated Home Assistant Repair check `outdated_controller_csv` to detect older versions of `vaillant/15.bass3.csv` or `vaillant/15.basv3.csv` (reporting legacy `Z1HolidayTemp` instead of Zone 1 mapped Holiday Mode registers), automatically clearing once the v1.2.4+ files are loaded in `ebusd`.
  - Mapped the read (`r`, poll priority 0) definitions of `HolidayTemp` (`020003000500`), `HolidayStartDate` (`020003000300`), `HolidayStartTime` (`020003002100`), `HolidayEndDate` (`020003000400`), and `HolidayEndTime` (`020003002000`) in `15.bass3.csv` and `15.basv3.csv` to the Zone 1 registers actively polled by MiGo Link (`0xf1` every hour and 3 seconds after any app change), while keeping the write (`w`) definitions on the global `02010000f200..f600` registers.
  - Implemented clean UI sentinel filtering in `datetime.py`: `SaunierGeniaHolidayStartDateTime` and `SaunierGeniaHolidayEndDateTime` return `None` (displaying as `Desconocido` / empty in Home Assistant) when the bus holds the inactive reset sentinel (`2015-01-01`), unless the user has set a preselected date buffer in the UI. Similarly, `SaunierGeniaCoolingStartDateTime` and `SaunierGeniaCoolingEndDateTime` return `None` when inactive (`2019-01-01`). Open-ended / indefinite periods (`2099-01-01`) and active dates remain cleanly visible.
  - Surfaced diagnostic start and end dates as structured state attributes on the `holiday_duration_remaining` and `cooling_duration_remaining` sensors, as well as on `switch.holiday_mode` and `switch.cooling_season`.
  - Changed `RunStatsHcStarts` (`540200c00b` in `08.hmux0.csv`) and `CoolingStartDate`/`CoolingEndDate` (`15.bass3.csv`/`15.basv3.csv`) from `u` to `r` (poll priority 0) and added them to `ESSENTIAL_HYDRATION_MESSAGES` (with `76.vwzio` fallback for `stats_hc_starts`) so they hydrate immediately on startup.
  - Removed 4 redundant raw date string sensors (`cooling_start_date`, `cooling_end_date`, `holiday_start_date`, `holiday_end_date`) and the unsupported legacy VRC700 `yield_total` (`020000003e00`) sensor (bringing the integration to 142 strongly typed entities: 92 sensors [88 telemetry/energy + 4 weekly schedules], 25 numbers, 8 binary sensors, 6 switches, 5 selects, 4 datetimes, 1 climate, 1 water heater), adding their unique IDs to `DEPRECATED_UNIQUE_ID_SUFFIXES` for automatic Entity Registry cleanup.
- **HACS & Home Assistant Hassfest CI Validation:**
  - Added `"categories": ["climate.heat_pumps_air_conditioning", "climate.thermostats_heating", "climate.water_heaters"]` to `manifest.json` to resolve the HACS validation warning.
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

