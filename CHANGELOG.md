# Changelog

All notable changes to **aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - Unreleased

> [!IMPORTANT]
> **Action Required:** Please update the configuration files in your `ebusd` folder (`ebusd-configuration/vaillant/`) and restart `ebusd`. This release introduces native support for **Vaillant HMU00 (HW=5103)** outdoor units and **CTLV2 / CTLV3 (sensoHOME / sensoCOMFORT / MiSet)** controllers, persistent **Cooling Quick Veto**, **Anti-Legionella protection**, fast **`r1;u` electric power polling**, 3 daily schedule intervals, eBUS diagnostic services, `ebusd` health sensors, and critical audit stability fixes.

### Added
- **Hardware: Vaillant HMU00 (HW5103) & aroTHERM Split Support:**
  - Added dedicated configuration template `ebusd-configuration/vaillant/08.hmu.HW5103.csv` with automatic circuit aliasing (`hmux0` <-> `hmu`/`hmu00`), Split water pressure (`FlowPressure`), silent mode levels, compressor hours/starts fallbacks (`CompressorHours`/`CompressorStarts`), native COP registers (`CopHc`, `CopHwc`, `CopCooling`), and legacy energy yield registers.
- **Hardware: sensoCOMFORT & sensoHOME Controllers (`CTLV2` & `CTLV3`):**
  - Added configuration templates `15.ctlv2.csv` and `15.ctlv3.csv` with automatic scan detection, bidirectional aliasing (`bass3`/`basv3` <-> `ctlv2`/`ctlv3`), and updated repair checks.
  - Added UK `aroTHERM pro 7.1` and `aroTHERM plus 8.1` models to the outdoor unit catalog.
- **Refrigeration Cycle, Per-Mode Compressor & Auxiliary Heater Diagnostics:**
  - Added refrigeration thermodynamics and compressor control sensors (`evaporation_temp`, `condensation_temp`, `condensate_temp`, `superheat`, synthetic `subcooling`, `energy_integral`, `compressor_flow_temp_desired`, and `heat_output_internal`).
  - Added per-mode compressor operating hours and starts (`stats_compressor_hc_hours`, `stats_compressor_hc_starts`, `stats_compressor_hwc_hours`, `stats_compressor_hwc_starts`, `stats_compressor_cool_hours`, `stats_compressor_cool_starts`) with cross-circuit `hmux0`/`hmu` fallbacks.
  - Added hydraulic auxiliary immersion heater telemetry and statistics on `76.vwzio` (`vwzio_heater_energy`, `vwzio_heater_flow_temp`, and heating/DHW operating hours and starts).
  - Added active error diagnostic sensors (`hmu_current_error` and `controller_current_error`) decoding `Currenterror` across outdoor units and climate controllers.
- **Zone 1 Relative Room Humidity (`Z1RoomHumidity`):**
  - Exposed Zone 1 relative humidity (`b524 020003002800`) both as `sensor.z1_room_humidity` (`%`) and directly as `current_humidity` on `SaunierGeniaZone1Climate`, with backward-compatible MQTT aliasing from legacy `Z1MaxFlowTempDesired`.
- **Weekly Schedule Multi-Slot Expansion (Slots 2 & 3) & Silent Mode Timer:**
  - Expanded all daily schedules across heating, cooling, DHW, and circulation from 1 to 3 time slots across all 4 controller CSV configurations.
  - Added Silent Mode weekly schedule support (`SilentTimer_*` on `b5 55` circuit `04`), including `circuit_type: silent` in `set_weekly_timer` and `sensor.silent_mode_weekly_schedule_summary`.
  - Added passive eavesdropping (`u`) for official MiGo Link app schedule writes, decoding time intervals and target temperatures in real time without polling.
- **Anti-Legionella Disinfection Schedule Control (`select`, `time` & Action):**
  - Added `HwcLegionellaDay` (defined with mandatory 2-byte `daysel3` / `UIN` encoding for CTLV2/CTLV3/BASS3 compatibility) and `HwcLegionellaTime` (`HTM`) across all 4 controller CSVs.
  - Added `select.hwc_legionella_day` (`off`, `monday`..`sunday`), new Home Assistant `Time` platform (`time.hwc_legionella_time`), and `arotherm_genia_ebusd.set_legionella_protection` service.
