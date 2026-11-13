# Troubleshooting & FAQ

**🇬🇧 English** | [🇪🇸 Versión en Español](troubleshooting_es.md)

---

## Downloading Diagnostics & Bus Verification

To inspect the raw cached JSON payloads from `ebusd`, or to attach them to a bug report: **Settings → Devices & Services → aroTHERM & GeniaAir (eBUS) → `⋮` → Download diagnostics**. Sensitive MQTT topic details are redacted automatically.

For shareable snapshots, the [`dump_mqtt_values`](services.md#8-arotherm_genia_ebusddump_mqtt_values) and [`record_topic_changes`](services.md#9-arotherm_genia_ebusdrecord_topic_changes) actions produce anonymized captures (serial numbers masked by default) directly from Developer Tools.

If **eBUSd TCP Diagnostics** is enabled in [runtime options](configuration.md#runtime-options-configure), the coordinator also runs zero-bus-traffic `info` and CSV `find` checks over TCP, populates physical bus latency/symbol metrics, and updates **eBUS Missing CSV Devices** whenever a scanned bus address has no matching CSV file loaded.

> **Note:** Recent `ebusd` versions (24.x / 26.x) log decoding errors internally instead of publishing `ERR:` payloads onto MQTT topics, so **eBUSd TCP Diagnostics** (`find`) is the reliable way to detect missing or incompatible CSV definitions.

## Frequently Asked Questions

<details>
<summary><b>1. Why do some entities show <code>Unknown</code> for the first 30-60 seconds after restarting Home Assistant?</b></summary>

This is by design. To protect the 2400-baud bus, the coordinator waits `5.0 s` for retained MQTT messages and then queries missing registers one by one (`0.8 s` apart). All active sensors populate within about a minute.
</details>

<details>
<summary><b>2. I switched Zone 1 to <code>Cool</code>; why does <code>Cooling Release Status (Hardware Lock 1)</code> still show Locked?</b></summary>

The integration opens the calendar dates (`01;01;26` to `01;01;99`) and sets `Z1OpModeCooling = day`, but the physical `CoolingReleaseStatus` register in the controller firmware only unlocks when BOTH the calendar window is open AND the outdoor temperature exceeds `CoolingOutsideTempThreshold` (typically `≥ 15 °C`). Below that temperature the heat pump blocks cooling in hardware to protect the compressor. Note also that active Away / Holiday mode prevents cooling activation altogether.
</details>

<details>
<summary><b>3. How do I verify that ebusd is publishing JSON to MQTT?</b></summary>

Subscribe to your broker with `mosquitto_sub` (or **Settings → Devices & Services → MQTT → Configure → Listen to a topic**):

```bash
mosquitto_sub -h <MQTT_BROKER_IP> -u <USER> -P <PASS> -t "ebusd/#" -v
```

Payloads should be JSON objects (e.g. `ebusd/hmux0/RunDataFlowTemp {"value": {"value": 34.25}}`). If you see plain numbers, add `--mqttjson` to your `ebusd` startup flags and restart `ebusd`.
</details>

<details>
<summary><b>4. Why is <code>Global System Off (Installer)</code> disabled by default?</b></summary>

Writing `yes` to `GlobalSystemOff` puts the whole installation (including DHW and, depending on firmware, frost protection routines) into installer standby. The entity is disabled by default in the entity registry to prevent accidental dashboard or voice-assistant toggles; you can enable it manually from the Climate Controller device page.
</details>

<details>
<summary><b>5. Some sensors stay <code>Unknown</code> permanently on my CTLV2 / CTLV3 controller or HMU (HW5103) unit.</b></summary>

Two common causes:

- The register is defined as read-on-demand (`r`) and nothing on the bus requests it, so `ebusd` never publishes it. Enabling [eBUSd TCP diagnostics](configuration.md) or reading it once with [`read_parameter`](services.md#11-arotherm_genia_ebusdread_parameter) (`force: true`) confirms whether the register answers.
- The hardware variant genuinely does not expose that register. Support for `15.ctlv2`/`15.ctlv3` and `08.hmu.HW5103` is based on register maps and community reports, and is still being validated on real installations. Please open an issue with an anonymized [`dump_mqtt_values`](services.md#8-arotherm_genia_ebusddump_mqtt_values) capture so the register map can be confirmed or adjusted.
</details>

<details>
<summary><b>6. Why did control entities or Live COP become <code>Unavailable</code> after 10 minutes?</b></summary>

The coordinator enforces a `600 s` (`10-minute`, or `2 × fallback_poll_interval`) communication watchdog and power-freshness timeout. If MQTT updates from `ebusd` stop arriving (e.g. `ebusd` stopped, MQTT disconnected, or the adapter dropped off the bus), controls and live power/COP switch to `unavailable` until bus telemetry resumes, while historical energy counters keep their state.
</details>

## Reporting an Issue

When opening a [GitHub issue](https://github.com/R91g/arotherm-genia-ebusd/issues), include:

1. The **diagnostics file** (see above).
2. An anonymized **`dump_mqtt_values`** response.
3. If the problem involves bus communication or a register that misbehaves, a **`record_topic_changes`** capture taken while reproducing it.
4. Your `ebusd` version (`ebusd --version`), Home Assistant version and hardware models (outdoor unit, controller, hydraulic module).

