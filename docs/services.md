# Actions (Services) Reference

**🇬🇧 English** | [🇪🇸 Versión en Español](services_es.md)

The integration registers twelve custom actions under the `arotherm_genia_ebusd` domain, available in **Developer Tools → Actions** and in automations and scripts.

| # | Action | Purpose |
| :---: | :--- | :--- |
| 1 | [`set_weekly_timer`](#1-arotherm_genia_ebusdset_weekly_timer) | Write or clear weekly schedule slots (heating, cooling, DHW, circulation, silent) |
| 2 | [`force_dhw_boost`](#2-arotherm_genia_ebusdforce_dhw_boost) | Immediate one-time DHW charge with hysteresis bypass |
| 3 | [`set_legionella_protection`](#3-arotherm_genia_ebusdset_legionella_protection) | Set the weekly anti-legionella disinfection schedule |
| 4 | [`set_holiday_mode`](#4-arotherm_genia_ebusdset_holiday_mode) | Activate holiday / away mode |
| 5 | [`cancel_holiday_mode`](#5-arotherm_genia_ebusdcancel_holiday_mode) | Cancel holiday / away mode |
| 6 | [`quick_veto`](#6-arotherm_genia_ebusdquick_veto) | Quick veto in the active mode (native heating veto, persistent cooling veto) |
| 7 | [`cancel_quick_veto`](#7-arotherm_genia_ebusdcancel_quick_veto) | Cancel the active quick veto |
| 8 | [`dump_mqtt_values`](#8-arotherm_genia_ebusddump_mqtt_values) | Dump cached telemetry for troubleshooting |
| 9 | [`record_topic_changes`](#9-arotherm_genia_ebusdrecord_topic_changes) | Record live MQTT traffic for a time window |
| 10 | [`send_hex_command`](#10-arotherm_genia_ebusdsend_hex_command) | Send a raw hex telegram (opt-in diagnostic) |
| 11 | [`read_parameter`](#11-arotherm_genia_ebusdread_parameter) | Read a symbolic eBUS register |
| 12 | [`write_parameter`](#12-arotherm_genia_ebusdwrite_parameter) | Write a symbolic eBUS register |

---

## 1. `arotherm_genia_ebusd.set_weekly_timer`

[![Open your Home Assistant instance and show your service developer tools.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.set_weekly_timer)

Modifies or clears native `b5 55` weekly time programs inside the `sensoCOMFORT` / `MiPro Sense` controller (`15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3`), synchronizing active slot counts and keeping automatic bus pacing across multi-day writes.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `circuit_type` | Yes | `heating`, `dhw`, `cooling`, `circulation`, `silent` | Target schedule: heating (`Z1Timer`), DHW (`HwcTimer`), cooling (`CoolingTimer`), circulation (`CirculationTimer`) or silent mode (`SilentTimer`). |
| `day` | Yes | `Monday`..`Sunday`, `Weekdays`, `Weekend`, `All`<br>*(Spanish also accepted: `Lunes`..`Domingo`, `Laborables`, `Fin de semana`, `Todos`)* | Single day, Monday-Friday, Saturday-Sunday, or the whole week. |
| `action` | No | `set`, `delete`, `clear` *(default: `set`)* | `set` creates or updates the slot; `delete` removes it and shifts later slots down; `clear` empties the day (0 active slots). |
| `slot` | No | `1`, `2`, `3` *(default: `1`)* | Daily slot index. Ignored with `action: clear`. |
| `start_time` | Optional* | `"HH:MM"` | Window start (24 h format, 1-minute resolution). *Required with `action: set`. |
| `end_time` | Optional* | `"HH:MM"` (use `"24:00"` for all day) | Window end (24 h format, 1-minute resolution). *Required with `action: set`. |
| `temp` | No | `5.0` - `80.0` (°C) | Target temperature for the slot. Only for `heating`, `dhw` and `cooling`; ignored for `circulation` and `silent`. If omitted, the active circuit setpoint is used. |
| `reset_remaining` | No | `true`, `false` *(default: `false`)* | With `slot: 1` and `action: set`, rewrites the day to exactly 1 active slot and erases slots 2 and 3 without needing prior bus telemetry. |

**Example 1 - DHW schedule every day (initializing the day with `reset_remaining`):**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: All
  slot: 1
  start_time: "13:00"
  end_time: "15:30"
  reset_remaining: true
```

**Example 2 - Continuous 24 h heating in Zone 1:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: heating
  day: All
  slot: 1
  start_time: "00:00"
  end_time: "24:00"
  temp: 20.5
  reset_remaining: true
```

**Example 3 - Add a second heating slot on weekends:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: heating
  day: Weekend
  slot: 2
  start_time: "17:00"
  end_time: "22:00"
  temp: 21.0
```

**Example 4 - Delete slot 2 on a single day:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Monday
  action: delete
  slot: 2
```

**Example 5 - Clear all slots for a day:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Monday
  action: clear
```

---

## 2. `arotherm_genia_ebusd.force_dhw_boost`

[![Open your Home Assistant instance and show your service developer tools.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.force_dhw_boost)

Triggers an immediate one-time DHW cylinder charge (`HwcSFMode = load`), optionally with a custom temporary boost temperature for that cycle (useful for solar PV surplus diverters).

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `boost_temp` | No | `40.0` - `68.0` (°C) | Temporary setpoint for this single boost cycle. If omitted, `T_current + Hysteresis + 1.5 °C` is applied automatically. |

**Example - Heat the DHW tank to 60 °C when solar export exceeds 2.5 kW:**
```yaml
action: arotherm_genia_ebusd.force_dhw_boost
data:
  boost_temp: 60.0
```

> **How the hysteresis bypass works:** the controller enforces a factory charging hysteresis (`CylinderChargeHyst = 5.0 K`), so a standard boost does nothing when the tank is within 5 K of the setpoint. With **Enable Smart Forced DHW Boost** enabled (default), the integration temporarily raises `HwcTempDesired` above the current tank temperature, fires `HwcSFMode = load`, and restores your original setpoint when charging completes, is cancelled or the 60-minute safety timeout elapses.

---

## 3. `arotherm_genia_ebusd.set_legionella_protection`

Configures the weekly anti-legionella thermal disinfection schedule (`HwcLegionellaDay` and `HwcLegionellaTime`) on the climate controller: the day of the week and the execution time.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `day` | Yes | `off`, `Monday`..`Sunday` *(or Spanish / `'0'`..`'7'`)* | Day to run the disinfection; `off` disables it. |
| `time` | No | `"HH:MM"` | Execution time (default `04:00` when a day is active). |

**Example - Weekly disinfection on Sunday at 04:00:**
```yaml
action: arotherm_genia_ebusd.set_legionella_protection
data:
  day: Sunday
  time: "04:00"
```

The same settings are exposed as the **Anti-Legionella Protection Day** (`select`) and **Anti-Legionella Protection Time** (`time`) entities on the Climate Controller device.

---

## 4. `arotherm_genia_ebusd.set_holiday_mode`

Activates Holiday / Away Mode on the climate controller, suspending DHW production and reducing space heating to a frost-protection setback temperature for a timed or open-ended window.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `5.0` - `24.0` (°C, default `15.0`) | Setback room temperature during the absence (heating only). |
| `start_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Absence start date (default: today). |
| `start_time` | No | `HH:MM` | Absence start time (default: current time). |
| `end_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Return date. If omitted, the mode stays active until cancelled. |
| `end_time` | No | `HH:MM` | Return time (default: `23:59`). |

**Example - Holiday until November 10th with 12 °C frost protection:**
```yaml
action: arotherm_genia_ebusd.set_holiday_mode
data:
  temperature: 12.0
  end_date: "2026-11-10"
  end_time: "18:00"
```

---

## 5. `arotherm_genia_ebusd.cancel_holiday_mode`

Immediately cancels Holiday / Away Mode and restores automatic schedule operation for heating and DHW. No parameters.

```yaml
action: arotherm_genia_ebusd.cancel_holiday_mode
```

---

## 6. `arotherm_genia_ebusd.quick_veto`

Applies a quick veto to Zone 1 in whichever mode is active (blocked while Away / Holiday mode is active):

- **Heating (or off):** uses the controller's **native heating quick veto**, a temporary setpoint override (`Z1QuickVetoTemp` / `Z1QuickVetoDuration` / `Z1SFMode`) with its own countdown, after which the controller restores its prior operating mode (`auto`, `day`, `night`, or `off`).
- **Cooling:** the controller's native veto does not cover cooling, so the action routes to a **persistent timed cooling quick veto managed by the integration**: it switches cooling to manual day mode (`Z1OpModeCooling = day`) with the temporary target and restores the exact pre-veto operating mode and manual cooling setpoint when the timer expires or is cancelled.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `10.0` - `30.0` (°C in heating)<br>`15.0` - `30.0` (°C in cooling) | Target during the veto. If omitted: in heating, `+3.0 °C` over the current target when running (adjustable via **Zone 1 Quick Veto Boost Delta**) or `Z1ManualTemp` when off; in cooling, the current target minus the cooling boost delta (**Zone 1 Cooling Quick Veto Boost Delta**, default `2.0 °C`), or `Z1CoolingManualTemp` outside a scheduled slot. |
| `duration` | No | `0.5` - `12.0` (hours) | Veto duration. If omitted, the controller's configured **Zone 1 Quick Veto Duration** is used (factory default `3.0 h`). |

**Example - Boost Zone 1 to 22.5 °C for 2.5 hours:**
```yaml
action: arotherm_genia_ebusd.quick_veto
data:
  temperature: 22.5
  duration: 2.5
```

> **Cooling quick veto persistence:** the end timestamp and captured pre-veto state (`Z1OpModeCooling` and `Z1CoolingManualTemp`) are saved to Home Assistant persistent storage (`Store`), not just RAM. If Home Assistant restarts while a cooling veto is active, the integration reloads that state on startup, resumes any remaining countdown (or triggers expiration restoration immediately if time already elapsed), and writes back your previous mode and setpoint once eBUS communication is ready. The same persistent cooling veto flow applies when you adjust the target temperature from the climate card while scheduled cooling (`auto`) is active.

---

## 7. `arotherm_genia_ebusd.cancel_quick_veto`

Immediately cancels the active quick veto. For heating, it clears `Z1SFMode` back to `auto`, sets duration to `0`, and restores `off` if heating had been off beforehand; for cooling, it stops the timer, clears persisted veto storage, and writes back the captured pre-veto operating mode and manual cooling setpoint. No parameters.

```yaml
action: arotherm_genia_ebusd.cancel_quick_veto
```

---

## 8. `arotherm_genia_ebusd.dump_mqtt_values`

Dumps all cached telemetry, active circuits, hardware models and eBUS state as a service response (`SupportsResponse.ONLY`), visible in Developer Tools. Designed for sharing installation snapshots in GitHub issues.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `circuit` | No | String (e.g. `"08"`, `"15"`, `"hmu"`) | Substring filter to restrict the dump. If omitted, all active circuits are dumped. |
| `anonymize` | No | Boolean (default `true`) | Masks manufacturing serial numbers so the snapshot is safe to share publicly. |

---

## 9. `arotherm_genia_ebusd.record_topic_changes`

Records all live MQTT traffic under the `ebusd` topic prefix for a configurable window (`SupportsResponse.ONLY`): timestamps, topics, parsed JSON payloads and retained flags. Useful to trace physical interactions without SSH access.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `duration` | No | `5` - `120` (seconds, default `30`) | Recording window. |
| `circuit` | No | String (e.g. `"08"`, `"15"`) | Substring filter for captured topics. |
| `anonymize` | No | Boolean (default `true`) | Masks serial numbers and hardware identifiers in the captured payloads. |

---

## 10. `arotherm_genia_ebusd.send_hex_command`

Sends a raw hexadecimal telegram directly to the `ebusd` daemon over its TCP socket and returns the raw response bytes (`SupportsResponse.ONLY`). Intended for probing undocumented registers without editing CSV files or using SSH.

**This action is a deliberate security opt-in.** It is blocked until you enable **Enable Raw Hex Command** (`enable_send_hex`) in the integration options, and `ebusd` must be started with `--enablehex`. Raw telegrams can write any register on the bus, including installer and safety parameters: use it only if you know exactly which frame you are sending and why.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `command` | Yes | Hex string (e.g. `"08b51a0405ff3428"`) | Raw telegram (spaces are stripped). |
| `host` | No | String (default configured TCP host, e.g. `"127.0.0.1"`) | Host running `ebusd`. |
| `port` | No | Integer (default configured TCP port, e.g. `8888`) | `ebusd` TCP command port. |
| `timeout` | No | Float (default `5.0`) | Socket timeout in seconds. |

---

## 11. `arotherm_genia_ebusd.read_parameter`

Reads a symbolic eBUS register over MQTT (`SupportsResponse.ONLY`): publishes to `<prefix>/<circuit>/<name>/get` and awaits the decoded JSON response. Circuit aliases such as `08`, `15`, `outdoor` and `controller` are resolved automatically.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `circuit` | Yes | String (e.g. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`) | eBUS circuit name or alias. |
| `name` | Yes | String (e.g. `"CompressorSilentOperationLevel"`, `"Status01"`) | Symbolic message/parameter name defined in the CSVs. |
| `force` | No | Boolean (default `false`) | `true` forces an active bus query instead of returning the cached value. Prefer the cache to keep bus traffic low. |
| `timeout` | No | Float (default `5.0`) | Maximum wait for the MQTT response, in seconds. |

---

## 12. `arotherm_genia_ebusd.write_parameter`

Writes a symbolic value to an eBUS register over MQTT (`SupportsResponse.OPTIONAL`): publishes to `<prefix>/<circuit>/<name>/set` and applies an immediate optimistic UI update.

| Parameter | Required | Allowed Values | Description |
| :--- | :---: | :--- | :--- |
| `circuit` | Yes | String (e.g. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`) | eBUS circuit name or alias. |
| `name` | Yes | String (e.g. `"CompressorSilentOperationLevel"`, `"Z1OpMode"`) | Symbolic message/parameter name defined in the CSVs. |
| `value` | Yes | String / Number / Boolean | Value to write. |

> Writes go onto the physical eBUS. Check the allowed range of each register in the CSV definition before writing, and avoid high-frequency writes from automations: the bus runs at 2400 baud and shares the medium with your wall controller.

