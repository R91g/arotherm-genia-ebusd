<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/custom_components/arotherm_genia_ebusd/brand/icon.png" alt="aroTHERM & GeniaAir (eBUS)" width="150">
</p>

# aroTHERM & GeniaAir (eBUS) — Integración para Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/default)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-41BDF5.svg?style=for-the-badge)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-local__push-00B050.svg?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![Protocol](https://img.shields.io/badge/Protocol-eBUS%20%2F%20MQTT%20JSON-FF8C00.svg?style=for-the-badge)](https://github.com/john30/ebusd)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://github.com/R91g/arotherm-genia-ebusd/blob/main/LICENSE)

[🇬🇧 Read in English](README.md) | **🇪🇸 Español**

---

**aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) es una **integración personalizada 100 % local (`local_push`) e independiente de la nube para Home Assistant**, diseñada para bombas de calor aerotérmicas R290 de **Vaillant** y **Saunier Duval** gobernadas por reguladores **`sensoCOMFORT` (`VRC 720`)** o **`MiPro Sense` (`SRC 720`)** a través de [**eBUSd**](https://github.com/john30/ebusd).

Construida directamente sobre la arquitectura electrónica eBUS compartida por el Grupo Vaillant (`08.hmux0` / `08.hmu`, `15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3`, `76.vwzio`, `04.netx3` / `04.netx2`), sustituye el caos de entidades del auto-descubrimiento MQTT crudo y la dependencia de servidores externos por **185 entidades nativas fuertemente tipadas**, motor termodinámico y cálculo de COP/EER en tiempo real, filtrado de valores centinela de firmware, gestión automática del Doble Cerrojo de refrigeración, Quick Veto persistente en refrigeración, diagnósticos físicos TCP y algoritmo inteligente de ACS Puntual (Boost Forzado).

---

## Tabla de Contenidos

1. [¿Por qué control local por eBUS?](#por-qué-control-local-por-ebus)
2. [Hardware Compatible y Equivalencia entre Marcas](#hardware-compatible-y-equivalencia-entre-marcas)
3. [Características Principales y Arquitectura](#características-principales-y-arquitectura)
4. [Requisitos Previos](#requisitos-previos)
5. [Instalación Paso a Paso](#instalación-paso-a-paso)
   - [Paso 1: Desplegar los archivos CSV optimizados en eBUSd](#paso-1-desplegar-los-archivos-csv-optimizados-en-ebusd)
   - [Paso 2: Instalar la Integración (HACS o Manual)](#paso-2-instalar-la-integración-hacs-o-manual)
   - [Paso 3: Configurar en Home Assistant](#paso-3-configurar-en-home-assistant)
6. [Reconfiguración y Opciones en Caliente](#reconfiguración-y-opciones-en-caliente)
7. [Acciones Personalizadas (Servicios)](#acciones-personalizadas-servicios)
8. [Configuración en el Panel de Energía de Home Assistant](#configuración-en-el-panel-de-energía-de-home-assistant)
9. [Diagnósticos, Solución de Problemas y Preguntas Frecuentes](#diagnósticos-solución-de-problemas-y-preguntas-frecuentes)
10. [Referencia Técnica e Ingeniería Inversa](#referencia-técnica-e-ingeniería-inversa)
11. [Desarrollo y Pruebas](#desarrollo-y-pruebas)
12. [Agradecimientos y Proyectos de Referencia](#agradecimientos-y-proyectos-de-referencia)
13. [Licencia y Aviso Legal](#licencia-y-aviso-legal)

---

## ¿Por qué control local por eBUS?

| Capacidad | Integraciones Cloud (`myVAILLANT` / `MiGo Link`) | `ebusd` por defecto (`ebusd-configuration` + `mqtt-hassio.cfg`) | **aroTHERM & GeniaAir (eBUS)** |
| :--- | :---: | :---: | :---: |
| **Soporte CSV para Aerotermia R290 Moderna** | ✅ Nube propietaria | ❌ **CSV por defecto incompatibles** (hechos para calderas antiguas / VRC 700) | ✅ **CSV propios creados por ingeniería inversa y optimizados** |
| **Colisiones en el Bus Físico eBUS (2400 bps)** | ✅ Pasarela nativa (`f1`) | ❌ **Múltiples colisiones en el bus** por sondeo activo sin control | ✅ **Sin colisiones** (escucha pasiva `u` + arbitraje escalonado) |
| **Operación 100 % Local (Sin Internet)** | ❌ Depende de la nube | ✅ Local | ✅ **100 % Local (`local_push`)** |
| **Sin límites de peticiones / Caídas de API** | ❌ Sujeto a bloqueos/cuotas | ✅ Sin límites | ✅ **Push MQTT instantáneo** |
| **Jerarquía limpia de dispositivos** | ⚠️ Telemetría limitada | ❌ Cientos de entidades planas/crípticas | ✅ **4 dispositivos lógicos estructurados** |
| **Automatización Doble Cerrojo de Frío** | ✅ Gestionado en app oficial | ❌ Edición manual de registros/fechas | ✅ **Cerrojo 1 y Cerrojo 2 automáticos** |
| **Filtro Anti-Centinela de Consignas** | ✅ Oculto por la app oficial | ❌ Muestra picos de `5.0 °C` y `99.0 °C` | ✅ **Filtrado + memoria estacional** |
| **ACS Boost Inteligente (`ΔT < 5 K`)** | ❌ Bloqueado por histéresis de `5.0 K` | ❌ Bloqueado por histéresis de `5.0 K` | ✅ **Bypass automático de histéresis** |
| **Potencia Térmica y COP / EER en vivo** | ❌ Estimaciones diarias/mensuales | ❌ Registros aislados sin cálculo | ✅ **ΔT, W y COP/EER en vivo e histórico** |

---

## Hardware Compatible y Equivalencia entre Marcas

Los equipos de aerotermia de Vaillant y Saunier Duval comparten **al 100 % las mismas placas electrónicas eBUS y mapas de registros internos**. Al elegir el fabricante durante la instalación (o más adelante mediante **Reconfigurar**), la integración adapta automáticamente todos los nombres de dispositivos, modelos comerciales y denominaciones de controlador a tu equipo.

### 1. Unidades Exteriores — Bombas de Calor (`08.hmux0`)

| Generación | Modelos Comerciales Vaillant | Modelos Comerciales Saunier Duval | Refrigerante / Placa |
| :--- | :--- | :--- | :--- |
| **Generación Actual (`/7.1` ES e Internacional)** | `aroTHERM plus ES VWL 55/7.1 A 230V`<br>`aroTHERM plus ES VWL 85/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 400V`<br>`aroTHERM plus ES VWL 155/7.1 A 230V`<br>`aroTHERM plus ES VWL 155/7.1 A 400V` | `GeniaAir Max ES 5`<br>`GeniaAir Max ES 8`<br>`GeniaAir Max ES 12`<br>`GeniaAir Max ES 15`<br>`GeniaAir Iso ES` | R290 (`08.hmux0` / `08.hmu` / `08.hmu.HW5103`) |
| **Generación Previa (`/6` y `Max` Legacy)** | `aroTHERM plus VWL 35/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 55/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 75/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 105/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 125/6 A (Legacy)` | `GeniaAir Max 4 (Legacy)`<br>`GeniaAir Max 6 (Legacy)`<br>`GeniaAir Max 8 (Legacy)`<br>`GeniaAir Max 11 (Legacy)`<br>`GeniaAir Max 15 (Legacy)` | R290 (`08.hmux0` / `08.hmu`) |

### 2. Módulos Hidráulicos Interiores, Interfaces y Torres (`76.vwzio`)

| Tipo de Componente | Modelos Vaillant | Modelos Saunier Duval | Dirección eBUS |
| :--- | :--- | :--- | :---: |
| **Módulo Hidráulico Mural (con apoyo eléctrico)** | `VWZ MEH 97/7` | `HPIM 7 230V` / `Módulo Hidráulico HE 9-7 W` | `76` (`VWZIO`) |
| **Módulo Hidráulico / Interfaz de Bomba** | `VWZ MH 97/7` / `VWZ AI 7/230V` | `HPIM 7 230V` | `76` (`VWZIO`) |
| **Torre Hidráulica con Acumulador ACS Integrado** | `uniTOWER VIH QW 190/7` | `GeniaSet FEW/FIW 200-7` | `76` (`VWZIO`) |

### 3. Reguladores del Sistema y Accesorios Opcionales

| Rol del Componente | Modelos Vaillant | Modelos Saunier Duval | Dirección eBUS |
| :--- | :--- | :--- | :---: |
| **Controlador de Clima del Sistema (Requerido)** | `sensoCOMFORT VRC 720` (`720/2`, `720/3`) | `MiPro Sense SRC 720` (`720/2`, `720/3`) | `15` (`BASS3` / `BASV3` / `CTLV2` / `CTLV3`) |
| **Termostato Inalámbrico / Receptor RF (Opcional)** | `sensoCOMFORT RF VRC 720f` (`NETX3` / `NETX2`) | `MiPro Sense RF SRC 720f` (`NETX3` / `NETX2`) | `04` / `f6` |
| **Pasarela Oficial en Nube (Opcional — Sinergia Pasiva)** | `myVAILLANT connect VR 940f` / `sensoNET VR 921` | `MiGo Link SR 940f` | Maestro `f1` |

> **Nota:** **No es obligatorio** disponer de la pasarela oficial en la nube (`myVAILLANT connect` / `MiGo Link`). Si está conectada al bus, la integración aprovecha de forma pasiva sus lecturas periódicas sin inyectar tráfico adicional. Si no dispones de pasarela oficial, basta con desmarcar esa casilla en el asistente y la integración activará automáticamente un sondeo `/get` escalonado y libre de colisiones.

---

## Características Principales y Arquitectura

### 1. Arquitectura 100 % Autónoma sobre MQTT JSON Nativo (`local_push`)
- Se suscribe directamente al árbol JSON publicado por `ebusd` (`<mqtt_prefix>/#` con `--mqttjson`) y envía comandos selectivos de lectura (`/get`) y escritura (`/set`).
- **Independiente de `mqtt-hassio.cfg`:** No necesita el auto-descubrimiento MQTT de `ebusd` (`--mqttint`), manteniendo el registro de dispositivos de Home Assistant totalmente limpio y libre de entidades duplicadas o huérfanas.

### 2. Protección de Colisiones en Bus eBUS (2400 baudios) e Hidratación Escalonada
- El bus físico eBUS es un medio compartido CSMA/CD de 2 hilos a **2400 bps (~240 bytes/s)**. Un sondeo masivo simultáneo provoca tormentas de colisiones con el mando de pared.
- **Cola de Hidratación Inicial:** Al arrancar Home Assistant, el coordinador espera `5.0 s` para absorber a coste cero los mensajes `retained` del broker MQTT y solicita secuencialmente (con `0.8 s` de pausa entre tramas) **únicamente los registros que falten**.
- **Actualización Optimista y Confirmación Selectiva:** Las escrituras sobre registros pasivos `u` (consignas, modos, horarios, fechas) actualizan la interfaz al instante sin disparar lecturas `/get` redundantes que devuelvan valores antiguos en caché, espaciando las secuencias multipaso entre `0.3 s` y `0.6 s`.

### 3. 185 Entidades Nativas Agrupadas en 4 Dispositivos Lógicos

| Dispositivo Lógico | Circuito eBUS | Entidades Destacadas |
| :--- | :---: | :--- |
| **1. Unidad Exterior** (`<Modelo Exterior>`) | `08.hmux0` / `08.hmu` | Monitor operativo en vivo (52+ estados `S.xx`/`S.xxx`), velocidad (`r/s`) y modulación (`%`) del compresor, alta presión R290, pasos EEV, ventiladores, caudal primario, temperaturas de impulsión/retorno de alta precisión, contadores IEEE 754 (`EXP`) eléctricos, térmicos y de energía ambiental por modo (`Wh`), horas/arranques, niveles de reducción de ruido (modo silencioso) y **sensores termodinámicos y de energía total calculados**. |
| **2. Controlador de Clima** (`sensoCOMFORT` / `MiPro Sense`) | `15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3` | **Climatización Zona 1 (`climate`)**, **Agua Caliente Sanitaria (`water_heater`)**, curvas climáticas, límites de impulsión, puntos de bivalencia, presión de agua, integral de energía de calefacción (`EnergyIntegral`), contadores de energía por servicio (`PrEnergySumHc` / `PrEnergySumHwc`), resúmenes de programación semanal, programación antilegionella e interruptores de sistema. |
| **3. Interfaz Hidráulica** (`<Modelo Interior>`) | `76.vwzio` | Estado operativo del circuito secundario (calefacción, refrigeración, ACS, postcirculación, reposo), potencia eléctrica instantánea (`W`), contadores de energía `b5 16` (`Wh`), apoyo eléctrico auxiliar, diagnóstico de válvula de 3 vías / bomba secundaria y monitor de errores activos (`OK` o códigos de avería). |
| **4. Termostato Inalámbrico** *(Opcional)* | `04.netx3` / `04.netx2` / `f6` / `broadcast` | Temperatura en el dial inalámbrico, consigna inalámbrica, temperatura exterior por difusión (`Broadcast`) y fecha/hora del bus eBUS. *(Si no hay termostato inalámbrico instalado, los sensores broadcast se asocian automáticamente al Controlador de Clima).* |

**Desglose por Plataforma (185 entidades en total a través de 10 plataformas):**
- `climate` (**1**): Termostato unificado Calefacción / Refrigeración / Auto para Zona 1 con modos preestablecidos (`Programado (Confort)`, `Manual continuo`, `Eco (Reducción nocturna)`, `Anulación rápida (Quick Veto)` en calor y frío, `Modo Ausencia / Vacaciones`).
- `water_heater` (**1**): Control del depósito de Agua Caliente Sanitaria (ACS) (`Apagado`, `Programación horaria`, `Continuo (24h)`, `Boost`).
- `sensor` (**127**): Sensores de telemetría, matrices de energía en `Wh` (rendimientos eléctrico, térmico y ambiental en calefacción, frío, ACS y módulo auxiliar), cálculos termodinámicos y COP/EER, diagnósticos físicos del bus y de salud MQTT, detector de CSV faltantes y 5 sensores resumen de programación semanal (`heating`, `dhw`, `cooling`, `circulation`, `silent`).
- `binary_sensor` (**9**): Compresor en marcha, bomba primaria, desescarche activo, integración de energía activa, demanda de calor Zona 1, autorización hardware de refrigeración, ciclo de frío broadcast, señal física eBUS y apoyo eléctrico activo.
- `number` (**28**): Todos los parámetros numéricos de usuario e instalador (curva climática, sobretemperatura, impulsión mín./máx., corte de verano, consignas día/noche/manual/veto/frío/ausencia, consigna/histéresis/offset/tiempos de ACS, deltas de boost y duración de Quick Veto en calor y frío, puntos de bivalencia y humedad máxima).
- `select` (**6**): Modo calefacción Zona 1, modo refrigeración Zona 1, modo ACS, modo reducción nocturna (`eco`/`night`/`off`), control por temperatura ambiente (`off`/`modulating`/`thermostat`) y día semanal antilegionella (`off`/`Lunes`–`Domingo`).
- `switch` (**6**): Modo Ausencia (`Holiday Mode`), ACS Puntual (`Boost`), Autorización temporada de frío (`Cerrojo 1`), Curva de calefacción adaptativa, Carga paralela de ACS y calefacción, y Apagado global del sistema *(deshabilitado por defecto por seguridad)*.
- `datetime` (**4**): Controles interactivos de interfaz para Fecha/Hora de Inicio y Fin del Modo Ausencia (`datetime`), y Fecha/Hora de Inicio y Fin de Refrigeración Manual (`datetime`).
- `time` (**1**): Selector horario interactivo para la desinfección térmica semanal antilegionella (`HwcLegionellaTime`).
- `button` (**2**): Botones de acción en caliente para control del demonio eBUSd (`Recargar configuraciones CSV` y `Reiniciar escaneo de dispositivos`).

### 4. Climatización Zona 1: Filtro Anti-Centinela y Gestión Dual de Refrigeración
- **Filtrado Anti-Centinela de Firmware:**
  - Con la calefacción apagada (`Z1OpMode = off`), el regulador reporta `5.0 °C` (antihielo) en `Z1ActualRoomTempDesired`.
  - Con la refrigeración apagada (`Z1OpModeCooling = off`), reporta `99.0 °C` (`0000c642` en IEEE 754) en `Z1CoolingTempDesired`.
  - La integración filtra ambos valores centinela, memoriza de forma independiente las consignas reales de confort de invierno y verano entre reinicios de Home Assistant (`RestoreEntity`) y evita picos fuera de escala en las gráficas.
- **Gestión Transparente del Doble Cerrojo de Refrigeración y Modo Período por Calendario:**
  - Los reguladores Vaillant / Saunier Duval protegen el modo frío mediante dos bloqueos independientes: el **Cerrojo 1** (ventana de calendario `CoolingStartDate`–`CoolingEndDate`) y el **Cerrojo 2** (`Z1OpModeCooling`).
  - **Modo Indefinido Abierto (Por Defecto):** Al seleccionar **`Frío` (`Cool`)** en el termostato sin haber configurado fechas previas, la integración apaga calefacción, abre automáticamente el **Cerrojo 1** de forma indefinida (`01;01;26` a `01;01;99`), activa el **Cerrojo 2** (`Z1OpModeCooling = day`) y restaura tu consigna de verano guardada.
  - **Modo por Período de Calendario:** Si introduces fechas personalizadas desde los selectores interactivos `Fecha/Hora Inicio Frío Manual` y `Fecha/Hora Fin Frío Manual` (antes de encender el frío o mientras está activo), la integración programa tu ventana temporal exacta sin forzar el final abierto, limitando la refrigeración activa estrictamente a dicho intervalo.
  - Al volver a **`Calor` (`Heat`)** o **`Apagado` (`Off`)**, cierra automáticamente el **Cerrojo 1** al epoch `01;01;19` (idéntico al comportamiento de las apps oficiales `myVAILLANT` / `MiGo Link`) y restaura la consigna de invierno.
- **Quick Veto Unificado (Hardware en Calefacción + Persistente en Refrigeración):**
  - Al seleccionar `Anulación rápida (Quick Veto)` (o llamar a `arotherm_genia_ebusd.quick_veto`), activa el Quick Veto nativo por hardware en calefacción (`Z1QuickVetoStartTime` / `Z1QuickVetoDuration`) y un **Quick Veto sintético persistente** respaldado por almacenamiento en disco (`Store`) entre reinicios cuando la refrigeración está activa.
  - Ambos modos admiten deltas de boost configurables (`+3.0 °C` en calefacción / `-2.0 °C` en refrigeración por defecto) y restauran automáticamente el modo de funcionamiento y la consigna exactos previos al finalizar o cancelar, mientras que el **Modo Ausencia / Vacaciones** tiene prioridad absoluta, impide activarlo y cancela automáticamente cualquier Quick Veto de frío activo.

### 5. Agua Caliente Sanitaria (`water_heater`): ACS Boost Forzado Inteligente
- De fábrica, `sensoCOMFORT` / `MiPro Sense` aplica una histéresis estricta de carga (`CylinderChargeHyst = 5.0 K`). Si tu consigna de ACS es `50.0 °C` y el acumulador está a `47.0 °C`, activar la carga puntual estándar (`HwcSFMode = load`) **no arranca el compresor** porque `47.0 °C > (50.0 - 5.0) °C`.
- Con el **ACS Boost Forzado Inteligente** activado (por defecto):
  1. Cuando `T_depósito > (T_consigna - Histéresis)`, al activar **`Boost`** (desde la tarjeta `water_heater`, el interruptor **ACS Puntual (Boost)** o la acción `arotherm_genia_ebusd.force_dhw_boost`), el coordinador memoriza tu consigna actual, eleva temporalmente `HwcTempDesired` de forma dinámica a **`T_depósito + Histéresis + 1.5 °C`** (con tope en `68.0 °C`) y tras `1.0 s` envía `HwcSFMode = load`, garantizando el arranque inmediato del compresor sea cual sea tu consigna habitual (`45 °C`, `50 °C`, `55 °C`...).
  2. Supervisa continuamente la carga y **restaura automáticamente tu consigna original de ACS** en cuanto finaliza el ciclo (`HwcSFMode == auto`), se alcanza la temperatura objetivo, se cancela manualmente o vence el temporizador de seguridad de 60 minutos.

### 6. Motor Termodinámico y de Eficiencia COP / EER en Tiempo Real
Calculado automáticamente por el coordinador con cada actualización de telemetría de `08.hmux0` y `76.vwzio`:
```text
Salto Térmico Primario ΔT (K)   = T_impulsión (RunDataFlowTemp) - T_retorno (RunDataReturnTemp)
Potencia Térmica Instantánea    = Caudal (L/h) × |ΔT| (K) × 1.163   [Vatios]
COP / EER Instantáneo en Vivo   = Potencia_Térmica (W) / Potencia_Eléctrica (W)
COP / EER Histórico por Modo    = (Térmica_HMUX0_Wh + Térmica_VWZIO_Wh) / (Eléc_HMUX0_Wh + Eléc_VWZIO_Wh)
Consumo Eléctrico Total (Wh)    = Calefacción_Total_Wh + ACS_Total_Wh + Refrigeración_Total_Wh
```
*(Incluye puesta a cero durante desescarches y compresor en reposo para evitar falsos picos de COP por caudal residual de la bomba circuladora).*

### 7. Seguridad Táctil (`NumberMode.BOX`) e Identificadores `unique_id` Neutros
- **Seguridad Táctil:** Los controles `number` utilizan cajas numéricas con botones `+`/`-` (`NumberMode.BOX`) en lugar de barras deslizantes, evitando modificar por accidente la curva climática o los puntos de bivalencia al hacer scroll desde el móvil.
- **Reconfiguración sin Pérdida de Datos:** Todos los `unique_id` siguen estrictamente el patrón `{entry_id}_{circuito}_{mensaje}_{campo}`, sin cadenas de marca. Cambiar de fabricante o modelo mediante **Reconfigurar** conserva al 100 % las entidades, automatizaciones y estadísticas históricas.

### 8. Diagnóstico del Bus Físico por Socket TCP Directo (`ebusctl`) y Botones de Acción
Más allá del transporte telemétrico primario por MQTT, la integración incorpora un cliente asíncrono opcional de **conexión TCP directa** con el demonio `ebusd` (interfaz `ebusctl`, puerto `8888` por defecto):
- **Telemetría de Rendimiento del Bus Físico:** Extracción en tiempo real de métricas de bajo nivel que nunca se publican por MQTT: tasa de modulación en símbolos por segundo (`symbol rate`), latencia de arbitraje de línea en microsegundos (`arbitration latency`), latencia de respuesta del transceptor (`symbol latency`) y contador de reconexiones físicas (`reconnects`).
- **Detección Proactiva de Archivos CSV Faltantes:** El coordinador analiza la tabla de escaneo de dispositivos reportada por `ebusctl info`. Si una dirección física está activa en el bus pero no dispone de un archivo de configuración CSV enlazado (por ejemplo, una unidad exterior `HMU00` internacional o un regulador `CTLV2` cuando solo se desplegaron los CSV antiguos), el sensor `Dispositivos sin CSV` (`sensor.ebusd_missing_csv_devices`) pasa de `OK` a `Pending` y desglosa los identificadores hardware en sus atributos, alertándote proactivamente antes de que fallen las entidades.
- **Botones de Acción en Caliente:**
  - **Recargar Configuraciones CSV (`button.ebusd_reload_csv`):** Emite el comando `reload` por TCP para que `ebusd` vuelva a analizar los archivos CSV modificados sobre la marcha sin necesidad de reiniciar el contenedor o add-on.
  - **Reiniciar Escaneo de Dispositivos (`button.ebusd_restart_scan`):** Emite `scan full` para forzar la re-enumeración completa del bus físico.
- **Ciclo de Vida Dinámico en el Registro de Entidades:** Si la opción de diagnóstico TCP se desactiva en los ajustes de la integración, todos los sensores físicos y botones de acción se deshabilitan limpiamente en el Registro de Entidades de Home Assistant para no saturar la vista. Al activarla, se habilitan de inmediato.

### 9. Localización Trilingüe (ES / EN / DE) y Migración Transparente de Dispositivos
- **Paridad Trilingüe al 100 %:** Traducción completa y rigurosa en español, inglés y alemán (`es.json`, `en.json`, `de.json` y `strings.json`) cubriendo el 100 % de los nombres de entidades, descripciones de opciones avanzadas, parámetros de acciones y notificaciones de reparación.
- **Doble Registro del Esquema de Opciones:** Los campos del flujo de opciones se declaran simultáneamente en `sections.advanced_options` y en la raíz `step.init.data`, garantizando una presentación impecable tanto en interfaces modernas con secciones colapsables como en renderizadores clásicos de formularios planos.
- **Migración Transparente del Registro de Dispositivos:** El coordinador analiza automáticamente los dispositivos existentes al arrancar (`_async_migrate_legacy_device_names`), actualizando de forma transparente los nombres de sistema en español a identificadores estándar canónicos en inglés sin alterar jamás los nombres personalizados que el usuario haya establecido en la interfaz.

---

## Requisitos Previos

1. **Adaptador Físico eBUS:** Conectado en paralelo a los bornes de 2 hilos del bus eBUS (`+`/`-`, sin polaridad) de la máquina exterior, módulo hidráulico o mando mural — por ejemplo, [eBUS Adapter Shield v5 / C6](https://adapter.ebusd.eu/) (Ethernet, Wi-Fi o USB).
2. **Demonio `ebusd` (`v23.2` o superior):** Ejecutándose como **Add-on eBUSd en Home Assistant** o como servicio Linux / contenedor Docker, conectado a tu broker MQTT con el flag **`--mqttjson`** activado.
3. **Home Assistant (`2024.12.0` o superior):** Con la **[integración oficial MQTT](https://www.home-assistant.io/integrations/mqtt/)** configurada y conectada al mismo broker MQTT que `ebusd`.

### Esquema de Cableado Físico y Coexistencia eBUS

El eBUS es un bus serie diferencial de 2 hilos a 24V diseñado para interconectar todos los componentes de la instalación en paralelo. Puedes conectar tu adaptador eBUS en cualquier punto donde el bus esté accesible (unidad interior / torre hidráulica, unidad exterior o termostato).

<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/docs/images/ebus_wiring_diagram_es.svg" alt="Esquema de cableado eBUS" width="900">
</p>

#### Puntos Clave de Conexionado:
* **Borna `BUS (+ / -)` (Conector rojo):** Destinada a accesorios del sistema. En instalaciones estándar, aquí se conecta la pasarela oficial (`myVAILLANT connect` / `MiGo Link`). Puedes conectar el adaptador eBUS en paralelo en este mismo puerto (bien embornando ambos cables en el mismo conector o mediante un par de clemas WAGO 221).
* **Borna `X25 (A / B)` (Conector naranja):** Aquí entra la línea de comunicación eBUS que viene directamente de la unidad exterior (`aroTHERM plus` / `GeniaAir Max`).
* **Mismo carril eléctrico interno:** Los conectores `BUS` y `X25` están puenteados internamente en las pistas de la placa de circuito impreso; forman parte del mismo bus físico. Conectar el adaptador en `BUS` o en `X25` es completamente equivalente.
* **Sin polaridad:** El protocolo eBUS no tiene polaridad. Toda la electrónica (incluido el adaptador) cuenta con puentes rectificadores de entrada, por lo que no importa si inviertes los hilos (`+` con `-`, o `A` con `B`).
* **Coexistencia 100 % con el módem oficial:** Si tienes instalado `myVAILLANT connect` o `MiGo Link`, **no necesitas desconectarlo ni prescindir de él**. La integración convive pacíficamente en el mismo bus, aprovechando de forma pasiva las peticiones que ya realiza la pasarela oficial para reducir al mínimo el tráfico.

<details>
<summary>📸 <b>Ver fotografía de instalación real en placa hidráulica</b></summary>
<br>

<p align="center">
  <img src="https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/docs/images/real_installation_pcb.jpg" alt="Foto de instalación real en unidad interior" width="650">
  <br>
  <em>Instalación real dentro del cuadro eléctrico de una torre Saunier Duval GeniaSet / Vaillant uniTOWER. Se observa el adaptador eBUS C6 alimentado por USB-C en la parte inferior, conectado en paralelo con la pasarela oficial MiGo Link en la borna roja <code>BUS</code>, mientras que el bus de la unidad exterior entra por la borna naranja <code>X25 (A/B)</code>.</em>
</p>

</details>

---

## Instalación Paso a Paso

### Paso 1: Desplegar los archivos CSV optimizados en eBUSd

> **¿Por qué son imprescindibles los archivos CSV incluidos en este repositorio?**
> Los archivos CSV que vienen por defecto en `ebusd` (`ebusd.eu` / repositorio oficial `ebusd-configuration`) están diseñados para calderas antiguas y reguladores de generaciones previas (`VRC 700`) — **no son compatibles** con estos sistemas modernos de aerotermia R290 y además provocan **numerosas colisiones en el bus eBUS** debido a su sondeo activo indiscriminado.
>
> Todos los archivos incluidos en [`ebusd-configuration/`](ebusd-configuration/) han sido **desarrollados mediante ingeniería inversa y validados sobre hardware real** para las placas modernas `08.hmux0`, `15.bass3`, `76.vwzio` y `04.netx3`, decodificando con exactitud los contadores de energía R290 IEEE 754 (`EXP`), las programaciones semanales `b5 55`, los registros del Doble Cerrojo de refrigeración y los más de 52 estados `HMUStatusCode`, priorizando la captura pasiva de tramas `u` para garantizar **cero colisiones** en el bus.

Copia los archivos CSV en el directorio de configuración de `ebusd` respetando exactamente esta estructura de carpetas:

```text
<raiz-config-ebusd>/en/
├── broadcast.csv              <-- DEBE ir en la raíz de en/ (NUNCA dentro de vaillant/)
└── vaillant/
    ├── 04.netx3.csv           <-- Receptor radio del termostato inalámbrico (NETX3 / NETX2)
    ├── 08.hmu.csv             <-- Placa unidad exterior (variantes internacionales / HMU00)
    ├── 08.hmu.HW5103.csv      <-- Placa unidad exterior (prioridad para HW=5103)
    ├── 08.hmux0.csv           <-- Placa unidad exterior (aroTHERM plus / GeniaAir Max)
    ├── 15.bass3.csv           <-- Controlador de clima (MiPro Sense SRC 720 / sensoCOMFORT VRC 720)
    ├── 15.basv3.csv           <-- Controlador de clima (sensoCOMFORT VRC 720 que reporta BASV3)
    ├── 15.ctlv2.csv           <-- Controlador de clima (sensoCOMFORT VRC 720/2)
    ├── 15.ctlv3.csv           <-- Controlador de clima (sensoCOMFORT VRC 720/3)
    ├── 76.vwzio.csv           <-- Módulo o torre hidráulica (VWZ MEH / uniTOWER / HPIM 7 / GeniaSet)
    └── f6.netx3.csv           <-- Tramas RF pasivas del termostato inalámbrico
```

#### Opción A: Add-on eBUSd en Home Assistant
1. Copia `ebusd-configuration/broadcast.csv` en:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/broadcast.csv`
2. Copia todos los archivos de `ebusd-configuration/vaillant/*.csv` en:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/vaillant/`
3. En los ajustes del Add-on (**Ajustes → Complementos → eBUSd → Configuración**):
   - **Desactiva la opción "Seed HA MQTT integration config (only needed once)"** (`seed_mqtt_cfg: false`).
     > **¿Por qué es IMPRESCINDIBLE desactivar esta opción?**
     > Si se deja activada (comportamiento predeterminado del add-on), eBUSd copia e inyecta la plantilla `mqtt-hassio.cfg` con la directiva `filter-seen = 5`. Esto obliga a eBUSd a sondear continuamente ~160 registros en crudo cada 16 minutos, saturando el bus físico eBUS a 2400 baudios con colisiones y errores de timeout, además de crear cientos de entidades MQTT huérfanas y duplicadas en Home Assistant. Al desactivarla, el sondeo queda estrictamente controlado por nuestros CSV optimizados (solo 20 registros limpios) y Home Assistant se mantiene limpio.
     >
     > *(Consejo: Si el add-on ya se había iniciado anteriormente con `seed_mqtt_cfg` activado, elimina los dispositivos MQTT huérfanos creados por ebusd en **Ajustes → Dispositivos y servicios → MQTT**).*
   - **Añade los argumentos de arranque en `commandline_options` (uno por línea):**
     ```text
     --mqttjson
     --configpath=/config/ebusd-configuration/en
     --scanconfig
     --accesslevel=*
     --mqtttopic=ebusd/%circuit/%name
     --mqttvar=filter-direction=r|u|^w
     ```
     > **CRÍTICO: ¡Añade explícitamente `--mqttjson`!**
     > Cuando `Seed HA MQTT integration config` está activado, el add-on añade automáticamente `--mqttjson` por debajo. Al desactivar dicha opción, el add-on **deja de añadir `--mqttjson` de forma automática**. Dado que esta integración requiere que eBUSd publique en formato JSON, **debes incluir obligatoriamente `--mqttjson`** en la lista de `commandline_options`.
     >
     > **¿Qué hace cada parámetro?**
     > - `--mqttjson`: Publica los mensajes en formato JSON enriquecido (`{"value": ...}`), requerido por la integración.
     > - `--configpath=/config/ebusd-configuration/en`: Carga los archivos CSV optimizados de este repositorio en lugar de los obsoletos descargados por defecto de internet.
     > - `--scanconfig`: Escanea el bus eBUS al arrancar y empareja automáticamente las placas (`08`, `15`, `76`, `04`) con sus respectivos CSV.
     > - `--accesslevel=*`: Imprescindible para permitir la lectura y escritura de parámetros avanzados e instalador (curvas de calefacción, límites, bivalencia).
     > - `--mqtttopic=ebusd/%circuit/%name`: Publica cada mensaje en el tópico estándar esperado por el coordinador de Home Assistant.
     > - `--mqttvar=filter-direction=r|u|^w`: **Imprescindible para habilitar la escritura.** Permite explícitamente enviar órdenes de escritura (`^w`) para consignas, curvas y modos.
     > - *(Nota: Parámetros como `--enablehex` no son necesarios salvo para depuración de bytes en crudo por terminal. Asimismo, se omite `--pollinterval` en los argumentos para que eBUSd aplique su valor predeterminado de 5 segundos (`--pollinterval=5`), intervalo sobre el cual están calibradas las prioridades de lectura `r` de nuestros archivos CSV).*
4. Reinicia el add-on **eBUSd** y comprueba en su registro de arranque que detecta y carga `08.hmux0` (o `08.hmu`), `15.bass3` (o `15.basv3` / `15.ctlv2` / `15.ctlv3`) y `76.vwzio`.

#### Opción B: `ebusd` en Servidor Linux Independiente o Docker
1. Copia `ebusd-configuration/broadcast.csv` en `/etc/ebusd/en/broadcast.csv` (o en el volumen mapeado de Docker).
2. Copia `ebusd-configuration/vaillant/*.csv` en `/etc/ebusd/en/vaillant/`.
3. Añade en `/etc/default/ebusd` (`EBUSD_OPTS`) o en el comando de tu `docker-compose.yml`:
   ```text
   --configpath=/etc/ebusd/en --scanconfig --accesslevel=* --mqttjson --mqtttopic=ebusd/%circuit/%name --mqttvar=filter-direction=r|u|^w --mqtthost=<IP_BROKER> --mqttport=1883 --mqttuser=<USUARIO> --mqttpass=<CLAVE>
   ```
4. Reinicia el servicio (`sudo systemctl restart ebusd` o `docker compose restart ebusd`).

---

### Paso 2: Instalar la Integración (HACS o Manual)

#### Método A: Instalación mediante HACS (Recomendado)

Pulsa el siguiente botón para abrir directamente la ficha de la integración en HACS dentro de tu instancia de Home Assistant:

[![Abrir tu instancia de Home Assistant y mostrar la integración en HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=R91g&repository=arotherm-genia-ebusd&category=integration)

O búscalo directamente en HACS:

1. Abre **HACS** en la barra lateral de Home Assistant.
2. En el buscador superior, escribe **`aroTHERM & GeniaAir (eBUS)`** (o `arotherm_genia_ebusd`).
3. Entra en la ficha de la integración y pulsa **Descargar** (*Download*) en la esquina inferior derecha.
4. **Reinicia Home Assistant** (**Ajustes → Sistema → Reiniciar**) para que cargue la integración.

> [!NOTE]
> Al estar incluida en el repositorio oficial predeterminado de HACS, **no es necesario** añadir ningún repositorio personalizado.

#### Método B: Instalación Manual

1. Descarga la última versión publicada (o clona este repositorio).
2. Copia la carpeta `custom_components/arotherm_genia_ebusd` dentro del directorio `/config/custom_components/` de tu Home Assistant:
   ```text
   /config/custom_components/arotherm_genia_ebusd/
   ```
3. **Reinicia Home Assistant**.

---

### Paso 3: Configurar en Home Assistant

Toda la configuración se realiza mediante asistente gráfico desde la interfaz de Home Assistant (sin tocar `configuration.yaml`):

[![Abrir tu instancia de Home Assistant e iniciar la configuración de una nueva integración.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=arotherm_genia_ebusd)

1. Ve a **Ajustes → Dispositivos y servicios** (o pulsa en el botón superior de My Home Assistant).
2. Pulsa **+ Añadir integración** abajo a la derecha y busca **aroTHERM & GeniaAir (eBUS)**.
3. **Paso 1 — Conexión MQTT y Fabricante:**
   - **Prefijo del tópico MQTT en eBUSd:** Por defecto `ebusd` (coincidente con `--mqtttopic=ebusd/%circuit/%name`).
   - **Fabricante del equipo:** Selecciona **`Vaillant`** o **`Saunier Duval`**.
4. **Paso 2 — Modelos de Hardware Instalado:**
   - **Modelo de unidad exterior (Bomba de Calor):** Filtrado automáticamente según la marca elegida (p. ej. `aroTHERM plus ES VWL 85/7.1 A 230V` o `GeniaAir Max ES 15`).
   - **Modelo de interfaz / módulo hidráulico interior:** Filtrado según la marca (p. ej. `VWZ MEH 97/7`, `uniTOWER VIH QW 190/7`, `HPIM 7 230V`, `GeniaSet FEW/FIW 200-7`).
   - **Termostato de ambiente inalámbrico (`04.netx3`):** Déjalo marcado si tienes mando de ambiente por radio (`sensoCOMFORT RF` / `MiPro Sense RF`); desmárcalo si tu instalación es exclusivamente cableada.
   - **Pasarela oficial en nube (`MiGo Link` / `myVAILLANT connect` en eBUS `f1`):** Déjalo marcado si tienes pasarela oficial conectada al bus (escucha pasiva sin tráfico extra); desmárcalo si no tienes pasarela oficial (activa el sondeo `/get` escalonado de respaldo).
5. Pulsa **Enviar**. En aproximadamente 60 segundos, la cola de hidratación inicial poblará todos los registros de tus 4 dispositivos.

---

## Reconfiguración y Opciones en Caliente

### Cambiar de Marca o Modelo Más Adelante (`Reconfigurar`)
Si en cualquier momento deseas cambiar el modelo de unidad exterior/interior, alternar entre etiquetas de Vaillant y Saunier Duval o añadir/quitar el termostato inalámbrico o la pasarela en nube:
- Ve a **Ajustes → Dispositivos y servicios → aroTHERM & GeniaAir (eBUS)**, abre el **menú de tres puntos (`⋮`)** junto a la entrada y pulsa **Reconfigurar**.
- Los nombres y especificaciones de los dispositivos se actualizarán en vivo conservando **el 100 % de los IDs de entidad y el historial estadístico**.

### Ajuste de Algoritmos en Tiempo Real (`Configurar`)
Pulsa el botón **Configurar** dentro de la tarjeta de la integración en **Ajustes → Dispositivos y servicios** para modificar su comportamiento al vuelo sin reiniciar Home Assistant:

| Opción | Por defecto | Rango | Descripción |
| :--- | :---: | :---: | :--- |
| **Activar ACS Boost Forzado Inteligente** (`force_dhw_boost`) | `True` | Sí / No | Eleva dinámicamente `HwcTempDesired` a `T_actual + Histéresis + 1.5 °C` cuando `ΔT < Histéresis` durante una carga puntual de ACS, restaurando la consigna original automáticamente al terminar. |
| **Abrir automáticamente el Cerrojo 1 de refrigeración** (`auto_cooling_lock_bypass`) | `True` | Sí / No | Escribe automáticamente `CoolingStartDate = 01;01;26` y `CoolingEndDate = 01;01;99` al activar el modo `Frío`, y vuelve a cerrarlo en `01;01;19` al pasar a `Calor` o `Apagado`. |
| **Intervalo de sondeo `/get` de respaldo** (`fallback_poll_interval`) | `300 s` | `60` – `3600 s` | Frecuencia del sondeo activo suave de registros principales. **Solo actúa cuando la opción de pasarela oficial en nube (`f1`) está desactivada.** |
| **Habilitar diagnósticos eBUSd por TCP** (`enable_ebusd_tcp`) | `False` | Sí / No | Permite realizar consultas asíncronas directas a `ebusd` (`ebusctl`, puerto `8888`) para extraer métricas físicas del bus, estado de escaneo, alertas de CSV faltantes y botones de control del demonio. |
| **Host TCP de eBUSd** (`ebusd_tcp_host`) | `127.0.0.1` | Nombre / IP | Dirección IP o nombre de host de la máquina o contenedor donde corre `ebusd` (ej. `127.0.0.1` o `core-ebusd`). |
| **Puerto TCP de eBUSd** (`ebusd_tcp_port`) | `8888` | `1` – `65535` | Puerto TCP donde `ebusd` acepta conexiones `ebusctl` (por defecto: `8888`). |

---

## Acciones Personalizadas (Servicios)

La integración registra **12 acciones personalizadas** bajo el dominio `arotherm_genia_ebusd`, disponibles en **Herramientas para desarrolladores → Acciones** y en Automatizaciones / Scripts.

### 1. `arotherm_genia_ebusd.set_weekly_timer`

[![Abrir tu instancia de Home Assistant y mostrar las herramientas de desarrollo de servicios.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.set_weekly_timer)

Modifica o borra las programaciones horarias semanales nativas (`b5 55`) directamente en la memoria del regulador `sensoCOMFORT` / `MiPro Sense` (`15.bass3` / `15.ctlv2` / `15.ctlv3`), sincronizando en el bus el contador de ranuras activas y aplicando automáticamente un espaciado de `600 ms` entre días para proteger el bus eBUS.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit_type` | Sí | `heating`, `dhw`, `cooling`, `circulation`, `silent` | Circuito horario a modificar: `heating` (Calefacción / `Z1Timer`), `dhw` (ACS / `HwcTimer`), `cooling` (Refrigeración / `CoolingTimer`), `circulation` (Recirculación / `CirculationTimer`) o `silent` (Modo silencioso / `SilentTimer`). |
| `day` | Sí | `Monday`..`Sunday`, `Weekdays`, `Weekend`, `All`<br>*(o en español: `Lunes`..`Domingo`, `Laborables`, `Fin de semana`, `Todos`)* | Día específico, días laborables L–V (`Weekdays` / `Laborables`), fin de semana S–D (`Weekend` / `Fin de semana`) o toda la semana L–D (`All` / `Todos`). |
| `action` | No | `set`, `delete`, `clear` *(por defecto: `set`)* | Acción a realizar:<br>• `set`: crea o modifica la franja horaria indicada.<br>• `delete`: elimina la ranura especificada y desplaza las posteriores de forma contigua.<br>• `clear`: vacía el día completo fijando 0 ranuras activas. |
| `slot` | No | `1`, `2`, `3` *(por defecto: `1`)* | Ranura horaria diaria (`1` a `3`). Se ignora si `action: clear`. |
| `start_time` | Opcional* | `"HH:MM"` *(ej. `"13:10"`)* | Hora de inicio en formato 24h (resolución de 1 minuto). *Requerido si `action: set`. |
| `end_time` | Opcional* | `"HH:MM"` *(ej. `"15:30"` o `"24:00"`)* | Hora de fin en formato 24h (utilizar `"24:00"` para programar el día completo). *Requerido si `action: set`. |
| `temp` | No | `5.0` – `80.0` *(°C)* | Consigna opcional para esa franja. Aplica solo a `heating`, `dhw` y `cooling` (se ignora en `circulation` y `silent`). Si se omite, mantiene la temperatura objetivo activa del circuito (p. ej. 50 °C en ACS o 20 °C en Calefacción). |
| `reset_remaining` | No | `true`, `false` *(por defecto: `false`)* | Si se activa junto a `slot: 1` en modo `set`, sobrescribe el día fijando exactamente 1 ranura activa (`total_slots = 1`) y elimina las ranuras 2 y 3 existentes, sin requerir lectura previa de telemetría de la línea eBUS. |

#### Ejemplos de Configuración y Automatización

**Ejemplo 1 — Configurar 1 franja horaria de ACS para toda la semana (con `reset_remaining: true` para inicializar el día):**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Todos             # o "All"
  slot: 1
  start_time: "13:00"
  end_time: "15:30"
  reset_remaining: true  # Establece 1 única ranura activa y reinicia ranuras 2 y 3
```

**Ejemplo 2 — Programar las 24 horas continuas (Todo el día) en Calefacción Zona 1:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: heating
  day: Todos             # o "All"
  slot: 1
  start_time: "00:00"
  end_time: "24:00"      # Formato nativo eBUS para 24 horas continuas
  temp: 20.5
  reset_remaining: true  # 1 única franja activa para todo el día
```

**Ejemplo 3 — Añadir una segunda franja (Slot 2) los fines de semana en Calefacción Zona 1:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: heating
  day: Fin de semana     # o "Weekend"
  slot: 2
  start_time: "17:00"
  end_time: "22:00"
  temp: 21.0
```

**Ejemplo 4 — Borrar una ranura específica (Slot 2) un día concreto:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Lunes             # o "Monday"
  action: delete
  slot: 2
```

**Ejemplo 5 — Vaciar completamente la programación de un día (0 franjas activas):**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Lunes             # o "Monday"
  action: clear
```

### 2. `arotherm_genia_ebusd.force_dhw_boost`

[![Abrir tu instancia de Home Assistant y mostrar las herramientas de desarrollo de servicios.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.force_dhw_boost)

Inicia inmediatamente una carga puntual del depósito de ACS (`HwcSFMode = load`) utilizando el algoritmo de bypass de histéresis, permitiendo indicar opcionalmente una temperatura objetivo específica para ese ciclo (ideal para aprovechamiento de excedentes fotovoltaicos).

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `boost_temp` | No | `40.0` – `68.0` *(°C)* | Consigna temporal opcional para este ciclo concreto (p. ej. `60.0 °C` para excedentes solares). Si se omite, calcula automáticamente `T_actual + Histéresis + 1.5 °C`. |

**Ejemplo de Automatización — Calentar el acumulador de ACS a 60 °C cuando el excedente solar supere 2.5 kW:**
```yaml
action: arotherm_genia_ebusd.force_dhw_boost
data:
  boost_temp: 60.0
```

### 3. `arotherm_genia_ebusd.set_legionella_protection`
Configura la programación semanal de desinfección térmica antilegionella (`HwcLegionellaDay` y `HwcLegionellaTime`) en el regulador climático (`15.bass3` / `15.ctlv2` / `15.ctlv3`).

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `day` | Sí | `off`, `Monday`..`Sunday`<br>*(o `desactivado`, `Lunes`..`Domingo`, `'0'`..`'7'`)* | Día de la semana programado para el ciclo semanal antilegionella, o `off` para desactivarlo. |
| `time` | No | `"HH:MM"` *(ej. `"04:00"`)* | Hora de ejecución en formato 24h. Por defecto `"04:00"` al activar un día válido. |

**Ejemplo de Automatización — Programar ciclo antilegionella todos los domingos a las 03:30:**
```yaml
action: arotherm_genia_ebusd.set_legionella_protection
data:
  day: Domingo
  time: "03:30"
```

### 4. `arotherm_genia_ebusd.set_holiday_mode`
Activa el Modo Ausencia / Vacaciones (`PRESET_AWAY`) en el regulador `MiPro Sense`, suspendiendo la producción de ACS y reduciendo la calefacción a la temperatura de mantenimiento seleccionada durante una ventana temporal específica o de forma indefinida.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `5.0` – `24.0` *(°C)* | Consigna de temperatura ambiente durante la ausencia (por defecto: `15.0 °C`). |
| `start_date` | No | `AAAA-MM-DD` / `DD/MM/AAAA` | Fecha de inicio de la ausencia (por defecto: hoy). |
| `start_time` | No | `HH:MM` | Hora de inicio de la ausencia (por defecto: hora actual). |
| `end_date` | No | `AAAA-MM-DD` / `DD/MM/AAAA` | Fecha de regreso. Si se omite, el modo permanece activo indefinidamente hasta su cancelación manual. |
| `end_time` | No | `HH:MM` | Hora de regreso (por defecto: `23:59`). |

**Ejemplo de Automatización — Salida de vacaciones hasta el 10 de noviembre con protección antihielo a 12 °C:**
```yaml
action: arotherm_genia_ebusd.set_holiday_mode
data:
  temperature: 12.0
  end_date: "2026-11-10"
  end_time: "18:00"
```

### 5. `arotherm_genia_ebusd.cancel_holiday_mode`
Cancela inmediatamente el Modo Ausencia en `15.bass3` y restablece el funcionamiento automático habitual en calefacción y ACS. No requiere parámetros.

```yaml
action: arotherm_genia_ebusd.cancel_holiday_mode
```

### 6. `arotherm_genia_ebusd.quick_veto`
Activa **Quick Veto (Boost)** en Zona 1 (`15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3`) para anular temporalmente la programación, la consigna manual o el estado apagado durante un tiempo limitado. Aplica Quick Veto nativo por hardware en calefacción y Quick Veto sintético persistente (`Store`) cuando la refrigeración está activa.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `10.0` – `30.0` *(°C en calor)*<br>`15.0` – `30.0` *(°C en frío)* | Temperatura objetivo temporal opcional. Si se omite, aplica el delta de boost configurado (por defecto: `+3.0 °C` en calefacción, `-2.0 °C` en refrigeración). |
| `duration` | No | `0.5` – `12.0` *(horas)* | Duración de la anulación en horas. Si se omite, utiliza la duración configurada (`Z1QuickVetoDuration`, por defecto: `3.0 h`). |

**Ejemplo de Automatización — Lanzar un boost de confort de 2.5 horas a 22.5 °C en Zona 1:**
```yaml
action: arotherm_genia_ebusd.quick_veto
data:
  temperature: 22.5
  duration: 2.5
```

### 7. `arotherm_genia_ebusd.cancel_quick_veto`
Cancela inmediatamente cualquier Quick Veto activo (de calefacción o de refrigeración) en Zona 1 y restaura exactamente el modo de funcionamiento y la consigna anteriores. No requiere parámetros.

```yaml
action: arotherm_genia_ebusd.cancel_quick_veto
```

### 8. `arotherm_genia_ebusd.dump_mqtt_values`
Vuelca directamente en las Herramientas para desarrolladores de Home Assistant (`SupportsResponse.ONLY`) el estado completo de la instalación, circuitos activos, modelos detectados y todas las variables eBUS recibidas. Ideal para adjuntar capturas de estado al abrir incidencias en GitHub o diagnosticar problemas de bus.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | No | Texto *(ej. `"08"`, `"15"`, `"hmu"`)* | Filtro opcional por subcadena para limitar el volcado a circuitos específicos. Si se omite, vuelca todos los circuitos activos. |
| `anonymize` | No | Booleano *(por defecto: `true`)* | Enmascara automáticamente los números de serie largos de fabricación (28 caracteres) para compartir el volcado de forma segura y privada en incidencias públicas de GitHub. |

### 9. `arotherm_genia_ebusd.record_topic_changes`
Graba en vivo todo el tráfico MQTT publicado bajo el prefijo de eBUSd durante una ventana temporal configurable (`SupportsResponse.ONLY`). Registra marcas temporales, tópicos, datos decodificados en JSON y marcas de retención (*retained*), permitiendo trazar interacciones físicas con el regulador sin necesidad de acceder por SSH.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `duration` | No | `5` – `120` *(segundos, por defecto: `30`)* | Intervalo de tiempo para grabar el tráfico MQTT entrante. |
| `circuit` | No | Texto *(ej. `"08"`, `"15"`)* | Filtro opcional por subcadena para capturar únicamente los mensajes que coincidan con un tópico o circuito. |

### 10. `arotherm_genia_ebusd.send_hex_command`
Envía un comando hexadecimal en crudo directamente al demonio `ebusd` a través de su socket TCP (puerto 8888) y devuelve los bytes de respuesta (`SupportsResponse.ONLY`). Ideal para explorar y diagnosticar registros no documentados sin editar archivos CSV ni requerir acceso por terminal SSH. Requiere que `ebusd` se haya iniciado con el parámetro de seguridad `--enablehex`.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `command` | Sí | Cadena hexadecimal *(ej. `"08b51a0405ff3428"`)* | Secuencia de bytes hexadecimales a enviar (los espacios se eliminan automáticamente). |
| `host` | No | Texto *(por defecto: `"127.0.0.1"`)* | Dirección IP o nombre de host donde corre `ebusd` (ej. `core-ebusd` o IP externa). |
| `port` | No | Entero *(por defecto: `8888`)* | Puerto TCP de comandos de `ebusd`. |
| `timeout` | No | Decimal *(por defecto: `5.0`)* | Tiempo máximo de espera en segundos para conectar y recibir respuesta. |

### 11. `arotherm_genia_ebusd.read_parameter`
Lee un registro simbólico de eBUSd a través de MQTT (`SupportsResponse.ONLY`). Publica un payload vacío a `<prefijo>/<circuito>/<nombre>/get` y espera la respuesta decodificada en JSON. Permite consultar la caché local u obligar a una lectura física activa en el bus.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | Sí | Texto *(ej. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`)* | Identificador o alias del circuito eBUS. |
| `name` | Sí | Texto *(ej. `"CompressorSilentOperationLevel"`, `"Status01"`)* | Nombre simbólico del mensaje o parámetro definido en los CSVs. |
| `force` | No | Booleano *(por defecto: `false`)* | Si es `true`, fuerza una consulta activa al bus en lugar de devolver el valor en caché. |
| `timeout` | No | Decimal *(por defecto: `5.0`)* | Tiempo máximo de espera en segundos para recibir la respuesta MQTT. |

### 12. `arotherm_genia_ebusd.write_parameter`
Escribe un valor en un registro simbólico de eBUSd a través de MQTT (`SupportsResponse.OPTIONAL`). Publica el payload a `<prefijo>/<circuito>/<nombre>/set`, aplica una actualización optimista inmediata en la interfaz y aprovecha el enrutamiento inteligente de circuitos y confirmaciones.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | Sí | Texto *(ej. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`)* | Identificador o alias del circuito eBUS. |
| `name` | Sí | Texto *(ej. `"CompressorSilentOperationLevel"`, `"Z1OpMode"`)* | Nombre simbólico del mensaje o parámetro definido en los CSVs. |
| `value` | Sí | Texto / Número / Booleano | Valor que se enviará en el payload de escritura a eBUSd. |

---

## Configuración en el Panel de Energía de Home Assistant

La integración proporciona sensores acumulativos `TOTAL_INCREASING` con precisión sub-kWh (`Wh`, IEEE 754 `EXP`) que suman automáticamente la unidad exterior (`08.hmux0`) y el módulo hidráulico interior (`76.vwzio`), diseñados específicamente para la jerarquía padre/hijo de **Dispositivos individuales** del Panel de Energía de Home Assistant (`Padre == Calefacción + ACS + Refrigeración`, evitando cualquier duplicidad de consumos):

1. Ve a **Ajustes → Paneles de control → Energía → Dispositivos individuales** y pulsa **Añadir dispositivo**.
2. **Añade el Dispositivo Padre (Consumo Total Aerotermia):**
   - Selecciona **`Consumo eléctrico total aerotermia`** (`calculated_system_total_energy`, en `Wh`, perteneciente al dispositivo **Unidad Exterior**).
   - Asígnale un nombre descriptivo (p. ej. `Aerotermia (Total)`).
3. **Añade los 3 Sub-dispositivos Hijos** (seleccionando en **`Dispositivo superior / Incluido en`** → `Consumo eléctrico total aerotermia` en cada uno):
   - **Calefacción:** `Consumo eléctrico total calefacción` (`calculated_heating_total_energy`, en `Wh`, en el dispositivo Unidad Exterior).
   - **Agua Caliente Sanitaria (ACS):** `Consumo eléctrico total ACS` (`calculated_dhw_total_energy`, en `Wh`, en el dispositivo Unidad Exterior).
   - **Refrigeración:** `Consumo eléctrico total refrigeración` (`energy_electric_cool`, en `Wh`, en el dispositivo Unidad Exterior).

Home Assistant calculará automáticamente los consumos por hora, día, mes y año a partir de estos contadores hardware en `Wh`, agrupando los tres servicios bajo un desplegable `>` dentro del dispositivo padre y mostrando el desglose exacto de **Calefacción vs. ACS vs. Refrigeración** en las barras de consumo y el diagrama de Sankey sin contabilizar ningún vatio-hora dos veces. *(Los contadores individuales de `08.hmux0` frente a `76.vwzio` siguen disponibles en la sección Diagnóstico por si deseas consultar qué parte corresponde al compresor y cuál al módulo hidráulico).*

---

## Diagnósticos, Solución de Problemas y Preguntas Frecuentes

### Descarga de Diagnósticos Sanitizados
Para adjuntar información técnica en un reporte o inspeccionar los JSON en caché recibidos desde `ebusd`, ve a **Ajustes → Dispositivos y servicios → aroTHERM & GeniaAir (eBUS) → `⋮` → Descargar diagnósticos**. Los datos sensibles del tópico MQTT se anonimizan automáticamente.

### Preguntas Frecuentes (FAQ)

<details>
<summary><b>1. ¿Por qué algunas entidades aparecen como <code>Desconocido</code> durante los primeros 30–60 segundos tras reiniciar Home Assistant?</b></summary>

Es el comportamiento previsto para proteger el bus físico eBUS (2400 baudios) frente a colisiones. Al iniciar, el coordinador espera `5.0 s` para recibir mensajes `retained` de MQTT y a continuación solicita uno a uno los registros restantes cada `0.8 s`. Todos los sensores activos quedan poblados en ~1 minuto.
</details>

<details>
<summary><b>2. He puesto Climatización Zona 1 en modo <code>Frío</code>, ¿por qué <code>Autorización de refrigeración (Hardware / Cerrojo 1)</code> sigue indicando Bloqueado?</b></summary>

La integración abre automáticamente el calendario de verano (`01;01;26` a `01;01;99`) y activa `Z1OpModeCooling = day`. Sin embargo, el registro hardware `CoolingReleaseStatus` del regulador `15.bass3` **solo se desbloquea físicamente cuando se cumplen AMBAS condiciones: fechas de calendario abiertas Y temperatura exterior superior al umbral mínimo de refrigeración del firmware (habitualmente ≥ 15 °C)**. Por debajo de esa temperatura exterior, la bomba de calor bloquea el frío por hardware para proteger el compresor.
</details>

<details>
<summary><b>3. ¿Cómo puedo verificar que <code>ebusd</code> está publicando correctamente en formato JSON por MQTT?</b></summary>

Puedes escuchar el tópico `ebusd/#` desde **Ajustes → Dispositivos y servicios → MQTT → Configurar → Escuchar un tema** en Home Assistant, o con `mosquitto_sub`:
```bash
mosquitto_sub -h <IP_BROKER_MQTT> -u <USUARIO> -P <CLAVE> -t "ebusd/#" -v
```
Debes recibir cargas en formato JSON (p. ej. `ebusd/hmux0/RunDataFlowTemp {"value": {"value": 34.25}}`). Si recibes números planos en lugar de objetos JSON, añade `--mqttjson` a los argumentos de arranque de `ebusd` y reinícialo.
</details>

<details>
<summary><b>4. ¿Por qué el interruptor <code>Apagado global del sistema (Instalador)</code> viene deshabilitado por defecto?</b></summary>

Escribir `yes` en `15.bass3/GlobalSystemOff` deja toda la instalación aerotérmica en espera global a nivel de instalador. Viene deshabilitado por defecto en el registro de entidades de Home Assistant para evitar pulsaciones accidentales desde paneles o asistentes de voz; los usuarios avanzados pueden habilitarlo manualmente desde la ficha del dispositivo Controlador de Clima.
</details>

---

## Referencia Técnica e Ingeniería Inversa

Para consultar el desglose técnico exhaustivo de todo el protocolo eBUS obtenido mediante ingeniería inversa, visita:  
👉 **[Referencia Técnica e Ingeniería Inversa de eBUS (Español)](docs/technical_reference_es.md)** | **[(English Version)](docs/technical_reference.md)**

Temas clave documentados en detalle:
- **Topología del Bus y Asignación de Direcciones:** Desglose maestro/esclavo (`03/08`, `10/15`, `71/76`, `f1/f6`).
- **Telemetría de Energía de Alta Precisión (`b5 16`):** Matriz de acumuladores de por vida (`Hc`, `Hwc`, `Cool` para consumo eléctrico, calor útil y rendimiento ambiental) y potencia instantánea (`RunDataElectricPowerConsumption` con respaldo de `PowerStatus`, en Vatios).
- **Dinámica del Compresor:** Demostración empírica del divisor `/16` para el tipo de modulación `0x38` y la precisión del $0,8\%$ del calorímetro `0D5E`.
- **Programación Horaria Semanal (`b5 55`):** Temporizadores de hasta 3 franjas diarias y el requisito del relleno obligatorio `=FFFF`.
- **Enclavamientos y Cerrojos de Seguridad:** El mecanismo de doble cerrojo en refrigeración, el comportamiento de pestillo (*latch*) de `HwcSFMode = load` y las anulaciones temporales (Quick Veto).
- **Estandarización de Sondas no Instaladas:** Uso de `tempv` con relleno de 4 bytes (`IGN:4`) para evitar lecturas corruptas en sondas ausentes.
- **Gestión del Ancho de Banda a 2.400 Baudios:** Política de sondeo en tres niveles y cerrojos de concurrencia software.

---

## Desarrollo y Pruebas

Este repositorio incluye una batería de tests unitarios offline (ejecutables sin depender de una instancia activa de Home Assistant) y flujos de integración continua en GitHub Actions para **Hassfest**, **Validación HACS** y **Ruff**:

```bash
# Ejecutar los 187 tests unitarios (termodinámica, config flow, registro unique_id, servicios de diagnóstico, fixtures comunitarios, paridad de esquemas)
python -m unittest discover tests -v

# Verificar estilo y formato con Ruff
ruff check .
ruff format --check .
```

---

## Agradecimientos y Proyectos de Referencia

Esta integración se apoya en el trabajo previo de la comunidad de código abierto de eBUS. Un agradecimiento y reconocimiento especial a:

- **[john30/ebusd](https://github.com/john30/ebusd) y [ebusd-configuration](https://github.com/john30/ebusd-configuration):** Por el excepcional demonio eBUSd desarrollado por John30, sus especificaciones de protocolo y la base comunitaria de ingeniería inversa que hacen posible la comunicación local con el hardware.
- **[signalkraft/ebusd-vaillant-component](https://github.com/signalkraft/ebusd-vaillant-component):** Por inspirar el concepto y diseño de nuestros servicios de diagnóstico de volcado y captura de tráfico MQTT en vivo (`dump_mqtt_values` y `record_topic_changes`).
- **[MarkBovee/vaillant-ebus](https://github.com/MarkBovee/vaillant-ebus):** Por su exhaustivo trabajo en la exploración de registros de reguladores Vaillant y la recopilación de capturas comunitarias de múltiples familias de equipos.

---

## Licencia y Aviso Legal

Distribuido bajo la **[Licencia MIT](LICENSE)** — Copyright (c) 2026 [@R91g](https://github.com/R91g).

Este es un proyecto comunitario independiente de código abierto y **no** está afiliado, respaldado ni soportado oficialmente por **Vaillant GmbH** ni **Saunier Duval**. Úsalo bajo tu propia responsabilidad; la modificación de parámetros hidráulicos o de bivalencia de nivel instalador debe realizarse únicamente conociendo el diseño térmico de tu instalación.