- **Quick Veto (Zone 1 Boost) Controls, Cooling Quick Veto & Persistent Recovery:**
  - Added `number.z1_quick_veto_duration` (`0.5–12.0 h`), `number.z1_quick_veto_boost_delta` (heating boost delta), `number.z1_cooling_quick_veto_boost_delta` (cooling boost delta), and dedicated `arotherm_genia_ebusd.quick_veto` / `arotherm_genia_ebusd.cancel_quick_veto` actions.
  - Implemented persistent synthetic **Cooling Quick Veto** for scheduled (`auto`) and manual cooling Boost (`PRESET_BOOST` or adjusting temperature in scheduled cooling), backed by Home Assistant `Store` so active timers resume across restarts and expired vetos automatically restore prior operating mode and manual setpoint once eBUS reconnects.
- **Controller & Hydraulic Telemetry Additions (`76.vwzio` & `15.*`):**
  - Added passive `StationState` (`b512 0f0613`: hydraulic pressure, primary flow rate, operational state byte) to `76.vwzio.csv`.
  - Added `MultiInputSetting` (`6a00` PV/cooling/circulation input mode), `CoolingOutsideTempThreshold` (`3800`), `DewPointMonitoring` (`0400`), `DewPointOffset` (`3a00`), and `OffsetOutsideTemp` (`2d00`) across all 4 controller CSVs.
- **Diagnostic eBUS Services (`read_parameter` & `write_parameter`):**
  - Added actions to read and write symbolic eBUS parameters via MQTT directly from Home Assistant Developer Tools or automations, with automatic circuit alias resolution (`08`, `15`, `outdoor`, `controller`).
- **Anonymized Dumps & Mode-Specific Community Test Fixtures:**
  - Added automatic serial number and barcode masking to `dump_mqtt_values` and `record_topic_changes` services for safe troubleshooting sharing.
  - Organized Saunier Duval GeniaAir Max community test fixtures by distinct operating modes (`saunier_geniaair_max_heating.json`, `saunier_geniaair_max_acs.json`, and `saunier_geniaair_max_standby.json`), verifying entity stability, primary hydraulic thermodynamics, and humidity sensors across real-world operational states.
- **Physical eBUS Health & Advanced TCP Daemon Diagnostics:**
  - Added `binary_sensor.ebusd_running` and 7 diagnostic sensors attached to the root outdoor unit (uptime, scan status, daemon version, arbitration latency, symbol rate, reconnects, active masters).
  - Disabled unreachable MQTT metrics (`symbol_rate`, `reconnects`, `masters`, `arbitration_latency`) by default in the entity registry (`entity_registry_enabled_default = False`) to prevent `Unknown` entities on pure MQTT setups.
  - Added optional **Advanced eBUSd TCP Connection** in integration Options Flow (`enable_ebusd_tcp`, `ebusd_tcp_host` default `127.0.0.1`, `ebusd_tcp_port` default `8888`), periodically querying `info` (and zero-bus-traffic CSV `find` verification) via non-blocking TCP socket to hydrate daemon health metrics and detect outdated CSV files cleanly.
  - Added `sensor.ebusd_missing_csv_devices` diagnostic sensor identifying scanned eBUS devices missing loaded CSV files, with full device inventory attributes (`missing_count`, `missing_devices`, `loaded_devices`, `total_scanned`).
  - Added action buttons `button.ebusd_reload_csv` (reloads CSV definitions on the daemon in real time) and `button.ebusd_restart_scan` (restarts bus device identification).
  - Synchronized entity registry state dynamically: toggling `enable_ebusd_tcp` automatically enables or disables TCP diagnostic entities and action buttons without manual registry intervention.
  - Protected `send_hex_command` behind an explicit security opt-in switch (`enable_send_hex`) in Options Flow, automatically defaulting `host` and `port` to configured integration settings.
