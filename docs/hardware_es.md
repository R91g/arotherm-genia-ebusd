# Hardware Compatible

[🇬🇧 Read in English](hardware.md) | **🇪🇸 Español**

Las bombas aerotérmicas de Vaillant y Saunier Duval comparten las mismas placas electrónicas eBUS y mapas de registros. Durante la configuración (o más tarde mediante **Reconfigurar**) eliges el fabricante para que los nombres de dispositivo y las etiquetas de modelo coincidan con tu instalación.

## Estado de Validación

La instalación de referencia del desarrollador es un regulador `15.bass3` con unidad exterior `08.hmux0`; esas definiciones CSV se ejercitan a diario sobre ese hardware real. El resto de placas (`15.basv3`, `15.ctlv2`, `15.ctlv3`, `08.hmu`, `08.hmu.HW5103`) se soportan a partir de sus mapas de registros y de los informes de testers de la comunidad, y sus definiciones siguen registro a registro a las de referencia. Si usas alguna de estas variantes y algo no decodifica bien, abre un issue con una captura anonimizada de [`dump_mqtt_values`](services_es.md#8-arotherm_genia_ebusddump_mqtt_values).

## Unidades Exteriores - Bombas de Calor (`08.hmux0` / `08.hmu`)

| Generación | Modelos Vaillant | Modelos Saunier Duval |
| :--- | :--- | :--- |
| **Actual (`/7.1`, `/8.1` y UK `pro`)** | `aroTHERM plus ES VWL 55/7.1 A 230V`<br>`aroTHERM plus ES VWL 85/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 400V`<br>`aroTHERM plus ES VWL 155/7.1 A 230V`<br>`aroTHERM plus ES VWL 155/7.1 A 400V`<br>`aroTHERM pro 7.1` / `aroTHERM plus 8.1` | `GeniaAir Max ES 5`<br>`GeniaAir Max ES 8`<br>`GeniaAir Max ES 12`<br>`GeniaAir Max ES 15`<br>`GeniaAir Iso ES` |
| **Anterior (`/6` y Max Legacy)** | `aroTHERM plus VWL 35/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 55/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 75/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 105/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 125/6 A (Legacy)` | `GeniaAir Max 4 (Legacy)`<br>`GeniaAir Max 6 (Legacy)`<br>`GeniaAir Max 8 (Legacy)`<br>`GeniaAir Max 11 (Legacy)`<br>`GeniaAir Max 15 (Legacy)` |

## Módulos Hidráulicos Interiores, Interfaces y Torres (`76.vwzio`)

| Tipo de Componente | Modelos Vaillant | Modelos Saunier Duval |
| :--- | :--- | :--- |
| **Módulo Hidráulico Mural (con resistencia de apoyo)** | `VWZ MEH 97/7` | `HPIM 7 230V` / `Módulo Hidráulico HE 9-7 W` |
| **Módulo Hidráulico Mural / Interfaz** | `VWZ MH 97/7` / `VWZ AI 7/230V` | `HPIM 7 230V` |
| **Torre Hidráulica Todo-en-Uno (ACS integrada)** | `uniTOWER VIH QW 190/7` | `GeniaSet FEW/FIW 200-7` |

## Reguladores del Sistema y Accesorios Opcionales

| Rol del Componente | Modelos Vaillant | Modelos Saunier Duval | Dirección eBUS |
| :--- | :--- | :--- | :---: |
| **Regulador Climático (Obligatorio)** | `sensoCOMFORT VRC 720` (`720/2`, `720/3`) | `MiPro Sense SRC 720` (`720/2`, `720/3`) | `15` (`BASS3` / `BASV3` / `CTLV2` / `CTLV3`) |
| **Termostato Ambiente Inalámbrico / Receptor RF (Opcional)** | `sensoCOMFORT RF VRC 720f` (`NETX3` / `NETX2`) | `MiPro Sense RF SRC 720f` (`NETX3` / `NETX2`) | `04` / `f6` |
| **Pasarela Cloud Oficial (Opcional)** | `myVAILLANT connect VR 940f` / `sensoNET VR 921` | `MiGo Link SR 940f` | Maestro `f1` |

## Coexistencia con la Pasarela Cloud

Una pasarela oficial (`myVAILLANT connect` / `MiGo Link`) **no es necesaria**. La integración combina la escucha pasiva con las lecturas programadas que el propio `ebusd` realiza en la unidad exterior para los registros CSV marcados como `r1` (`RunDataElectricPowerConsumption`, con `PowerStatus` como respaldo) y `r2` (`RunDataFlowTemp`, `RunDataReturnTemp`, `RunDataFlowRate`). Además: si hay una pasarela instalada, la integración aprovecha pasivamente el tráfico que esta genera; si no la hay, desactiva la opción de pasarela durante la configuración y la integración añade un sondeo `/get` de respaldo suave para los registros básicos con intervalo configurable (por defecto `300 s`).

