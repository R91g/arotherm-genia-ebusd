# Configuración y Opciones en Caliente

[🇬🇧 Read in English](configuration.md) | **🇪🇸 Español**

---

## Reconfigurar Hardware o Marca

Para cambiar el modelo de bomba de calor, cambiar las etiquetas de marca o activar/desactivar el termostato inalámbrico o la pasarela cloud tras la instalación:

- Ve a **Ajustes → Dispositivos y Servicios → aroTHERM & GeniaAir (eBUS)**, abre el **menú de tres puntos (`⋮`)** de la entrada y selecciona **Reconfigurar**.
- Los títulos de los dispositivos y las especificaciones se actualizan preservando todos los IDs de entidad y las estadísticas históricas. Los `unique_id` de las entidades son neutros respecto a la marca (`{entry_id}_{circuit}_{message}_{field}`), así que cambiar de fabricante o modelos nunca deja entidades huérfanas ni rompe el histórico de energía.

## Opciones en Caliente (`Configurar`)

Pulsa **Configurar** en la tarjeta de la integración para ajustar el comportamiento sin reiniciar Home Assistant:

| Opción | Por defecto | Rango | Descripción |
| :--- | :---: | :---: | :--- |
| **Activar ACS Boost Forzado Inteligente** (`force_dhw_boost`) | `True` | On / Off | Eleva dinámicamente `HwcTempDesired` a `T_actual + Histéresis + 1,5 °C` cuando `ΔT < Histéresis` durante un boost de ACS puntual, restaurando la consigna original al terminar. |
| **Abrir Bloqueo 1 de Refrigeración automáticamente** (`auto_cooling_lock_bypass`) | `True` | On / Off | Establece `CoolingStartDate = 01;01;26` y `CoolingEndDate = 01;01;99` al pasar Zona 1 a refrigeración (`Cool`), y bloquea de nuevo a `01;01;19` en calefacción o apagado. |
| **Intervalo de sondeo `/get` de respaldo** (`fallback_poll_interval`) | `300 s` | `60` - `3600 s` | Intervalo del sondeo activo suave de registros básicos. Solo activo cuando la opción de pasarela cloud oficial (`f1`) está desactivada. |
| **Activar Diagnóstico TCP de eBUSd** (`enable_ebusd_tcp`) | `False` | On / Off | Habilita consultas TCP asíncronas directas a `ebusd` (`ebusctl`, puerto `8888`) para métricas físicas del bus, estado del escaneo, verificación de CSV (`find`), avisos de CSV ausentes y botones de control del demonio. |
| **Host TCP de eBUSd** (`ebusd_tcp_host`) | `127.0.0.1` | Hostname / IP | Equipo donde se ejecuta `ebusd` (p. ej. `127.0.0.1` o `core-ebusd`). |
| **Puerto TCP de eBUSd** (`ebusd_tcp_port`) | `8888` | `1` - `65535` | Puerto TCP donde `ebusd` acepta comandos. |
| **Activar Comando HEX Directo** (`enable_send_hex`) | `False` | On / Off | Opt-in de seguridad que desbloquea la acción de diagnóstico `send_hex_command`. Desactivado por defecto; ver la [referencia de acciones](services_es.md#10-arotherm_genia_ebusdsend_hex_command). |

## Uso Diario

> **Nota sobre los IDs de entidad:** Home Assistant antepone el nombre del dispositivo o regulador configurado al `entity_id` y lo genera en el idioma de tu interfaz (por ejemplo, `climate.mipro_sense_src_720_climatizacion_zona_1`). A continuación se indican los nombres visibles de cada entidad y su sufijo de clave interna.

- **Climatización Zona 1** (`zone_1_climate`): modos **Apagado / Calefacción / Refrigeración** y presets **Programado (Confort)**, **Manual continuo**, **Eco (Reducción nocturna)**, **Anulación rápida (Quick Veto)** y **Ausente / Vacaciones**. Cambiar la temperatura objetivo escribe en la consigna del modo activo; con la refrigeración en modo programado dispara un quick veto temporal persistente (ver [`quick_veto`](services_es.md#6-arotherm_genia_ebusdquick_veto)).
- **Agua Caliente Sanitaria** (`water_heater`): modos **Apagado**, **Programación horaria**, **Continuo (24h)** y **Boost**. El boost también se inicia desde **ACS Puntual (Boost)** o con la acción [`force_dhw_boost`](services_es.md#2-arotherm_genia_ebusdforce_dhw_boost).
- **Modo Vacaciones / Ausencia:** el interruptor **Modo Ausencia** con sus entidades `datetime` de inicio/fin, o la acción [`set_holiday_mode`](services_es.md#4-arotherm_genia_ebusdset_holiday_mode).
- **Programaciones horarias:** los **5 sensores resumen de programación semanal** (`heating`, `dhw`, `cooling`, `circulation` y `silent`) muestran los programas vigentes; los cambios se escriben con [`set_weekly_timer`](services_es.md#1-arotherm_genia_ebusdset_weekly_timer).
- **Modo silencioso:** **Nivel de modo silencioso del compresor** (`compressor_silent_operation_level`, `30–60 %`) fija el límite de reducción sonora del compresor, y la programación `silent` de `set_weekly_timer` decide cuándo se aplica.

## Entidades de Ajuste del Quick Veto

Dos entidades numéricas en el Regulador Climático ajustan cómo calcula [`quick_veto`](services_es.md#6-arotherm_genia_ebusdquick_veto) la consigna temporal cuando no se indica una temperatura explícita:

- **Incremento de temperatura Quick Veto Zona 1** (`z1_quick_veto_boost_delta`): grados añadidos sobre la consigna actual al activar un veto de calefacción sin temperatura explícita (por defecto `+3,0 °C`).
- **Reducción de temperatura Quick Veto Refrigeración Zona 1** (`z1_cooling_quick_veto_boost_delta`): grados restados de la consigna actual al activar un veto de refrigeración sin temperatura explícita (por defecto `-2,0 °C`).

La duración por defecto del veto se lee del registro propio del regulador **Duración temporal Quick Veto Zona 1** (`z1_quick_veto_duration`, valor de fábrica `3,0 h`, rango `0,5–12,0 h`).

## Entidades de Programación Antilegionela

El ciclo semanal de desinfección térmica se expone en el dispositivo Regulador Climático:

- **Día de protección antilegionela** (`select`, clave `hwc_legionella_day`): desactivado (`off`) o de lunes a domingo.
- **Hora de protección antilegionela** (`time`, clave `hwc_legionella_time`): hora de ejecución (`HH:MM`).

La misma programación puede establecerse desde automatizaciones con la acción [`set_legionella_protection`](services_es.md#3-arotherm_genia_ebusdset_legionella_protection).

## Comportamiento del Clima de Zona 1 y Vigilancia (*Watchdogs*)

Conviene conocer cuatro reglas operativas de la entidad de clima y del coordinador antes de montar automatizaciones sobre ellas:

- **Filtrado de centinelas:** el regulador reporta `5,0 °C` como temperatura ambiente deseada cuando la calefacción está apagada (protección antihielo) y `99,0 °C` cuando la refrigeración está apagada. La integración filtra ambos valores y conserva de forma independiente tus consignas reales de calefacción y refrigeración entre reinicios de Home Assistant (`RestoreEntity`), de modo que la interfaz nunca salta a esos extremos.
- **Doble bloqueo de refrigeración:** el regulador protege la refrigeración activa mediante la Compuerta 1 (ventana de calendario `CoolingStartDate`–`CoolingEndDate` junto a `CoolingOutsideTempThreshold`) y la Compuerta 2 (`Z1OpModeCooling`). Al activar el modo frío se abren ambas (con `auto_cooling_lock_bypass`, la Compuerta 1 se abre indefinidamente salvo que fijes fechas propias con **Fecha de inicio / fin de refrigeración**); al volver a calefacción o apagado se cierra la Compuerta 1 (`01;01;19`) y se restaura la consigna de calefacción.
- **Prioridad del Modo Vacaciones sobre la refrigeración:** `HolidayTemp` (`5,0–24,0 °C`, por defecto `15,0 °C`) es una consigna antihielo exclusiva para calefacción. Mientras el modo Ausencia / Vacaciones está activo (`holidayaway`), se bloquea la activación de la refrigeración y del quick veto de frío (y se cancela cualquier veto de frío activo) para evitar refrigerar innecesariamente una vivienda vacía.
- **Vigilancia de comunicaciones (*watchdog*):** si dejan de llegar datos del bus eBUS durante `10 minutos` (`600 s`, o `2 × fallback_poll_interval`), las entidades de control pasan de forma segura a `no disponible` (*unavailable*) manteniendo intactos los contadores históricos.

Todas las entidades `number` usan campos numéricos con botones `+`/`-` (`NumberMode.BOX`) en lugar de deslizadores para evitar cambios accidentales al hacer scroll desde el móvil.

## Panel de Energía de Home Assistant

La integración expone sensores de energía acumulada `TOTAL_INCREASING` con resolución de Wh (IEEE 754) que combinan la unidad exterior (`08.hmux0`) y el módulo hidráulico (`76.vwzio`), estructurados para la jerarquía de **Dispositivos Individuales** del Panel de Energía (anidado padre/hijo de modo que `Padre == Calefacción + ACS + Refrigeración` sin doble conteo):

1. Abre **Ajustes → Paneles → Energía → Dispositivos individuales** y pulsa **Añadir dispositivo**.
2. **Añade el sensor padre (bomba de calor total):**
   - Selecciona **Consumo eléctrico total aerotermia** (`calculated_system_total_energy`, en `Wh`, en el dispositivo Unidad Exterior).
   - Dale un nombre amigable (p. ej. `Bomba de Calor (Total)`).
3. **Añade los 3 sensores hijos anidados** (marcando **Incluido en** → `Consumo eléctrico total aerotermia` en cada uno):
   - **Calefacción:** `Consumo eléctrico total calefacción` (`calculated_heating_total_energy`).
   - **Agua Caliente Sanitaria:** `Consumo eléctrico total ACS` (`calculated_dhw_total_energy`).
   - **Refrigeración:** `Consumo eléctrico total refrigeración` (`energy_electric_cool`).

Home Assistant calcula deltas horarios, diarios, mensuales y anuales a partir de estos contadores hardware con resolución de Wh y muestra un desglose expandible de **Calefacción vs. ACS vs. Refrigeración** sin contar ni un vatio-hora dos veces. Los contadores por componente `08.hmux0` frente a `76.vwzio` siguen disponibles como sensores de diagnóstico si quieres inspeccionar por separado el consumo del compresor y del módulo hidráulico.

> **Nota sobre unidades `HMU` / `HMU00` (`HW5103`):** estas placas carecen de algunos registros EEPROM `b5 16` del Monobloc, así que la integración recurre a los contadores `PrEnergySum*` del regulador y a `Yield*` / `TotalEnergyUsage` (`ULG`) de la unidad exterior, desactivando automáticamente en el registro de entidades los 3 sensores eléctricos exteriores por modo exclusivos del Monobloc.

### Potencia Instantánea y Cálculos Termodinámicos

La potencia eléctrica instantánea prioriza `RunDataElectricPowerConsumption` (`r1;u`) mientras sea reciente (`<= 180 s`), recurre dinámicamente a `PowerStatus` como respaldo si caduca, y marca tanto la potencia en vivo como el COP instantáneo como `no disponible` (*unavailable*) tras `600 s` (`10 min`) sin actualizaciones:

```text
ΔT primario (K)                = T_impulsión (RunDataFlowTemp) - T_retorno (RunDataReturnTemp)
Potencia térmica instantánea   = Caudal (L/h) × |ΔT| (K) × 1,163    [Vatios]
COP / EER instantáneo          = Potencia_térmica (W) / Potencia_eléctrica (W)
COP / EER por modo y global    = (Térmica_HMUX0_Wh + Térmica_VWZIO_Wh) / (Eléctrica_HMUX0_Wh + Eléctrica_VWZIO_Wh)
Energía total del sistema (Wh) = Calefacción_Wh + ACS_Wh + Refrigeración_Wh
```

Los valores se fijan a cero durante los desescarches y las paradas del compresor para que el caudal residual de la bomba de circulación no produzca picos de COP ficticios.