- **Multilingual Support & Complete Translation Parity (EN, ES, DE):**
  - Added complete German (`de.json`) translation suite across all entity platforms, configuration and options flows, device classes, and actions.
  - Localized all 12 integration actions/services across `strings.json`, `translations/en.json`, `translations/es.json`, and `translations/de.json` with 100% key parity.
  - Migrated `services.yaml` base names and descriptions to standard English.
- **Release Security Gate in CI:**
  - Hardened GitHub release workflow to require unit tests (Python 3.12 & 3.13), Ruff linter/formatter, Pyright typing, Hassfest, and HACS validation before building and publishing release archives.

### Fixed
- **Legacy Spanish Device Registry Migration:**
  - Automatically migrates existing device entries in the Home Assistant Device Registry from legacy Spanish default names (`(Unidad Exterior)`, `(Regulador Climático)`, `(Interfaz Hidráulica)`, `(Termostato Inalámbrico)`) to standard English (`(Outdoor Unit)`, `(Climate Controller)`, `(Hydraulic Interface)`, `(Wireless Thermostat)`), preserving any custom user-assigned names (`name_by_user`).
- **Cumulative Energy, COP/SCOP & 65,535 kWh Overflow Fix on `HMU` / `HMU00` (`HW5103`) Units:**
  - Fixed 16-bit `UIN` integer overflow at 65,535 kWh in `08.hmu.csv` and `08.hmu.HW5103.csv` by migrating `YieldHc` and `TotalEnergyUsage` to 32-bit `ULG` counters.
  - Fixed cumulative electrical/thermal energy totals, environmental yield (`YieldHc`/`YieldHwc`), per-mode historical COP/EER (`CopHc`/`CopHwc`/`CopCooling` with `1 + Yield/PrEnergySum` fallback), and global system efficiency on `hmu`/`hmu00` units lacking Monobloc `b516` EEPROM registers.
  - Automatically disables the 3 Monobloc-exclusive outdoor per-mode electrical sensors (`energy_electric_hc_outdoor`, `energy_electric_hwc_outdoor`, `energy_electric_cool`) in the Entity Registry when an `hmu`/`hmu00` unit is detected, preserving manual user overrides.
- **Dynamic Instantaneous Electric Power Fallback & 10-Minute Expiration Watchdog:**
  - Configured `RunDataElectricPowerConsumption` (`r1;u`) as the preferred instantaneous electrical power source across `hmux0` and `hmu` while fresh (`<= 180 s`), dynamically falling back to `PowerStatus` if stale, and safely expiring power & active Live COP to `unavailable` after 10 minutes (`600 s`, or `2 × fallback_poll_interval`) without updates.
- **Controller Register `2800`, Decoupled Cooling Setpoints & Vacation Mode Guards:**
  - Renamed mislabeled `Z1DayTemp` (`2300`) to `Z1CoolingManualTemp` and `Z1MaxFlowTempDesired` (`2800` / invalid `w`) to read-only `Z1RoomHumidity` (`%`) across all 4 controller CSVs.
  - Enforced `PRESET_AWAY` (`Z1Status = holidayaway`) priority over active cooling in `SaunierGeniaZone1Climate`, preventing accidental cooling activation or veto overrides while away and keeping `HolidayTemp` exclusively for heating frost protection.
  - Widened `number.compressor_silent_operation_level` range to `30–60 %` and `number.max_cylinder_charge_time` range to `0–180 min` (`0 = Off`) to match field values observed on `basv3`/`hmu` installations.
- **Schedule Validation & Mutex Safety:**
  - Added chronological ordering validation, overlap rejection, midnight normalization (`24:00`), mutex write locking, and automatic cache recovery on mid-cascade communication errors.
- **Thermostat & Climate Symmetrical Operation:**
  - Fixed cooling season ECO preset to write `Z1OpModeCooling = "night"`, added dynamic season evaluation in `HVACMode.AUTO`, and corrected `select.hc1_auto_off_mode` options.
