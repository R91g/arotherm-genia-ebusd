<p align="center">
  <img src="custom_components/arotherm_genia_ebusd/brand/icon.png" alt="aroTHERM & GeniaAir (eBUS)" width="150">
</p>

# aroTHERM & GeniaAir (eBUS) — Integración para Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.4%2B-41BDF5.svg?style=for-the-badge)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-local__push-00B050.svg?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![Protocol](https://img.shields.io/badge/Protocol-eBUS%20%2F%20MQTT%20JSON-FF8C00.svg?style=for-the-badge)](https://github.com/john30/ebusd)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

[🇬🇧 Read in English](README.md) | **🇪🇸 Español**

---

**aroTHERM & GeniaAir (eBUS)** (`arotherm_genia_ebusd`) es una **integración personalizada 100 % local (`local_push`) e independiente de la nube para Home Assistant**, diseñada para bombas de calor aerotérmicas R290 de **Vaillant** y **Saunier Duval** gobernadas por reguladores **`sensoCOMFORT` (`VRC 720`)** o **`MiPro Sense` (`SRC 720`)** a través de [**eBUSd**](https://github.com/john30/ebusd).

Construida directamente sobre la arquitectura electrónica eBUS compartida por el Grupo Vaillant (`08.hmux0`, `15.bass3`, `76.vwzio`, `04.netx3`), sustituye el caos de entidades del auto-descubrimiento MQTT crudo y la dependencia de servidores externos por **134 entidades nativas fuertemente tipadas**, motor termodinámico y cálculo de COP/SCOP en tiempo real, filtrado de valores centinela de firmware, gestión automática del Doble Cerrojo de refrigeración y algoritmo inteligente de ACS Puntual (Boost Forzado).

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
10. [Desarrollo y Pruebas](#desarrollo-y-pruebas)
11. [Licencia y Aviso Legal](#licencia-y-aviso-legal)

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
| **Potencia Térmica y COP / SCOP en vivo** | ❌ Estimaciones diarias/mensuales | ❌ Registros aislados sin cálculo | ✅ **ΔT, W y COP Vivo/Diario/Mensual** |

---

## Hardware Compatible y Equivalencia entre Marcas

Los equipos de aerotermia de Vaillant y Saunier Duval comparten **al 100 % las mismas placas electrónicas eBUS y mapas de registros internos**. Al elegir el fabricante durante la instalación (o más adelante mediante **Reconfigurar**), la integración adapta automáticamente todos los nombres de dispositivos, modelos comerciales y denominaciones de controlador a tu equipo.

### 1. Unidades Exteriores — Bombas de Calor (`08.hmux0`)

| Generación | Modelos Comerciales Vaillant | Modelos Comerciales Saunier Duval | Refrigerante / Placa |
| :--- | :--- | :--- | :--- |
| **Generación Actual (`/7.1` ES)** | `aroTHERM plus ES VWL 55/7.1 A 230V`<br>`aroTHERM plus ES VWL 85/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 230V`<br>`aroTHERM plus ES VWL 125/7.1 A 400V`<br>`aroTHERM plus ES VWL 155/7.1 A 230V`<br>`aroTHERM plus ES VWL 155/7.1 A 400V` | `GeniaAir Max ES 5`<br>`GeniaAir Max ES 8`<br>`GeniaAir Max ES 12`<br>`GeniaAir Max ES 15`<br>`GeniaAir Iso ES` | R290 (`08.hmux0`) |
| **Generación Previa (`/6` y `Max` Legacy)** | `aroTHERM plus VWL 35/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 55/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 75/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 105/6 A 230V (Legacy)`<br>`aroTHERM plus VWL 125/6 A (Legacy)` | `GeniaAir Max 4 (Legacy)`<br>`GeniaAir Max 6 (Legacy)`<br>`GeniaAir Max 8 (Legacy)`<br>`GeniaAir Max 11 (Legacy)`<br>`GeniaAir Max 15 (Legacy)` | R290 (`08.hmux0`) |

### 2. Módulos Hidráulicos Interiores, Interfaces y Torres (`76.vwzio`)

| Tipo de Componente | Modelos Vaillant | Modelos Saunier Duval | Dirección eBUS |
| :--- | :--- | :--- | :---: |
| **Módulo Hidráulico Mural (con apoyo eléctrico)** | `VWZ MEH 97/7` | `HPIM 7 230V` / `Módulo Hidráulico HE 9-7 W` | `76` (`VWZIO`) |
| **Módulo Hidráulico / Interfaz de Bomba** | `VWZ MH 97/7` / `VWZ AI 7/230V` | `HPIM 7 230V` | `76` (`VWZIO`) |
| **Torre Hidráulica con Acumulador ACS Integrado** | `uniTOWER VIH QW 190/7` | `GeniaSet FEW/FIW 200-7` | `76` (`VWZIO`) |

### 3. Reguladores del Sistema y Accesorios Opcionales

| Rol del Componente | Modelos Vaillant | Modelos Saunier Duval | Dirección eBUS |
| :--- | :--- | :--- | :---: |
| **Controlador de Clima del Sistema (Requerido)** | `sensoCOMFORT VRC 720` (`720/2`, `720/3`) | `MiPro Sense SRC 720` (`720/2`, `720/3`) | `15` (`BASS3`) |
| **Termostato Inalámbrico / Receptor RF (Opcional)** | `sensoCOMFORT RF VRC 720f` (`NETX3`) | `MiPro Sense RF SRC 720f` (`NETX3`) | `04` / `f6` |
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

### 3. 144 Entidades Nativas Agrupadas en 4 Dispositivos Lógicos

| Dispositivo Lógico | Circuito eBUS | Entidades Destacadas |
| :--- | :---: | :--- |
| **1. Unidad Exterior** (`<Modelo Exterior>`) | `08.hmux0` | Monitor operativo en vivo (52+ estados `S.xx`/`S.xxx`), RPM/RPS/modulación del compresor, alta presión R290, pasos EEV, ventiladores, caudal primario, temperaturas de impulsión/retorno de alta precisión, contadores IEEE 754 (`EXP`) eléctricos y térmicos, horas/arranques y **sensores termodinámicos calculados**. |
| **2. Controlador de Clima** (`sensoCOMFORT` / `MiPro Sense`) | `15.bass3` | **Climatización Zona 1 (`climate`)**, **Agua Caliente Sanitaria (`water_heater`)**, curvas climáticas, límites de impulsión, puntos de bivalencia, presión de agua, contadores de energía por servicio (`PrEnergySumHc` / `PrEnergySumHwc`), resúmenes de programación semanal e interruptores de sistema. |
| **3. Interfaz Hidráulica** (`<Modelo Interior>`) | `76.vwzio` | Estado operativo del circuito secundario (calefacción, refrigeración, ACS, postcirculación, reposo), diagnóstico de válvula de 3 vías / bomba secundaria y monitor de errores activos (`OK` o códigos de avería). |
| **4. Termostato Inalámbrico** *(Opcional)* | `04.netx3` / `f6` / `broadcast` | Temperatura en el dial inalámbrico, consigna inalámbrica, temperatura exterior por difusión (`Broadcast`) y fecha/hora del bus eBUS. *(Si no hay termostato inalámbrico instalado, los sensores broadcast se asocian automáticamente al Controlador de Clima).* |

**Desglose por Plataforma (144 entidades en total a través de 8 plataformas):**
- `climate` (**1**): Termostato unificado Calefacción / Refrigeración / Auto para Zona 1 con modos preestablecidos (`Programado (Confort)`, `Manual continuo`, `Eco (Reducción nocturna)`, `Anulación rápida (Quick Veto)`, `Modo Ausencia / Vacaciones`).
- `water_heater` (**1**): Control del depósito de Agua Caliente Sanitaria (ACS) (`Apagado`, `Programación horaria`, `Continuo (24h)`, `Boost`).
- `sensor` (**94**): 90 sensores de telemetría, energía, diagnóstico y cálculos termodinámicos + 4 sensores resumen de programación semanal (con el detalle diario completo en sus atributos) + sensores de días restantes de vacaciones y refrigeración.
- `binary_sensor` (**8**): Compresor en marcha, bomba primaria, desescarche activo, integración de energía activa, demanda de calor Zona 1, autorización hardware de refrigeración, ciclo de frío broadcast y señal física eBUS.
- `number` (**25**): Todos los parámetros numéricos de usuario e instalador (curva climática, sobretemperatura, impulsión mín./máx., corte de verano, consignas día/noche/manual/veto/frío/ausencia, consigna/histéresis/offset/tiempos de ACS, puntos de bivalencia y humedad máxima).
- `select` (**5**): Modo calefacción Zona 1, modo refrigeración Zona 1, modo ACS, modo reducción nocturna (`eco`/`night`/`off`) y control por temperatura ambiente (`off`/`modulating`/`thermostat`).
- `switch` (**6**): Modo Ausencia (`Holiday Mode`), ACS Puntual (`Boost`), Autorización temporada de frío (`Cerrojo 1`), Curva de calefacción adaptativa, Carga paralela de ACS y calefacción, y Apagado global del sistema *(deshabilitado por defecto por seguridad)*.
- `datetime` (**4**): Controles interactivos de interfaz para Fecha/Hora de Inicio y Fin del Modo Ausencia (`datetime`), y Fecha/Hora de Inicio y Fin de Refrigeración Manual (`datetime`).

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

### 5. Agua Caliente Sanitaria (`water_heater`): ACS Boost Forzado Inteligente
- De fábrica, `sensoCOMFORT` / `MiPro Sense` aplica una histéresis estricta de carga (`CylinderChargeHyst = 5.0 K`). Si tu consigna de ACS es `50.0 °C` y el acumulador está a `47.0 °C`, activar la carga puntual estándar (`HwcSFMode = load`) **no arranca el compresor** porque `47.0 °C > (50.0 - 5.0) °C`.
- Con el **ACS Boost Forzado Inteligente** activado (por defecto):
  1. Cuando `T_depósito > (T_consigna - Histéresis)`, al activar **`Boost`** (desde la tarjeta `water_heater`, el interruptor **ACS Puntual (Boost)** o la acción `arotherm_genia_ebusd.force_dhw_boost`), el coordinador memoriza tu consigna actual, eleva temporalmente `HwcTempDesired` de forma dinámica a **`T_depósito + Histéresis + 1.5 °C`** (con tope en `68.0 °C`) y tras `1.0 s` envía `HwcSFMode = load`, garantizando el arranque inmediato del compresor sea cual sea tu consigna habitual (`45 °C`, `50 °C`, `55 °C`...).
  2. Supervisa continuamente la carga y **restaura automáticamente tu consigna original de ACS** en cuanto finaliza el ciclo (`HwcSFMode == auto`), se alcanza la temperatura objetivo, se cancela manualmente o vence el temporizador de seguridad de 60 minutos.

### 6. Motor Termodinámico y de Eficiencia COP / SCOP en Tiempo Real
Calculado automáticamente por el coordinador con cada actualización de telemetría de `08.hmux0` y `15.bass3`:
```text
Salto Térmico Primario ΔT (K)   = T_impulsión (RunDataFlowTemp) - T_retorno (RunDataReturnTemp)
Potencia Térmica Instantánea    = Caudal (L/h) × |ΔT| (K) × 1.163   [Vatios]
COP / EER Instantáneo en Vivo   = Potencia_Térmica (W) / Potencia_Eléctrica (W)
COP Diario / Mensual / SCOP     = Energía_Térmica_Entregada / Energía_Eléctrica_Consumida
Consumo Eléctrico Combinado     = Calefacción_kWh (BASS3) + ACS_kWh (BASS3) + Frío_kWh (HMUX0)
```
*(Incluye puesta a cero durante desescarches y compresor en reposo para evitar falsos picos de COP por caudal residual de la bomba circuladora).*

### 7. Seguridad Táctil (`NumberMode.BOX`) e Identificadores `unique_id` Neutros
- **Seguridad Táctil:** Los 24 controles `number` utilizan cajas numéricas con botones `+`/`-` (`NumberMode.BOX`) en lugar de barras deslizantes, evitando modificar por accidente la curva climática o los puntos de bivalencia al hacer scroll desde el móvil.
- **Reconfiguración sin Pérdida de Datos:** Todos los `unique_id` siguen estrictamente el patrón `{entry_id}_{circuito}_{mensaje}_{campo}`, sin cadenas de marca. Cambiar de fabricante o modelo mediante **Reconfigurar** conserva al 100 % las entidades, automatizaciones y estadísticas históricas.

---

## Requisitos Previos

1. **Adaptador Físico eBUS:** Conectado en paralelo a los bornes de 2 hilos del bus eBUS (`+`/`-`, sin polaridad) de la máquina exterior, módulo hidráulico o mando mural — por ejemplo, [eBUS Adapter Shield v5 / C6](https://adapter.ebusd.eu/) (Ethernet, Wi-Fi o USB).
2. **Demonio `ebusd` (`v23.2` o superior):** Ejecutándose como **Add-on eBUSd en Home Assistant** o como servicio Linux / contenedor Docker, conectado a tu broker MQTT con el flag **`--mqttjson`** activado.
3. **Home Assistant (`2024.4.0` o superior):** Con la **[integración oficial MQTT](https://www.home-assistant.io/integrations/mqtt/)** configurada y conectada al mismo broker MQTT que `ebusd`.

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
    ├── 04.netx3.csv           <-- Receptor radio del termostato inalámbrico
    ├── 08.hmux0.csv           <-- Placa unidad exterior (aroTHERM plus / GeniaAir Max)
    ├── 15.bass3.csv           <-- Controlador de clima (sensoCOMFORT VRC 720 / MiPro Sense SRC 720)
    ├── 76.vwzio.csv           <-- Módulo o torre hidráulica (VWZ MEH / uniTOWER / HPIM 7 / GeniaSet)
    └── f6.netx3.csv           <-- Tramas RF pasivas del termostato inalámbrico
```

#### Opción A: Add-on eBUSd en Home Assistant
1. Copia `ebusd-configuration/broadcast.csv` en:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/broadcast.csv`
2. Copia los 5 archivos de `ebusd-configuration/vaillant/*.csv` en:
   `/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en/vaillant/`
3. Configura los argumentos de arranque del Add-on eBUSd para cargar los CSV locales, activar el formato JSON y permitir la escritura:
   ```text
   --configpath=/config/ebusd-configuration/en --scanconfig --accesslevel=* --mqttjson --mqtttopic=ebusd/%circuit/%name --mqttvar=filter-direction=r|u|^w
   ```
   > **¿Qué hace cada parámetro?**
   > - `--configpath=/config/ebusd-configuration/en`: Carga los archivos CSV optimizados de este repositorio en lugar de los obsoletos descargados por defecto de internet.
   > - `--scanconfig`: Escanea el bus eBUS al arrancar y empareja automáticamente las placas (`08`, `15`, `76`, `04`) con sus respectivos CSV.
   > - `--accesslevel=*`: Imprescindible para permitir la lectura y escritura de parámetros avanzados e instalador (curvas de calefacción, límites, bivalencia).
   > - `--mqttjson`: Publica los mensajes en formato JSON enriquecido (`{"value": ...}`), requerido por la integración.
   > - `--mqtttopic=ebusd/%circuit/%name`: Publica cada mensaje en el tópico estándar esperado por el coordinador de Home Assistant.
   > - `--mqttvar=filter-direction=r|u|^w`: **Imprescindible para habilitar la escritura.** El Add-on eBUSd incluye por defecto la plantilla `mqtt-hassio.cfg`, la cual viene con `filter-direction = r|u` (bloqueando escrituras hacia el bus). Añadir este argumento anula esa restricción y permite explícitamente enviar órdenes de escritura (`^w`) para consignas, curvas y modos.
   > - *(Nota: Parámetros como `--enablehex` no son necesarios salvo para depuración de bytes en crudo por terminal. Asimismo, se omite `--pollinterval` en los argumentos para que eBUSd aplique su valor predeterminado de 5 segundos (`--pollinterval=5`), intervalo sobre el cual están calibradas las prioridades de lectura `r` de nuestros archivos CSV).*
4. Reinicia el add-on **eBUSd** y comprueba en su registro de arranque que detecta y carga `08.hmux0`, `15.bass3` y `76.vwzio`.

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

Pulsa el siguiente botón para abrir directamente este repositorio en HACS dentro de tu instancia de Home Assistant:

[![Abrir tu instancia de Home Assistant y añadir el repositorio en HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=R91g&repository=arotherm-genia-ebusd&category=integration)

O añádelo manualmente desde HACS:

1. Abre **HACS** en la barra lateral de Home Assistant.
2. Pulsa el **menú de tres puntos (`⋮`)** en la esquina superior derecha y selecciona **Repositorios personalizados** (*Custom repositories*).
3. Completa los campos:
   - **Repositorio:** `https://github.com/R91g/arotherm-genia-ebusd`
   - **Categoría / Tipo:** Selecciona **Integración** (*Integration*).
4. Pulsa **Añadir** (*Add*).
5. Cierra la ventana, busca **aroTHERM & GeniaAir (eBUS)** en el catálogo de HACS, entra en su ficha y pulsa **Descargar** (*Download*).
6. **Reinicia Home Assistant** (**Ajustes → Sistema → Reiniciar**) para que cargue la integración.

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

1. Ve a **Ajustes → Dispositivos y servicios**.
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

---

## Acciones Personalizadas (Servicios)

La integración registra dos acciones personalizadas bajo el dominio `arotherm_genia_ebusd`, disponibles en **Herramientas para desarrolladores → Acciones** y en Automatizaciones / Scripts.

### 1. `arotherm_genia_ebusd.set_weekly_timer`
Modifica las programaciones horarias semanales nativas (`b5 55`) directamente en la memoria del regulador `sensoCOMFORT` / `MiPro Sense` (`15.bass3`), aplicando automáticamente un espaciado de `600 ms` entre días para proteger el bus eBUS.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit_type` | Sí | `heating`, `dhw`, `cooling`, `circulation` | Circuito horario a modificar (`Z1Timer`, `HwcTimer`, `CoolingTimer` o `CirculationTimer`). |
| `day` | Sí | `Monday`..`Sunday`, `Weekdays`, `All` | Día concreto, Lunes a Viernes (`Weekdays`) o toda la semana L–D (`All`). |
| `slot` | No | `1`, `2`, `3` *(por defecto: `1`)* | Ranura horaria diaria (`1` a `3`). |
| `start_time` | Sí | `"HH:MM"` *(ej. `"13:00"`)* | Hora de inicio en formato 24h (resolución nativa del mando de 10 minutos). |
| `end_time` | Sí | `"HH:MM"` *(ej. `"15:30"`)* | Hora de fin en formato 24h. |

**Ejemplo de Automatización — Ajustar el horario diario de ACS a las horas centrales de producción solar:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: All
  slot: 1
  start_time: "13:00"
  end_time: "15:30"
```

### 2. `arotherm_genia_ebusd.force_dhw_boost`
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

### 3. `arotherm_genia_ebusd.set_holiday_mode`
Activa el Modo Ausencia / Vacaciones (`PRESET_AWAY`) en el regulador `MiPro Sense`, suspendiendo la producción de ACS y reduciendo la calefacción a la temperatura de mantenimiento seleccionada durante una ventana temporal específica o de forma indefinida.

| Parámetro | Requerido | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `5.0` – `24.0` *(°C)* | Consigna de temperatura ambiente durante la ausencia (por defecto: `12.0 °C`). |
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

### 4. `arotherm_genia_ebusd.cancel_holiday_mode`
Cancela inmediatamente el Modo Ausencia en `15.bass3` y restablece el funcionamiento automático habitual en calefacción y ACS. No requiere parámetros.

```yaml
action: arotherm_genia_ebusd.cancel_holiday_mode
```

---

## Configuración en el Panel de Energía de Home Assistant

La integración proporciona sensores acumulativos `TOTAL_INCREASING` diseñados específicamente para la jerarquía padre/hijo de **Dispositivos individuales** del Panel de Energía de Home Assistant, evitando cualquier duplicidad de consumos:

1. Ve a **Ajustes → Paneles de control → Energía → Dispositivos individuales** y pulsa **Añadir dispositivo**.
2. **Añade el Dispositivo Padre (Consumo Total Aerotermia):**
   - Selecciona **`Consumo eléctrico total combinado aerotermia`** (`calculated_total_energy`, en `kWh`, perteneciente al dispositivo **Unidad Exterior**).
   - Asígnale un nombre descriptivo (p. ej. `Aerotermia (Total)`).
3. **Añade los 3 Sub-dispositivos Hijos** (seleccionando en **`Dispositivo superior / Incluido en`** → `Consumo eléctrico total combinado aerotermia` en cada uno):
   - **Calefacción:** `Consumo calefacción total (BASS3)` (`bass3_energy_hc_total`, en `kWh`, en el dispositivo Controlador de Clima).
   - **Agua Caliente Sanitaria (ACS):** `Consumo ACS total (BASS3)` (`bass3_energy_hwc_total`, en `kWh`, en el dispositivo Controlador de Clima).
   - **Refrigeración:** `Energía eléctrica refrigeración total histórica` (`energy_cooling_electric_total`, en `Wh`, en el dispositivo Unidad Exterior).

Home Assistant agrupará los tres servicios bajo un desplegable `>` dentro del dispositivo padre y mostrará el desglose exacto de **Calefacción vs. ACS vs. Refrigeración** en las barras de consumo y el diagrama de Sankey sin contabilizar ningún vatio-hora dos veces.

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

## Desarrollo y Pruebas

Este repositorio incluye una batería de tests unitarios offline (ejecutables sin depender de una instancia activa de Home Assistant) y flujos de integración continua en GitHub Actions para **Hassfest**, **Validación HACS** y **Ruff**:

```bash
# Ejecutar los 23 tests unitarios (termodinámica, config flow, registro unique_id, paridad de esquemas)
python -m unittest discover tests -v

# Verificar estilo y formato con Ruff
ruff check .
ruff format --check .
```

---

## Licencia y Aviso Legal

Distribuido bajo la **[Licencia MIT](LICENSE)** — Copyright (c) 2026 [@R91g](https://github.com/R91g).

Este es un proyecto comunitario independiente de código abierto y **no** está afiliado, respaldado ni soportado oficialmente por **Vaillant GmbH** ni **Saunier Duval**. Úsalo bajo tu propia responsabilidad; la modificación de parámetros hidráulicos o de bivalencia de nivel instalador debe realizarse únicamente conociendo el diseño térmico de tu instalación.

