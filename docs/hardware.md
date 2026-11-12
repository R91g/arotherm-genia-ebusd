# Supported Hardware

**🇬🇧 English** | [🇪🇸 Versión en Español](hardware_es.md)

Vaillant and Saunier Duval aerothermal heat pumps share the same eBUS electronic boards and register maps. During setup (or later via **Reconfigure**) you select the manufacturer so device names and model labels match your installation.

## Validation Status

The developer's reference installation is a `15.bass3` controller with an `08.hmux0` outdoor unit; those CSV definitions are exercised daily on that live hardware. The remaining boards (`15.basv3`, `15.ctlv2`, `15.ctlv3`, `08.hmu`, `08.hmu.HW5103`) are supported from their register maps and from community tester reports, and their definitions track the reference ones register by register. If you run any of these variants and something does not decode correctly, please open an issue with an anonymized [`dump_mqtt_values`](services.md#8-arotherm_genia_ebusddump_mqtt_values) capture.

## Outdoor Units - Heat Pumps (`08.hmux0` / `08.hmu`)

| Generation | Vaillant Models | Saunier Duval Models |
| :--- | :--- | :--- |
| **Current (`/7.1`, `/8.1` & UK `pro`)** | `aroTHERM plus ES VWL 55/7.1 A 230V`<br>`aroTHERM plus ES VWL 85/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 400V`<br>`aroTHERM plus ES VWL 155/7.1 A 230V`<br>`aroTHERM plus ES VWL 155/7.1 A 400V`<br>`aroTHERM pro 7.1` / `aroTHERM plus 8.1` | `GeniaAir Max ES 5`<br>`GeniaAir Max ES 8`<br>`GeniaAir Max ES 12`<br>`GeniaAir Max ES 15`<br>`GeniaAir Iso ES` |
| **Previous (`/6` & Max Legacy)** | `aroTHERM plus VWL 35/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 55/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 75/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 105/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 125/6 A (Legacy)` | `GeniaAir Max 4 (Legacy)`<br>`GeniaAir Max 6 (Legacy)`<br>`GeniaAir Max 8 (Legacy)`<br>`GeniaAir Max 11 (Legacy)`<br>`GeniaAir Max 15 (Legacy)` |

## Indoor Hydraulic Modules, Interfaces & Towers (`76.vwzio`)

| Component Type | Vaillant Models | Saunier Duval Models |
| :--- | :--- | :--- |
| **Wall Hydraulic Module (with backup heater)** | `VWZ MEH 97/7` | `HPIM 7 230V` / `Módulo Hidráulico HE 9-7 W` |
| **Wall Hydraulic Module / Appliance Interface** | `VWZ MH 97/7` / `VWZ AI 7/230V` | `HPIM 7 230V` |
| **All-in-One Hydraulic Tower (Integrated DHW)** | `uniTOWER VIH QW 190/7` | `GeniaSet FEW/FIW 200-7` |

## System Controllers & Optional Accessories

| Component Role | Vaillant Models | Saunier Duval Models | eBUS Address |
| :--- | :--- | :--- | :---: |
| **System Climate Controller (Required)** | `sensoCOMFORT VRC 720` (`720/2`, `720/3`) | `MiPro Sense SRC 720` (`720/2`, `720/3`) | `15` (`BASS3` / `BASV3` / `CTLV2` / `CTLV3`) |
| **Wireless Room Thermostat / RF Receiver (Optional)** | `sensoCOMFORT RF VRC 720f` (`NETX3` / `NETX2`) | `MiPro Sense RF SRC 720f` (`NETX3` / `NETX2`) | `04` / `f6` |
| **Official Cloud Gateway (Optional)** | `myVAILLANT connect VR 940f` / `sensoNET VR 921` | `MiGo Link SR 940f` | Master `f1` |

## Cloud Gateway Coexistence

An official gateway (`myVAILLANT connect` / `MiGo Link`) is **not required**. The integration combines passive listening with the scheduled reads that `ebusd` itself performs for the outdoor CSV registers marked `r1` (`RunDataElectricPowerConsumption`, with `PowerStatus` as fallback) and `r2` (`RunDataFlowTemp`, `RunDataReturnTemp`, `RunDataFlowRate`). On top of that: if a gateway is installed, the integration passively captures the telemetry it generates; if none is installed, disable the gateway toggle during setup and the integration adds a gentle fallback `/get` polling loop for core registers at a configurable interval (default `300 s`).

