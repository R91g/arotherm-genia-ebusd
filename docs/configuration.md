# Configuration & Runtime Options

**🇬🇧 English** | [🇪🇸 Versión en Español](configuration_es.md)

---

## Reconfiguring Hardware or Brand

To change the heat pump model, switch brand labels, or toggle the wireless thermostat / cloud gateway after setup:

- Go to **Settings → Devices & Services → aroTHERM & GeniaAir (eBUS)**, open the **three-dot menu (`⋮`)** on the config entry and select **Reconfigure**.
- Device titles and hardware specs update while preserving all entity IDs and historical statistics. Entity `unique_id`s are brand-neutral (`{entry_id}_{circuit}_{message}_{field}`), so changing the manufacturer or models never orphans entities or breaks energy history.

## Runtime Options (`Configure`)

Click **Configure** on the integration card to adjust runtime behavior without restarting Home Assistant:

| Option | Default | Range | Description |
| :--- | :---: | :---: | :--- |
| **Enable Smart Forced DHW Boost** (`force_dhw_boost`) | `True` | On / Off | Dynamically raises `HwcTempDesired` to `T_current + Hysteresis + 1.5 °C` when `ΔT < Hysteresis` during a one-time DHW boost, restoring the original setpoint afterward. |
| **Automatically open Cooling Lock 1** (`auto_cooling_lock_bypass`) | `True` | On / Off | Sets `CoolingStartDate = 01;01;26` and `CoolingEndDate = 01;01;99` when Zone 1 switches to `Cool`, and locks back to `01;01;19` in `Heat` / `Off`. |
| **Fallback `/get` polling interval** (`fallback_poll_interval`) | `300 s` | `60` - `3600 s` | Interval for gentle active polling of core registers. Only active when the official cloud gateway (`f1`) option is disabled. |
| **Enable eBUSd TCP Diagnostics** (`enable_ebusd_tcp`) | `False` | On / Off | Enables direct asynchronous TCP queries to `ebusd` (`ebusctl`, port `8888`) for physical bus metrics, scan status, CSV verification (`find`), missing-CSV alerts and daemon control buttons. |
| **eBUSd TCP Host** (`ebusd_tcp_host`) | `127.0.0.1` | Hostname / IP | Host running `ebusd` (e.g. `127.0.0.1` or `core-ebusd`). |
| **eBUSd TCP Port** (`ebusd_tcp_port`) | `8888` | `1` - `65535` | TCP port where `ebusd` accepts commands. |
| **Enable Raw Hex Command** (`enable_send_hex`) | `False` | On / Off | Security opt-in that unblocks the `send_hex_command` diagnostic action. Off by default; see the [actions reference](services.md#10-arotherm_genia_ebusdsend_hex_command). |

## Everyday Use

> **Note on entity IDs:** Home Assistant prefixes entity IDs with the configured controller or device name and translates them to your UI language (for example `climate.mipro_sense_src_720_zone_1_climate`). Below, entities are referenced by their English UI names and translation key suffixes.

- **Zone 1 Climate** (`*_zone_1_climate`): modes **Off / Heat / Cool** and presets **Scheduled (Comfort)**, **Continuous Manual**, **Eco (Night setback)**, **Quick Veto Override** and **Away**. Changing the target temperature writes to the setpoint of the active mode; with cooling in scheduled mode it starts a persistent timed cooling quick veto (see [`quick_veto`](services.md#6-arotherm_genia_ebusdquick_veto)).
- **Domestic Hot Water** (`water_heater`): modes **Off**, **Time-controlled (schedule)**, **Continuous (24h)** and **Boost**. A boost can also be started from **One-Time DHW Charge (Boost)** or the [`force_dhw_boost`](services.md#2-arotherm_genia_ebusdforce_dhw_boost) action.
- **Holiday / Away Mode:** the **Away Mode** switch with its **Holiday Start / End** `datetime` controls, or the [`set_holiday_mode`](services.md#4-arotherm_genia_ebusdset_holiday_mode) action.
- **Weekly schedules:** the **5 weekly schedule summary sensors** (`heating`, `dhw`, `cooling`, `circulation` and `silent`) show the active programs; changes are written with [`set_weekly_timer`](services.md#1-arotherm_genia_ebusdset_weekly_timer).
- **Silent mode:** **Compressor Silent Operation Level** (`*_compressor_silent_operation_level`, `30–60 %`) sets the compressor noise reduction limit, and the `silent` schedule in `set_weekly_timer` controls when it applies.

## Quick Veto Tuning Entities

Two numeric configuration entities on the Climate Controller adjust how [`quick_veto`](services.md#6-arotherm_genia_ebusdquick_veto) calculates its temporary setpoint when no explicit temperature is passed:

- **Zone 1 Quick Veto Boost Temperature Delta** (`*_z1_quick_veto_boost_delta`): degrees added above the current heating target when starting a heating veto without an explicit temperature (default `+3.0 °C`).
- **Zone 1 Cooling Quick Veto Boost Temperature Delta** (`*_z1_cooling_quick_veto_boost_delta`): degrees subtracted from the current cooling target when starting a cooling veto without an explicit temperature (default `-2.0 °C`).

The default veto duration is read from the controller's own **Zone 1 Quick Veto Duration** register (`*_z1_quick_veto_duration`, factory default `3.0 h`, range `0.5–12.0 h`).

## Anti-Legionella Schedule Entities

The weekly thermal disinfection cycle is exposed on the Climate Controller device:

- **Anti-Legionella Protection Day** (`select.*_hwc_legionella_day`): `off` or Monday through Sunday.
- **Anti-Legionella Protection Time** (`time.*_hwc_legionella_time`): execution time (`HH:MM`).

The same schedule can be set from automations with the [`set_legionella_protection`](services.md#3-arotherm_genia_ebusdset_legionella_protection) action.

## Zone 1 Climate Behavior & Watchdogs

Four operational rules in the climate entity and coordinator are worth knowing before building automations around them:

- **Sentinel filtering:** the controller reports `5.0 °C` as the desired room temperature when heating is off (frost protection) and `99.0 °C` when cooling is off. The integration filters both values and persists your real heating and cooling targets independently across Home Assistant restarts (`RestoreEntity`), so the UI never jumps to those extremes.
- **Cooling double-lock:** the controller guards active cooling behind Gate 1 (calendar dates `CoolingStartDate`–`CoolingEndDate` plus `CoolingOutsideTempThreshold`) and Gate 2 (`Z1OpModeCooling`). Selecting `Cool` opens both (when `auto_cooling_lock_bypass` is enabled, Gate 1 opens indefinitely unless you set custom dates with **Manual Cooling Start Date** / **Manual Cooling End Date**); switching back to `Heat` or `Off` closes Gate 1 (`01;01;19`) and restores the heating setpoint.
- **Away / Holiday mode priority over cooling:** `HolidayTemp` (`5.0–24.0 °C`, default `15.0 °C`) is strictly a heating frost-protection setback. While Away / Holiday mode is active (`holidayaway`), cooling and cooling quick veto activation are blocked (and any active cooling quick veto is cleared) so an unoccupied home is never cooled unnecessarily.
- **Communication watchdog:** if eBUS telemetry stops arriving for `10 minutes` (`600 s`, or `2 × fallback_poll_interval`), control entities safely transition to `unavailable` while historical counters remain preserved.

All `number` entities use box inputs (`NumberMode.BOX`) with steppers instead of sliders to prevent accidental edits while scrolling on mobile devices.

## Home Assistant Energy Dashboard

The integration exposes sub-kWh (`Wh`, IEEE 754) cumulative `TOTAL_INCREASING` energy sensors combining the outdoor unit (`08.hmux0`) and the hydraulic module (`76.vwzio`), structured for the Energy Dashboard's **Individual Devices** hierarchy (parent/child nesting so `Parent == Heating + DHW + Cooling` with no double-counting):

1. Open **Settings → Dashboards → Energy → Individual devices** and click **Add device**.
2. **Add the parent (total heat pump) sensor:**
   - Select **Total System Electrical Energy** (`*_calculated_system_total_energy`, in `Wh`, on the Outdoor Unit device).
   - Give it a friendly name (e.g. `Heat Pump (Total)`).
3. **Add the 3 nested child sensors** (setting **Included in** → `Total System Electrical Energy` on each):
   - **Heating:** `Total Heating Electrical Energy` (`*_calculated_heating_total_energy`).
   - **Domestic Hot Water:** `Total DHW Electrical Energy` (`*_calculated_dhw_total_energy`).
   - **Cooling:** `Total Cooling Electrical Energy` (`*_energy_electric_cool`).

Home Assistant computes hourly, daily, monthly and yearly deltas from these Wh-resolution hardware counters and shows an expandable **Heating vs. DHW vs. Cooling** breakdown without counting any watt-hour twice. Component-level `08.hmux0` vs `76.vwzio` counters remain available as diagnostic sensors if you want to inspect compressor and hydraulic module consumption separately.

> **Note on `HMU` / `HMU00` (`HW5103`) units:** these boards lack some of the Monobloc `b5 16` EEPROM registers, so the integration falls back to controller `PrEnergySum*` and outdoor `Yield*` / `TotalEnergyUsage` counters (`ULG`) and automatically disables the 3 Monobloc-exclusive per-mode outdoor electrical sensors in the entity registry.

### Instantaneous Power & Computed Thermodynamic Values

Instantaneous electrical power prioritizes `RunDataElectricPowerConsumption` (`r1;u`) while fresh (`<= 180 s`), dynamically falling back to `PowerStatus` if stale, and expiring both live power and Live COP to `unavailable` after `600 s` (`10 min`) without updates:

```text
Primary ΔT (K)               = T_flow (RunDataFlowTemp) - T_return (RunDataReturnTemp)
Instantaneous Thermal Power  = Flow_Rate (L/h) × |ΔT| (K) × 1.163   [Watts]
Live Instantaneous COP / EER = Thermal_Power (W) / Electric_Power (W)
Mode & Global COP / EER      = (HMUX0_Thermal_Wh + VWZIO_Thermal_Wh) / (HMUX0_Elec_Wh + VWZIO_Elec_Wh)
Total System Energy (Wh)     = Heating_Total_Wh + DHW_Total_Wh + Cooling_Total_Wh
```

Values are clamped to zero during defrost cycles and compressor standby so residual circulation pump flow does not produce phantom COP spikes.

