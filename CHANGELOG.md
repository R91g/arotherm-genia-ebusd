# Changelog

All notable changes to **aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

