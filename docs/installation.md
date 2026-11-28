# Installation Guide

**🇬🇧 English** | [🇪🇸 Versión en Español](installation_es.md)

This guide covers the full setup: physical adapter, `ebusd` configuration, integration install and first-run verification. Allow 30-45 minutes.

---

## 1. Prerequisites

1. **Physical eBUS adapter** connected in parallel to the 2-wire eBUS terminals (`+`/`-`, polarity-insensitive) of your heat pump, hydraulic module or wall controller - for example, the [eBUS Adapter Shield v5 / C6](https://adapter.ebusd.eu/) (Ethernet, Wi-Fi or USB).
2. **`ebusd` daemon (v23.2 or newer)** running either as the Home Assistant eBUSd Add-on or as a standalone Linux service / Docker container, connected to your MQTT broker with `--mqttjson` enabled.
3. **Home Assistant (`2024.12.0` or newer, the minimum version declared to HACS)** with the core [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) installed and connected to the same MQTT broker as `ebusd`.

### Physical Wiring & Coexistence

eBUS is a 2-wire, 24 V differential serial bus that connects all heating devices in parallel. You can connect the adapter at any point where the bus is accessible (indoor hydraulic station, outdoor unit or wall controller).

<p align="center">
  <img src="images/ebus_wiring_diagram.svg" alt="eBUS Hardware Wiring Diagram" width="900">
</p>

> **Safety:** disconnect the mains power supply before opening the electrical enclosure of any unit, and follow your equipment's installation manual. If you are not confident working inside the unit, have a qualified installer connect the adapter. The terminal layout described below is documented from a Saunier Duval GeniaSet / Vaillant uniTOWER indoor board (see the photo); other models may differ, so check the manual of your own unit.

**Wiring notes for the documented board:**

- **Terminal `BUS (+ / -)` (red header):** intended for system accessories; the official cloud gateway (`myVAILLANT connect` / `MiGo Link`) usually connects here. You can connect the eBUS adapter in parallel on this same port (double-crimping into the screw terminal or with WAGO 221 lever connectors).
- **Terminal `X25 (A / B)` (orange header):** the communication line from the outdoor unit lands here. On the documented board, `BUS` and `X25` are interconnected on the PCB traces; verify this on your own unit before treating the two ports as equivalent.
- **Polarity:** the eBUS specification is polarity-insensitive (devices rectify the line internally), so reversing `+`/`-` (or `A`/`B`) does not damage the bus.
- **Coexistence with the official gateway:** if you have `myVAILLANT connect` or `MiGo Link`, do not remove it. The integration passively captures the telemetry it requests, which reduces bus utilization.

<details>
<summary>📸 <b>Real-World Installation Photograph (Indoor Hydraulic Board)</b></summary>
<br>

<p align="center">
  <img src="images/real_installation_pcb.jpg" alt="Real installation photo inside the indoor unit" width="650">
  <br>
  <em>Real installation inside a Saunier Duval GeniaSet / Vaillant uniTOWER electrical enclosure. The eBUS Adapter C6 is powered via USB-C at the bottom, connected in parallel with the official MiGo Link gateway on the red <code>BUS</code> terminal, while the outdoor unit bus enters through the orange <code>X25 (A/B)</code> connector.</em>
</p>

</details>

---

## 2. Deploy the ebusd CSV Configuration

> **Why are the bundled CSV files required?**
> The default CSV definitions distributed with `ebusd` predate these R290 heat pump boards and do not include most of their messages. The CSV files in [`ebusd-configuration/`](../ebusd-configuration/) define the registers of the `08.hmux0`, `08.hmu`, `15.bass3`/`basv3`/`ctlv2`/`ctlv3`, `76.vwzio` and `04.netx3` boards, and rely primarily on passive frame capture to keep bus traffic low: the eBUS medium runs at 2400 baud and is shared with the wall controller, so every actively polled register competes with normal system traffic.

Copy the CSV files into your `ebusd` configuration directory preserving this exact structure:

```text
<ebusd-config-root>/en/
├── broadcast.csv              <-- MUST be placed in the root of en/ (NEVER inside vaillant/)
└── vaillant/
    ├── 04.netx3.csv           <-- Wireless room thermostat receiver (NETX3 / NETX2)
    ├── 08.hmu.csv             <-- Outdoor heat pump board (international / HMU00 variants)
    ├── 08.hmu.HW5103.csv      <-- Outdoor heat pump board (HW=5103 matching priority)
    ├── 08.hmux0.csv           <-- Outdoor heat pump board (aroTHERM plus / GeniaAir Max)
    ├── 15.bass3.csv           <-- Climate controller (MiPro Sense SRC 720 / sensoCOMFORT VRC 720)
    ├── 15.basv3.csv           <-- Climate controller (sensoCOMFORT VRC 720 reporting BASV3)
    ├── 15.ctlv2.csv           <-- Climate controller (sensoCOMFORT VRC 720/2)
    ├── 15.ctlv3.csv           <-- Climate controller (sensoCOMFORT VRC 720/3)
    ├── 52.vr_70.csv           <-- Optional VR 70 mixer / solar expansion module
    ├── 76.vwzio.csv           <-- Hydraulic module / tower (VWZ MEH / uniTOWER / HPIM 7 / GeniaSet)
    └── f6.netx3.csv           <-- Wireless room thermostat passive RF frames
```

### Option A: Home Assistant eBUSd Add-on ([LukasGrebe/ha-addons](https://github.com/LukasGrebe/ha-addons))

**Quick install / update (recommended):** run this one-line command from Home Assistant's **Terminal & SSH** or **Studio Code Server** app (auto-detects `/addon_configs/*_ebusd/ebusd-configuration/en`, backs up modified files, and never touches unrelated CSVs):

```bash
curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh
```

> Use the same command later whenever a new release updates the CSVs. Pass `sh -s -- --main` to pull unreleased CSV fixes from `main`, or `sh -s -- --help` for all options (`--dir`, `--version`, `--dry-run`, `--reload`).

**Or install manually:**

1. Copy `ebusd-configuration/broadcast.csv` to:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/broadcast.csv`
2. Copy all files inside `ebusd-configuration/vaillant/*.csv` to:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/vaillant/`
3. Configure the add-on (**Settings → Add-ons → eBUSd → Configuration**):
   - **Disable the "Seed HA MQTT integration config (only needed once)" toggle** (`seed_mqtt_cfg: false`).
     > When enabled, the add-on injects its bundled `mqtt-hassio.cfg` with `filter-seen = 5`, which polls a broad set of legacy registers every 16 minutes and creates a large number of unmanaged MQTT entities in Home Assistant. With the toggle off, polling is controlled exclusively by the CSV definitions from this repository.
     >
     > If the add-on previously ran with this seed enabled, delete the orphaned `ebusd` devices under **Settings → Devices & Services → MQTT**.
   - **Add these startup arguments in `commandline_options` (one per entry):**
     ```text
     --mqttjson
     --configpath=/config/ebusd-configuration/en
     --scanconfig
     --accesslevel=*
     --mqtttopic=ebusd/%circuit/%name
     --mqttvar=filter-direction=r|u|^w
     ```
     > **Remember `--mqttjson` explicitly.** The add-on only appends it automatically while the seed toggle is enabled; once you disable the seed, you must add it yourself or `ebusd` will publish plain values the integration cannot parse.
     >
     > What each flag does:
     > - `--mqttjson`: publishes messages as JSON (`{"value": ...}`), required by the coordinator.
     > - `--configpath`: loads the CSVs from this repository instead of the online defaults.
     > - `--scanconfig`: probes the bus on startup and binds circuits (`08`, `15`, `76`, `04`) to their CSV files.
     > - `--accesslevel=*`: allows reading and writing installer-level parameters (heating curves, bivalence points, limits).
     > - `--mqtttopic=ebusd/%circuit/%name`: structures topics per circuit and message (matches `ebusd`'s default topic format).
     > - `--mqttvar=filter-direction=r|u|^w`: permits write operations (`^w`) for setpoints, modes and curves.
     >
     > `--pollinterval` is intentionally omitted so `ebusd` keeps its default 5-second cycle, which matches the CSV read priorities (`r1`/`r2`/`r9`). `--enablehex` is only needed if you plan to use the optional `send_hex_command` diagnostic action.
     >
     > **Using a Wi-Fi eBUS adapter (`ens:`)?** `ebusd` uses `--latency=10` ms by default for network devices, which can be too tight for 2.4 GHz Wi-Fi jitter and trigger `ERR: read timeout` / `ERR: SYN received` or dropped writes. Add `--latency=50` to `commandline_options` (up to `80`–`100` on congested Wi-Fi; keep `--pollinterval` at its default 5 s). Ethernet and USB adapters do not need this flag.

   <p align="center">
     <img src="images/ebusd_addon_config.png" alt="Home Assistant eBUSd Add-on configuration UI showing seed_mqtt_cfg disabled and commandline_options" width="750">
     <br>
     <em>Reference configuration in the eBUSd Add-on UI: <b>Seed HA MQTT integration config</b> disabled (red) and required flags added under <b>Additional ebusd options</b> (plus optional external MQTT broker flags and SQLite telegram logging).</em>
   </p>

   - **Equivalent YAML configuration** (**⋮ → Edit in YAML**):
     ```yaml
     network_device: ens:<ADAPTER_IP>:9999
     seed_mqtt_cfg: false
     commandline_options:
       - --mqttjson
       - --mqtthost=<BROKER_IP>        # Optional: only if using an external MQTT broker (no spaces after '=')
       - --mqttport=1883               # Optional: external MQTT broker port
       - --mqttuser=<MQTT_USER>        # Optional: external MQTT broker user
       - --mqttpass=<MQTT_PASSWORD>    # Optional: external MQTT broker password
       - --mqttvar=filter-direction=r|u|^w
       - --accesslevel=*
       - --configpath=/config/ebusd-configuration/en
       - --scanconfig
       - --latency=50                  # Recommended for Wi-Fi adapters (ens:); omit for Ethernet/USB
       - --enablehex                   # Optional: required only for send_hex_command
     sqlite_db: /config/telegrams.db   # Optional: stores raw eBUS telegrams for troubleshooting
     sqlite_retention_days: 10
     ```
     > When using Home Assistant's local Mosquitto add-on, `--mqtthost`, `--mqttport`, `--mqttuser` and `--mqttpass` are sourced automatically from the Supervisor MQTT service and can be omitted. If you specify them manually (for example for an external broker), **never put spaces after `=`**.
4. Restart the `eBUSd` add-on and check its log: circuits `08.hmux0` (or `08.hmu`), `15.bass3` (or `15.basv3` / `15.ctlv2` / `15.ctlv3`) and `76.vwzio` should load after the bus scan.

### Option B: Standalone Linux / Docker ebusd

**Quick install / update (recommended):**

```bash
# Auto-detects /etc/ebusd/en (or pass -d /path/to/your/docker-volume/en):
curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sudo sh
```

**Or install manually:**

1. Copy `ebusd-configuration/broadcast.csv` to `/etc/ebusd/en/broadcast.csv` (or your mapped Docker volume).
2. Copy `ebusd-configuration/vaillant/*.csv` to `/etc/ebusd/en/vaillant/`.
3. Add to `/etc/default/ebusd` (`EBUSD_OPTS`) or your `docker-compose.yml` command (keep the quotes: without them the shell interprets `|` and `*`):
   ```text
   --configpath=/etc/ebusd/en --scanconfig '--accesslevel=*' --mqttjson '--mqtttopic=ebusd/%circuit/%name' '--mqttvar=filter-direction=r|u|^w' --mqtthost=<BROKER_IP> --mqttport=1883 --mqttuser=<USER> --mqttpass=<PASS>
   ```
4. Restart `ebusd` (`sudo systemctl restart ebusd` or `docker compose restart ebusd`).

### Option C (Optional): Automatic CSV Updates After Each HACS Update (`shell_command`)

Because HACS updates never overwrite files outside `custom_components/`, you can automate CSV updates directly from Home Assistant so `ebusd` always stays in sync after each integration update:

- **Important HAOS container note:** Home Assistant's `shell_command` runs inside the `homeassistant` container, which can read/write `/share` (and `/config`) but **cannot** access `/addon_configs/b4d7ad18_ebusd`. The `LukasGrebe/ha-addons` eBUSd add-on mounts `/share` as read/write, so placing your CSVs under `/share/ebusd-configuration/en` lets **both** Home Assistant and eBUSd share the folder cleanly without SSH.
  1. Run the installer once pointing to `/share/ebusd-configuration/en`:
     ```bash
     curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh -s -- -d /share/ebusd-configuration/en
     ```
  2. In the eBUSd add-on `commandline_options`, point `--configpath` to `/share/ebusd-configuration/en` and restart the add-on once.
  3. Add a `shell_command` to `configuration.yaml` (the script auto-detects `/share/ebusd-configuration/en` and reloads `b4d7ad18-ebusd:8888` live without restarting the add-on; pass `-v {{ tag }}` if you also test HACS beta pre-releases):
     ```yaml
     shell_command:
       update_ebusd_csvs: >-
         curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh
         | sh -s -- -d /share/ebusd-configuration/en --reload
     ```
  4. Import the official **[Automatic eBUSd CSV Updater Blueprint](../blueprints/automation/ebusd_csv_auto_update.yaml)** in one click (no automation YAML needed — supports persistent notifications, custom mobile/Telegram notify actions, and optional `{{ tag }}` beta version tracking):

     [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FR91g%2Farotherm-genia-ebusd%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Febusd_csv_auto_update.yaml)

     *(Or if you prefer manual YAML instead of the blueprint:)*
     ```yaml
     alias: "eBUSd: Auto-update CSVs after integration update"
     trigger:
       - trigger: state
         entity_id: update.arotherm_genia_ebusd_update
         from: "on"
         to: "off"
     action:
       - action: shell_command.update_ebusd_csvs
         response_variable: csv_result
       - action: persistent_notification.create
         data:
           title: >-
             {{ "eBUSd CSVs Updated" if csv_result.returncode == 0 else "eBUSd CSV Update Failed" }}
           message: >-
             {{ csv_result.stdout if csv_result.returncode == 0 else (csv_result.stderr or csv_result.stdout) }}
     ```
- **Prefer to keep your CSVs in `/addon_configs/b4d7ad18_ebusd`?** Run the one-line command from the **Terminal & SSH** add-on whenever a Repair notice appears — or invoke it over SSH from `shell_command` if you already use SSH keys to reach your host/Terminal add-on.

---

## 3. Install the Integration

### Method A: HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=R91g&repository=arotherm-genia-ebusd&category=integration)

Or manually:

1. Open **HACS** in the Home Assistant sidebar.
2. Search for **`aroTHERM & GeniaAir (eBUS)`** (or `arotherm_genia_ebusd`).
3. Open the integration card and click **Download**.
4. **Restart Home Assistant** so Python loads the new custom component.

> The integration is included in the HACS default catalog, so you do not need to add a custom repository URL.

### Method B: Manual

1. Download the latest release (or clone this repository).
2. Copy the `custom_components/arotherm_genia_ebusd` folder into `/config/custom_components/`.
3. **Restart Home Assistant**.

---

## 4. Configure in Home Assistant

Setup is done entirely through the UI; no `configuration.yaml` edits are required.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=arotherm_genia_ebusd)

1. Go to **Settings → Devices & Services** (or use the button above).
2. Click **+ Add Integration** and search for **aroTHERM & GeniaAir (eBUS)**.
3. **Step 1 - Prerequisites Confirmation:** confirm that the repository CSV files, required `ebusd` flags, and `seed_mqtt_cfg: false` (for the HA add-on) are in place.
4. **Step 2 - MQTT & Manufacturer:**
   - **eBUSd MQTT topic prefix:** default `ebusd` (matching `--mqtttopic=ebusd/%circuit/%name`).
   - **Equipment manufacturer:** `Vaillant` or `Saunier Duval`.
5. **Step 3 - Hardware Models:**
   - **Outdoor unit (heat pump):** filtered by brand (e.g. `aroTHERM plus ES VWL 85/7.1 A 230V` or `GeniaAir Max ES 15`).
   - **Indoor hydraulic module:** filtered by brand (e.g. `VWZ MEH 97/7`, `uniTOWER VIH QW 190/7`, `HPIM 7 230V`, `GeniaSet FEW/FIW 200-7`).
   - **Wireless room thermostat (`04.netx3`):** enable if you have a wireless `sensoCOMFORT RF` / `MiPro Sense RF` room unit; disable for wired-only setups.
   - **Official cloud gateway (`f1`):** enable if a `myVAILLANT connect` / `MiGo Link` is on the bus (passive listening); disable otherwise (activates paced fallback `/get` polling).
6. **Step 4 - eBUSd TCP Connection (Optional):**
   - If the Home Assistant eBUSd add-on or a local eBUSd daemon is detected, the toggle, host (e.g. `b4d7ad18-ebusd`), and port (`8888`) are **automatically pre-filled**.
   - If eBUSd runs on another host/IP, you can enter its address and port here (verified before saving) — or simply **leave it disabled** to run over MQTT only. You can always enable or change it later in the integration's **Configure** options.
7. Click **Submit**. The staggered hydration queue populates all registers within about 60 seconds.

---

## 5. First-Run Verification

- Entities may show `Unknown` for the first 30-60 seconds: the coordinator waits `5.0 s` for retained MQTT payloads and then requests missing registers one at a time (`0.8 s` apart) to protect the bus. This is normal.
- Check that the four logical devices appear: **Outdoor Unit**, **Climate Controller**, **Hydraulic Interface** and, if enabled, **Wireless Room Thermostat**.
- Verify MQTT JSON output with:
  ```bash
  mosquitto_sub -h <MQTT_BROKER_IP> -u <USER> -P <PASS> -t "ebusd/#" -v
  ```
  Payloads should look like `ebusd/hmux0/RunDataFlowTemp {"value": {"value": 34.25}}`. If you see plain numbers, add `--mqttjson` to your `ebusd` flags and restart `ebusd`.

Next steps: [runtime options and Energy Dashboard](configuration.md) · [actions reference](services.md) · [troubleshooting](troubleshooting.md)

