# Solución de Problemas y FAQ

[🇬🇧 Read in English](troubleshooting.md) | **🇪🇸 Español**

---

## Descarga de Diagnósticos y Verificación del Bus

Para inspeccionar los payloads JSON en caché de `ebusd`, o adjuntarlos a un informe de error: **Ajustes → Dispositivos y Servicios → aroTHERM & GeniaAir (eBUS) → `⋮` → Descargar diagnósticos**. Los detalles sensibles de los topics MQTT se anonimizan automáticamente.

Para capturas compartibles, las acciones [`dump_mqtt_values`](services_es.md#8-arotherm_genia_ebusddump_mqtt_values) y [`record_topic_changes`](services_es.md#9-arotherm_genia_ebusdrecord_topic_changes) generan volcados anonimizados (números de serie enmascarados por defecto) directamente desde Herramientas de Desarrollador.

Si tienes activado **Activar Diagnóstico TCP de eBUSd** en las [opciones en caliente](configuration_es.md#opciones-en-caliente-configurar), el coordinador también ejecuta consultas `info` y verificaciones CSV `find` por TCP sin tráfico en el bus eBUS, rellena las métricas físicas de latencia/símbolos y actualiza **Dispositivos eBUS con CSV pendiente** si detecta algún equipo escaneado sin archivo CSV cargado.

## Preguntas Frecuentes

<details>
<summary><b>1. ¿Por qué algunas entidades muestran <code>Desconocido</code> durante los primeros 30-60 segundos tras reiniciar Home Assistant?</b></summary>

Es intencionado. Para proteger el bus de 2400 baudios, el coordinador espera `5,0 s` a los mensajes MQTT retenidos y luego consulta los registros que faltan de uno en uno (`0,8 s` de separación). Todos los sensores activos se rellenan en aproximadamente un minuto.
</details>

<details>
<summary><b>2. Pasé Zona 1 a Refrigeración; ¿por qué <code>Autorización de refrigeración (Hardware / Cerrojo 1)</code> sigue indicando Bloqueado?</b></summary>

La integración abre las fechas del calendario (`01;01;26` a `01;01;99`) y establece `Z1OpModeCooling = day`, pero el registro físico `CoolingReleaseStatus` del firmware del regulador solo se desbloquea cuando AMBAS condiciones se cumplen: la ventana de calendario abierta Y la temperatura exterior por encima de `CoolingOutsideTempThreshold` (típicamente `≥ 15 °C`). Por debajo de esa temperatura, la bomba de calor bloquea la refrigeración por hardware para proteger el compresor. Ten en cuenta además que el Modo Ausencia activo impide activar la refrigeración.
</details>

<details>
<summary><b>3. ¿Cómo verifico que ebusd publica JSON en MQTT?</b></summary>

Suscríbete a tu broker con `mosquitto_sub` (o **Ajustes → Dispositivos y Servicios → MQTT → Configurar → Escuchar un topic**):

```bash
mosquitto_sub -h <IP_BROKER_MQTT> -u <USUARIO> -P <CLAVE> -t "ebusd/#" -v
```

Los payloads deben ser objetos JSON (p. ej. `ebusd/hmux0/RunDataFlowTemp {"value": {"value": 34.25}}`). Si ves números planos, añade `--mqttjson` a los flags de arranque de `ebusd` y reinícialo.
</details>

<details>
<summary><b>4. ¿Por qué <code>Apagado global del sistema (Instalador)</code> está desactivado por defecto?</b></summary>

Escribir `yes` en `GlobalSystemOff` deja toda la instalación (incluido el ACS y, según el firmware, las rutinas antihielo) en standby de instalador. La entidad está desactivada por defecto en el registro de entidades para evitar activaciones accidentales desde el panel o asistentes de voz; puedes activarla manualmente desde la página del dispositivo Regulador Climático.
</details>

<details>
<summary><b>5. Algunos sensores se quedan en <code>Desconocido</code> permanentemente en mi regulador CTLV2 / CTLV3 o unidad HMU (HW5103).</b></summary>

Dos causas habituales:

- El registro está definido como lectura bajo demanda (`r`) y nada en el bus lo solicita, así que `ebusd` nunca lo publica. Activar el [diagnóstico TCP de eBUSd](configuration_es.md) o leerlo una vez con [`read_parameter`](services_es.md#11-arotherm_genia_ebusdread_parameter) (`force: true`) confirma si el registro responde.
- La variante de hardware simplemente no expone ese registro. El soporte de `15.ctlv2`/`15.ctlv3` y `08.hmu.HW5103` se basa en mapas de registros e informes de la comunidad, y sigue validándose en instalaciones reales. Abre un issue con una captura anonimizada de [`dump_mqtt_values`](services_es.md#8-arotherm_genia_ebusddump_mqtt_values) para confirmar o ajustar el mapa de registros.
</details>

<details>
<summary><b>6. ¿Por qué los controles o el COP instantáneo pasan a <code>No disponible</code> tras 10 minutos?</b></summary>

El coordinador aplica un watchdog de comunicaciones y frescura de potencia de `600 s` (`10 minutos`, o `2 × fallback_poll_interval`). Si dejan de llegar actualizaciones MQTT desde `ebusd` (p. ej. caída del demonio, desconexión MQTT o fallo del adaptador eBUS), los controles y la potencia/COP en vivo pasan a `no disponible` (*unavailable*) hasta que vuelve la telemetría del bus, manteniendo intactos los acumuladores históricos.
</details>

## Cómo Reportar un Issue

Al abrir un [issue en GitHub](https://github.com/R91g/arotherm-genia-ebusd/issues), incluye:

1. El **archivo de diagnósticos** (ver arriba).
2. Una respuesta anonimizada de **`dump_mqtt_values`**.
3. Si el problema afecta a la comunicación del bus o a un registro concreto, una captura de **`record_topic_changes`** tomada mientras lo reproduces.
4. Tu versión de `ebusd` (`ebusd --version`), versión de Home Assistant y modelos de hardware (unidad exterior, regulador, módulo hidráulico).