- **Thermodynamic Responsiveness:**
  - Evaluated thermal calculations against all canonical message aliases, immediately updating thermal power and live COP upon telemetry arrival.
- **Connection Loss Watchdog:**
  - Added a 10-minute communication watchdog that safely marks control entities unavailable when bus telemetry ceases, keeping historical sensors available.
- **CSV Header Compliance, Parity & Clean Hydration:**
  - Moved CSV column definitions to line 1 to comply with ebusd 26.1 C++ parser, filtered incompatible `b516` queries on HMU units, and enforced byte-for-byte parity and Unix `LF` line endings across `15.*.csv` and `08.hmu*.csv`.
- **English Localization for Countdown Duration States:**
  - Standardized coordinator string returns for `sensor.holiday_duration_remaining` and `sensor.cooling_duration_remaining` from Spanish (`Inactivo` / `Final abierto`) to standard English (`Inactive` / `Open-ended`), defined centrally in `const.py` (`STATE_INACTIVE` / `STATE_OPEN_ENDED`).
- **Compatibility & Code Quality:**
  - Fixed Home Assistant Core 2026.8+ Device Registry compatibility by passing `config_entry_id` to `async_get_device_by_identifier` via a unified registry lookup helper (retaining `async_get_device` fallback for earlier releases).
  - Raised minimum supported Home Assistant version to `2024.12.0` and achieved 100% clean Pyright static typing and Ruff formatting across 188 unit tests.

### Changed
- **Fast Live Electric Power Polling (`r1;u`) & Thermodynamic Polling (`r2;u`):**
  - Upgraded `RunDataElectricPowerConsumption` (`08.hmux0.csv`, `08.hmu.csv`, `08.hmu.HW5103.csv`) to top-priority `r1;u` active polling (with `PowerStatus` as fallback and 10-minute staleness expiration) so live electrical input updates reliably every ~9–18 seconds.
  - Upgraded `RunDataFlowTemp`, `RunDataReturnTemp`, and `RunDataFlowRate` from slow `r9;u` to prioritized `r2;u` in `08.hmux0.csv`, `08.hmu.csv`, and `08.hmu.HW5103.csv`.
  - Re-evaluates flow and return temperatures every ~18 to 36 seconds, accelerating real-time ΔT and instantaneous thermal power updates while keeping the full poll cycle under 2 minutes.
  - Converted `CompressorAvailability` in `08.hmux0.csv` to passive `u` to resolve the `prepare poll message: ERR: end of input reached` error caused by missing master input arguments during active polling.
- **eBUSd Add-on Setup & Collision Prevention:**
  - Updated documentation to instruct users to disable **"Seed HA MQTT integration config (only needed once)"** (`seed_mqtt_cfg: false`), preventing ebusd from injecting `mqtt-hassio.cfg` with `filter-seen = 5` which polled 160+ registers every 16 minutes, caused 2400-baud bus collisions, and created hundreds of duplicate MQTT entities.
  - Explicitly documented the requirement to add `--mqttjson` to `commandline_options` when `seed_mqtt_cfg` is disabled (as the add-on previously auto-injected `--mqttjson` only when `seed_mqtt_cfg` was active).
- **HACS Official Default Repository Indexing:**
  - Updated README documentation and badges from `HACS-Custom` to `HACS-Default`. With official inclusion in the default HACS store catalog, users can install directly via standard HACS search without configuring a custom repository URL.
- **Selective Low-Priority `r9;u` Polling & Conservative Register Naming:**
  - Assigned gentle `r9;u` background polling exclusively to registers not queried passively by `MiGo Link` (`0xf1`) across `08.hmux0.csv`, `08.hmu.csv` / `08.hmu.HW5103.csv`, and `15.*.csv`, keeping unpolled counters, COPs, and diagnostics fresh without saturating the bus.
  - Conservatively re-labeled unverified hourly diagnostic registers (`RunDataDiagxxxx`) across `08.hmux0.csv`, `08.hmu*.csv`, and `76.vwzio.csv`.

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

