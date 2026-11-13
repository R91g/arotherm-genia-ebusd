# Referencia de Acciones (Servicios)

[🇬🇧 Read in English](services.md) | **🇪🇸 Español**

La integración registra doce acciones personalizadas bajo el dominio `arotherm_genia_ebusd`, disponibles en **Herramientas de Desarrollador → Acciones** y en automatizaciones y scripts.

| # | Acción | Propósito |
| :---: | :--- | :--- |
| 1 | [`set_weekly_timer`](#1-arotherm_genia_ebusdset_weekly_timer) | Escribir o borrar franjas de programación horaria (calefacción, refrigeración, ACS, circulación, silencioso) |
| 2 | [`force_dhw_boost`](#2-arotherm_genia_ebusdforce_dhw_boost) | Carga puntual inmediata de ACS evitando la histéresis |
| 3 | [`set_legionella_protection`](#3-arotherm_genia_ebusdset_legionella_protection) | Programar la desinfección antilegionela semanal |
| 4 | [`set_holiday_mode`](#4-arotherm_genia_ebusdset_holiday_mode) | Activar el modo vacaciones / ausencia |
| 5 | [`cancel_holiday_mode`](#5-arotherm_genia_ebusdcancel_holiday_mode) | Cancelar el modo vacaciones / ausencia |
| 6 | [`quick_veto`](#6-arotherm_genia_ebusdquick_veto) | Quick veto en el modo activo (veto nativo en calor, veto persistente en refrigeración) |
| 7 | [`cancel_quick_veto`](#7-arotherm_genia_ebusdcancel_quick_veto) | Cancelar el quick veto activo |
| 8 | [`dump_mqtt_values`](#8-arotherm_genia_ebusddump_mqtt_values) | Volcar la telemetría en caché para diagnóstico |
| 9 | [`record_topic_changes`](#9-arotherm_genia_ebusdrecord_topic_changes) | Grabar el tráfico MQTT en vivo durante una ventana |
| 10 | [`send_hex_command`](#10-arotherm_genia_ebusdsend_hex_command) | Enviar un telegrama HEX directo (diagnóstico opt-in) |
| 11 | [`read_parameter`](#11-arotherm_genia_ebusdread_parameter) | Leer un registro eBUS simbólico |
| 12 | [`write_parameter`](#12-arotherm_genia_ebusdwrite_parameter) | Escribir un registro eBUS simbólico |

---

## 1. `arotherm_genia_ebusd.set_weekly_timer`

[![Abre tu instancia de Home Assistant y muestra las herramientas de desarrollo del servicio.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.set_weekly_timer)

Modifica o borra los programas horarios semanales nativos `b5 55` dentro del regulador `sensoCOMFORT` / `MiPro Sense` (`15.bass3` / `15.basv3` / `15.ctlv2` / `15.ctlv3`), sincronizando el número de franjas activas y manteniendo el ritmo de bus automático en escrituras de varios días.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit_type` | Sí | `heating`, `dhw`, `cooling`, `circulation`, `silent` | Programación objetivo: calefacción (`Z1Timer`), ACS (`HwcTimer`), refrigeración (`CoolingTimer`), circulación (`CirculationTimer`) o modo silencioso (`SilentTimer`). |
| `day` | Sí | `Monday`..`Sunday`, `Weekdays`, `Weekend`, `All`<br>*(también en español: `Lunes`..`Domingo`, `Laborables`, `Fin de semana`, `Todos`)* | Día suelto, lunes-viernes, sábado-domingo o toda la semana. |
| `action` | No | `set`, `delete`, `clear` *(por defecto: `set`)* | `set` crea o actualiza la franja; `delete` la elimina y desplaza las siguientes; `clear` vacía el día (0 franjas activas). |
| `slot` | No | `1`, `2`, `3` *(por defecto: `1`)* | Índice de franja diaria. Ignorado con `action: clear`. |
| `start_time` | Opcional* | `"HH:MM"` | Inicio de la franja (formato 24 h, resolución de 1 minuto). *Obligatorio con `action: set`. |
| `end_time` | Opcional* | `"HH:MM"` (usa `"24:00"` para todo el día) | Fin de la franja (formato 24 h, resolución de 1 minuto). *Obligatorio con `action: set`. |
| `temp` | No | `5.0` - `80.0` (°C) | Consigna de la franja. Solo para `heating`, `dhw` y `cooling`; ignorado en `circulation` y `silent`. Si se omite, se usa la consigna activa del circuito. |
| `reset_remaining` | No | `true`, `false` *(por defecto: `false`)* | Con `slot: 1` y `action: set`, reescribe el día a exactamente 1 franja activa y borra las franjas 2 y 3 sin necesitar telemetría previa del bus. |

**Ejemplo 1 - Programación de ACS todos los días (inicializando el día con `reset_remaining`):**
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

**Ejemplo 2 - Calefacción continua 24 h en Zona 1:**
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

**Ejemplo 3 - Añadir una segunda franja de calefacción los fines de semana:**
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

**Ejemplo 4 - Borrar la franja 2 de un día concreto:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Monday
  action: delete
  slot: 2
```

**Ejemplo 5 - Vaciar todas las franjas de un día:**
```yaml
action: arotherm_genia_ebusd.set_weekly_timer
data:
  circuit_type: dhw
  day: Monday
  action: clear
```

---

## 2. `arotherm_genia_ebusd.force_dhw_boost`

[![Abre tu instancia de Home Assistant y muestra las herramientas de desarrollo del servicio.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=arotherm_genia_ebusd.force_dhw_boost)

Dispara una carga puntual inmediata del acumulador de ACS (`HwcSFMode = load`), opcionalmente con una temperatura de boost temporal para ese ciclo (útil para desviar excedentes solares fotovoltaicos).

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `boost_temp` | No | `40.0` - `68.0` (°C) | Consigna temporal para este único ciclo de boost. Si se omite, se aplica automáticamente `T_actual + Histéresis + 1,5 °C`. |

**Ejemplo - Calentar el ACS a 60 °C cuando la exportación solar supera 2,5 kW:**
```yaml
action: arotherm_genia_ebusd.force_dhw_boost
data:
  boost_temp: 60.0
```

> **Cómo funciona el bypass de la histéresis:** el regulador impone una histéresis de carga de fábrica (`CylinderChargeHyst = 5,0 K`), así que un boost estándar no hace nada cuando el acumulador está a menos de 5 K de la consigna. Con la opción **Activar ACS Boost Forzado Inteligente** activada (por defecto), la integración eleva temporalmente `HwcTempDesired` por encima de la temperatura actual del acumulador, lanza `HwcSFMode = load` y restaura tu consigna original al completar la carga, al cancelarlo o al cumplirse el tiempo máximo de seguridad de 60 minutos.

---

## 3. `arotherm_genia_ebusd.set_legionella_protection`

Configura la programación semanal de desinfección térmica antilegionela (`HwcLegionellaDay` y `HwcLegionellaTime`) en el regulador climático: el día de la semana y la hora de ejecución.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `day` | Sí | `off`, `Monday`..`Sunday` *(o en español / `'0'`..`'7'`)* | Día de ejecución de la desinfección; `off` la desactiva. |
| `time` | No | `"HH:MM"` | Hora de ejecución (por defecto `04:00` cuando hay un día activo). |

**Ejemplo - Desinfección semanal los domingos a las 04:00:**
```yaml
action: arotherm_genia_ebusd.set_legionella_protection
data:
  day: Sunday
  time: "04:00"
```

Los mismos ajustes están disponibles en el dispositivo Regulador Climático como **Día de protección antilegionela** (`select`) y **Hora de protección antilegionela** (`time`).

---

## 4. `arotherm_genia_ebusd.set_holiday_mode`

Activa el modo Vacaciones / Ausencia en el regulador climático, suspendiendo la producción de ACS y reduciendo la calefacción a una temperatura de protección antihielo durante una ventana temporizada o indefinida.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `5.0` - `24.0` (°C, por defecto `15.0`) | Temperatura ambiente reducida durante la ausencia (solo para calefacción). |
| `start_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Fecha de inicio de la ausencia (por defecto: hoy). |
| `start_time` | No | `HH:MM` | Hora de inicio (por defecto: hora actual). |
| `end_date` | No | `YYYY-MM-DD` / `DD/MM/YYYY` | Fecha de regreso. Si se omite, el modo permanece activo hasta cancelarlo. |
| `end_time` | No | `HH:MM` | Hora de regreso (por defecto: `23:59`). |

**Ejemplo - Vacaciones hasta el 10 de noviembre con protección antihielo a 12 °C:**
```yaml
action: arotherm_genia_ebusd.set_holiday_mode
data:
  temperature: 12.0
  end_date: "2026-11-10"
  end_time: "18:00"
```

---

## 5. `arotherm_genia_ebusd.cancel_holiday_mode`

Cancela inmediatamente el modo Vacaciones / Ausencia y restaura el funcionamiento automático por programación de calefacción y ACS. Sin parámetros.

```yaml
action: arotherm_genia_ebusd.cancel_holiday_mode
```

---

## 6. `arotherm_genia_ebusd.quick_veto`

Aplica un quick veto a Zona 1 en el modo que esté activo (bloqueado si está activo el Modo Ausencia / Vacaciones):

- **Calefacción (o apagado):** usa el **quick veto de calefacción nativo del regulador** (`Z1QuickVetoTemp` / `Z1QuickVetoDuration` / `Z1SFMode`), tras cuya duración el regulador vuelve automáticamente al modo previo (`auto`, `day`, `night` u `off`).
- **Refrigeración:** el veto nativo del regulador no cubre el frío, así que la acción se enruta a un **quick veto de refrigeración temporal persistente gestionado por la integración**: esta pasa la refrigeración a modo día manual (`Z1OpModeCooling = day`) con la consigna temporal y restaura exactamente el modo operativo y la consigna manual de frío previos al finalizar o cancelar.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `temperature` | No | `10.0` - `30.0` (°C en calor)<br>`15.0` - `30.0` (°C en frío) | Consigna durante el veto. Si se omite: en calefacción, `+3,0 °C` sobre la consigna actual si está en marcha (ajustable con **Incremento de temperatura Quick Veto Zona 1**) o `Z1ManualTemp` si está apagada; en refrigeración, la consigna actual menos el delta configurado (**Reducción de temperatura Quick Veto Refrigeración Zona 1**, por defecto `2,0 °C`), o `Z1CoolingManualTemp` fuera de franja programada. |
| `duration` | No | `0.5` - `12.0` (horas) | Duración del veto. Si se omite, se usa **Duración temporal Quick Veto Zona 1** configurada en el regulador (valor de fábrica `3,0 h`). |

**Ejemplo - Elevar Zona 1 a 22,5 °C durante 2,5 horas:**
```yaml
action: arotherm_genia_ebusd.quick_veto
data:
  temperature: 22.5
  duration: 2.5
```

> **Persistencia del quick veto de refrigeración:** la hora de finalización y el estado capturado antes del veto (`Z1OpModeCooling` y `Z1CoolingManualTemp`) se guardan en el almacenamiento persistente de Home Assistant (`Store`), no solo en RAM. Si Home Assistant se reinicia con un veto de refrigeración activo, la integración recarga ese estado al arrancar, reanuda la cuenta atrás restante (o marca la restauración pendiente si ya venció) y vuelve a escribir exactamente tu modo y consigna anteriores en cuanto eBUS esté operativo. El mismo mecanismo persistente se aplica al cambiar la consigna desde la tarjeta de clima estando activo el modo de refrigeración programado (`auto`).

---

## 7. `arotherm_genia_ebusd.cancel_quick_veto`

Cancela inmediatamente el quick veto activo. Para calefacción devuelve `Z1SFMode` a `auto`, fija la duración a `0` y restaura `off` si la calefacción estaba apagada antes; para refrigeración detiene el temporizador, limpia el estado guardado en `Store` y vuelve a escribir el modo y la consigna manual de refrigeración capturados al activarlo. Sin parámetros.

```yaml
action: arotherm_genia_ebusd.cancel_quick_veto
```

---

## 8. `arotherm_genia_ebusd.dump_mqtt_values`

Vuelca toda la telemetría en caché, circuitos activos, modelos de hardware y estado del eBUS como respuesta del servicio (`SupportsResponse.ONLY`), visible en Herramientas de Desarrollador. Pensado para compartir capturas de la instalación en issues de GitHub.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | No | Texto (p. ej. `"08"`, `"15"`, `"hmu"`) | Filtro por subcadena para limitar el volcado. Si se omite, se vuelcan todos los circuitos activos. |
| `anonymize` | No | Booleano (por defecto `true`) | Enmascara los números de serie de fabricación para compartir la captura públicamente con seguridad. |

---

## 9. `arotherm_genia_ebusd.record_topic_changes`

Graba todo el tráfico MQTT en vivo bajo el prefijo de topic de `ebusd` durante una ventana configurable (`SupportsResponse.ONLY`): marcas de tiempo, topics, payloads JSON decodificados y flags de retención. Útil para rastrear interacciones físicas sin acceso SSH.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `duration` | No | `5` - `120` (segundos, por defecto `30`) | Ventana de grabación. |
| `circuit` | No | Texto (p. ej. `"08"`, `"15"`) | Filtro por subcadena de los topics capturados. |
| `anonymize` | No | Booleano (por defecto `true`) | Enmascara números de serie e identificadores de hardware en los payloads capturados. |

---

## 10. `arotherm_genia_ebusd.send_hex_command`

Envía un telegrama hexadecimal en crudo directamente al demonio `ebusd` por su socket TCP y devuelve los bytes de respuesta (`SupportsResponse.ONLY`). Pensado para sondear registros no documentados sin editar archivos CSV ni usar SSH.

**Esta acción es un opt-in de seguridad deliberado.** Está bloqueada hasta que actives **Activar Comando HEX Directo** (`enable_send_hex`) en las opciones de la integración, y `ebusd` debe haberse arrancado con `--enablehex`. Los telegramas en crudo pueden escribir cualquier registro del bus, incluidos parámetros de instalador y de seguridad: úsala solo si sabes exactamente qué trama estás enviando y por qué.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `command` | Sí | Cadena HEX (p. ej. `"08b51a0405ff3428"`) | Telegrama en crudo (los espacios se eliminan). |
| `host` | No | Texto (por defecto el host TCP configurado, p. ej. `"127.0.0.1"`) | Equipo donde se ejecuta `ebusd`. |
| `port` | No | Entero (por defecto el puerto TCP configurado, p. ej. `8888`) | Puerto TCP de comandos de `ebusd`. |
| `timeout` | No | Flotante (por defecto `5.0`) | Tiempo máximo del socket en segundos. |

---

## 11. `arotherm_genia_ebusd.read_parameter`

Lee un registro eBUS simbólico por MQTT (`SupportsResponse.ONLY`): publica en `<prefijo>/<circuito>/<nombre>/get` y espera la respuesta JSON decodificada. Los alias de circuito como `08`, `15`, `outdoor` y `controller` se resuelven automáticamente.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | Sí | Texto (p. ej. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`) | Nombre o alias del circuito eBUS. |
| `name` | Sí | Texto (p. ej. `"CompressorSilentOperationLevel"`, `"Status01"`) | Nombre simbólico del mensaje/parámetro definido en los CSV. |
| `force` | No | Booleano (por defecto `false`) | `true` fuerza una consulta activa al bus en lugar de devolver el valor en caché. Prefiere la caché para mantener bajo el tráfico del bus. |
| `timeout` | No | Flotante (por defecto `5.0`) | Espera máxima de la respuesta MQTT, en segundos. |

---

## 12. `arotherm_genia_ebusd.write_parameter`

Escribe un valor simbólico en un registro eBUS por MQTT (`SupportsResponse.OPTIONAL`): publica en `<prefijo>/<circuito>/<nombre>/set` y aplica una actualización optimista inmediata en la interfaz.

| Parámetro | Obligatorio | Valores Permitidos | Descripción |
| :--- | :---: | :--- | :--- |
| `circuit` | Sí | Texto (p. ej. `"08"`, `"hmu"`, `"bass3"`, `"ctlv2"`) | Nombre o alias del circuito eBUS. |
| `name` | Sí | Texto (p. ej. `"CompressorSilentOperationLevel"`, `"Z1OpMode"`) | Nombre simbólico del mensaje/parámetro definido en los CSV. |
| `value` | Sí | Texto / Número / Booleano | Valor a escribir. |

> Las escrituras salen al bus eBUS físico. Comprueba el rango permitido de cada registro en su definición CSV antes de escribir y evita escrituras de alta frecuencia desde automatizaciones: el bus funciona a 2400 baudios y comparte el medio con tu regulador de pared.

