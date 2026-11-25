# AquaWeb IoT – Avance 3: Módulo de Comunicación MQTT

---

## 1. Hoja de Presentación

- **Universidad:** Universidad Tecnológica de Panamá (UTP)
- **Facultad:** Facultad de Ingeniería de Sistemas Computacionales
- **Asignatura:** Desarrollo de Software VIII
- **Docente:** Prof. José Collado
- **Proyecto:** AquaWeb IoT – Avance 3: Módulo de Comunicación MQTT
- **Estudiante:** Cristian Joel Pinto Ortega — Cédula: `8-1015-1885`
- **Grupo:** `grupo` (DS8)
- **Fecha:** 25 de noviembre de 2026
- **Repositorio GitHub:** https://github.com/Cris19111/AquaWeb
- **Dashboard Web (GitHub Pages):** https://cris19111.github.io/AquaWeb/
- **Simulación en Wokwi:** Proyecto ESP32 MicroPython definido en `wokwi/diagram.json`, `wokwi/main.py` y `wokwi/umqtt_simple.py`

---

## 2. Descripción del Módulo de Comunicación

El módulo de comunicación de **AquaWeb IoT** conecta el nodo embebido simulado en Wokwi (**ESP32 + MicroPython v1.20+**) con el backend de supervisión en **Python 3** mediante el protocolo **MQTT** sobre el broker público `broker.hivemq.com:1883`. El sistema opera de forma determinística (sin IA/ML) para monitorear pH y temperatura en estanques camaroneros de Panamá.

1. **Nodo Wokwi (`wokwi/main.py`, `wokwi/umqtt_simple.py`):** Adquiere pH (GPIO 34 con `ADC.ATTN_11DB`) y temperatura DHT22 (GPIO 15), controla la bomba/aireador (LED rojo en GPIO 2), indica conectividad (LED azul en GPIO 5) y atiende un botón físico de bypass manual (GPIO 4 con `Pin.IRQ_RISING` y antirrebote de `250 ms`). Publica telemetría JSON cada `5 s`, gestiona órdenes remotas con `check_msg()`, ejecuta `ping()` explícito en modo silencio, registra testamento **LWT** (`OFFLINE`, QoS 1, retenido) antes de conectar y tolera caídas de red con backoff exponencial (`2` a `60 s`) conservando el control automático local offline.
2. **Broker MQTT (`broker.hivemq.com:1883`):** Desacopla al nodo y al backend enrutando los temas bajo `utp/ds8/grupo/aquaweb/#` y reteniendo el estado de conectividad.
3. **Programa Receptor (`backend/receptor_mqtt.py`):** Implementado con `paho-mqtt >= 2.1.0` (`CallbackAPIVersion.VERSION2`), se suscribe con comodín `#` (QoS 0), valida sintaxis JSON, tipos estrictos y rangos físicos, descarta tramas corruptas sin detenerse y guarda lecturas válidas en `backend/data/telemetria_valida.csv`.
4. **Monitor de Estado (`backend/monitor_estado.py`):** Script independiente con `loop_start()` y evaluación no bloqueante cada `1 s`. Distingue `ONLINE`, `SIN_DATOS` (`SILENCIO_MAX_SEG = 20 s`) y `OFFLINE`, persistiendo en `backend/data/eventos_comunicacion.csv` únicamente las transiciones de estado.

---

## 3. Esquema de Temas MQTT y Ejemplos de Mensajes JSON

La siguiente tabla refleja exactamente los niveles de **QoS** y bandera **Retenido** verificados en `wokwi/main.py`, `wokwi/umqtt_simple.py`, `backend/receptor_mqtt.py`, `backend/monitor_estado.py` y `backend/simulador_pruebas.py`:

| Tema MQTT | Dirección | QoS | Retenido | Contenido / Formato |
| :--- | :--- | :--- | :--- | :--- |
| `utp/ds8/grupo/aquaweb/telemetria` | Dispositivo → Broker | `0` (pub ESP32 y sub backend) | No (`False`) | JSON con `ph`, `temperatura`, `actuador`, `modo`, `umbral_ph_min`, `umbral_ph_max` |
| `utp/ds8/grupo/aquaweb/estado` | Dispositivo → Broker | `1` (pub `ONLINE`, LWT `OFFLINE` y sub monitor) | Sí (`True`) | Cadena `"ONLINE"` al conectar o `"OFFLINE"` emitido por el broker vía Last Will (LWT) |
| `utp/ds8/grupo/aquaweb/ordenes` | Broker → Dispositivo | `1` (pub emisor CLI) / `0` (sub ESP32) | No (`False`) | JSON con comandos de `modo`, `actuador`, `umbral_ph_min`, `umbral_ph_max` o `simular_silencio` |

**Ejemplo de telemetría (`.../telemetria`, QoS 0):**
```json
{"ph": 7.85, "temperatura": 26.4, "actuador": 0, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5}
```

**Ejemplo de orden válida (`.../ordenes`):**
```json
{"modo": "MANUAL", "actuador": 1}
```

**Ejemplo de estado (`.../estado`, QoS 1, retenido):**
```text
"ONLINE"   (al conectar)  |  "OFFLINE"  (disparado por el broker vía LWT tras vencer keepalive=15s)
```

---

## 4. Diagrama de Flujo de Datos

El flujo inicia en la lectura periódica no bloqueante del ESP32 en Wokwi (`time.ticks_ms()`), que transmite tramas JSON (QoS 0) hacia `utp/ds8/grupo/aquaweb/telemetria` y su disponibilidad (QoS 1, retenido) hacia `utp/ds8/grupo/aquaweb/estado`. El broker distribuye la información hacia dos procesos desacoplados en Python: `receptor_mqtt.py` (validación de integridad y registro en `telemetria_valida.csv`) y `monitor_estado.py` (supervisión de silencio cada `1 s` y registro de transiciones en `eventos_comunicacion.csv`). En sentido inverso, `simulador_pruebas.py` actúa como emisor CLI de órdenes sobre `utp/ds8/grupo/aquaweb/ordenes`, las cuales el firmware valida atómicamente antes de alterar su estado.

![Diagrama de flujo de datos Avance 3](assets/diagrama_flujo.png)

---

## 5. Tabla de Pruebas (8 Escenarios Obligatorios)

Se distingue rigurosamente el método de verificación de cada escenario entre pruebas ejecutadas con el emisor CLI contra el broker/backend (`Ejecutado (CLI → Backend)`) y mecanismos validados directamente en la lógica del firmware MicroPython (`Verificado en firmware / razonado`), aclarando que `simulador_pruebas.py` cumple el rol de emisor de pruebas y no sustituye al nodo ESP32 en Wokwi.

| # | Escenario | Cómo se provocó | Resultado esperado | Resultado observado | Verificación |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Funcionamiento normal | Ejecución de `receptor_mqtt.py` y `monitor_estado.py` contra `broker.hivemq.com:1883` recibiendo ráfaga normal enviada desde `simulador_pruebas.py`. | Estado `ONLINE` retenido; registro de lecturas válidas en `telemetria_valida.csv` y evento inicial único en `eventos_comunicacion.csv`. | Se registraron 4 filas válidas (`pH 7.85, 8.12, 6.20, 7.65`) en `telemetria_valida.csv` y 1 sola transición `INICIAL -> ONLINE (INFO)` en `eventos_comunicacion.csv`. | **Ejecutado (CLI → Backend)** |
| 2 | Orden válida | Envío desde el emisor CLI de `{"modo":"MANUAL","actuador":1}`, `{"umbral_ph_min":7.0,"umbral_ph_max":8.5}` y `{"modo":"AUTO"}` a `.../ordenes`. | El broker entrega la orden; el firmware la valida atómicamente, actualiza modo/actuador/umbrales, refleja el cambio en GPIO 2 e imprime `[ORDEN APLICADA]`. | Tráfico confirmado en el broker por `receptor_mqtt.py`; lógica de aplicación atómica y actualización de `led_actuador` verificada en `validar_y_aplicar_orden()` de `wokwi/main.py`. | **Ejecutado (CLI → Broker) + Verificado en firmware / razonado** |
| 3 | Orden inválida | Envío desde el emisor CLI de JSON corrupto `{modo: MANUAL_CORRUPTO`, modo `"TURBO"`, `actuador: 9` y `min=10.5 > max=6.0`. | Rechazo estricto en consola indicando motivo; el estado previo del sistema permanece intacto. | Las 4 tramas inválidas circularon por el broker y cumplen las ramas de rechazo explícito (`[ORDEN RECHAZADA]`) sin mutar `estado_sistema` en `wokwi/main.py`. | **Ejecutado (CLI → Broker) + Verificado en firmware / razonado** |
| 4 | Caída de Wi-Fi / broker y recuperación | Análisis y prueba unitaria de fallo de socket (`OSError`/`MQTTException`) en el bucle principal de `wokwi/main.py` (en Wokwi puede reproducirse apuntando `MQTT_BROKER` a un host inalcanzable para observar el backoff en consola serial). | LED azul parpadea/apaga; el ESP32 mantiene el muestreo local y la IRQ de GPIO 4 mientras reintenta con backoff exponencial `2..60 s`. | Bloques `try/except (OSError, MQTTException)` y `backoff_s = min(backoff_s * 2, 60)` garantizan progresión `2, 4, 8, 16, 32, 60 s` no bloqueante con `ticks_ms()` manteniendo control local e IRQ. | **Verificado en firmware / razonado** |
| 5 | Dato inválido hacia receptor | Inyección desde el emisor CLI de 5 tramas inválidas en `.../telemetria` (JSON truncado, campos faltantes, `pH=19.5`, `Temp=95.0`, `ph="alto"`). | `receptor_mqtt.py` imprime advertencia clara por cada trama, la descarta y continúa ejecutándose sin escribirla en CSV. | El receptor imprimió `[ADVERTENCIA - DESCARTADO #1..#5]`, reportó `Descartados=5`, no se detuvo y mantuvo limpio `telemetria_valida.csv`. | **Ejecutado (CLI → Backend)** |
| 6 | Reinicio del dispositivo | Revisión del flujo de arranque `main()` -> `conectar_mqtt()` en `wokwi/main.py` y validación de reconexión limpia. | El dispositivo registra LWT antes de `connect()`, publica `ONLINE` (QoS 1, retenido), se suscribe a `.../ordenes` y reanuda telemetría sin intervención manual. | En `conectar_mqtt()` se ejecuta en orden `set_last_will(..., b"OFFLINE", retain=True, qos=1)`, `connect(clean_session=True)`, `subscribe(TOPIC_ORDENES, qos=0)` y `publish(..., b"ONLINE", retain=True, qos=1)`. | **Verificado en firmware / razonado** |
| 7 | Dispositivo conectado que deja de publicar (`SIN_DATOS`) | Pausa de `23 s` sin telemetría tras estado `ONLINE` (equivalente en el ESP32 a `{"simular_silencio": true}`, donde el firmware mantiene `ping()` cada `7 s` sin publicar lecturas). | Al superar `SILENCIO_MAX_SEG = 20 s`, `monitor_estado.py` transiciona `ONLINE -> SIN_DATOS` (1 evento); al reanudar vuelve a `ONLINE`. | A los `20.6 s` se registró `SIN_DATOS (ADVERTENCIA)` y al reanudar telemetría regresó a `ONLINE (INFO)` en `eventos_comunicacion.csv`. | **Ejecutado (CLI → Backend) + Verificado en firmware (`ping()`)** |
| 8 | Detención de simulación (`OFFLINE` / LWT) | Prueba de recepción `OFFLINE` en `.../estado` hacia `monitor_estado.py`. En la demostración con Wokwi, el estado `OFFLINE` se dispara automáticamente por el broker mediante el Testamento LWT al detener la simulación sin `DISCONNECT` tras vencer `keepalive = 15 s`. | `monitor_estado.py` detecta el cambio y registra 1 sola transición `ONLINE -> OFFLINE (CRITICO)` en `eventos_comunicacion.csv`. | Al llegar `"OFFLINE"` en `.../estado`, el monitor registró la transición #4 `ONLINE -> OFFLINE (CRITICO)`, completando 4 transiciones únicas sin duplicados. | **Ejecutado (CLI → Backend) + LWT configurado en firmware (QoS 1, retain=True)** |

---

## 6. Capturas de Evidencia

### (a) Consola del Programa Receptor y Muestra de `telemetria_valida.csv`
La captura evidencia la recepción en tiempo real desde `broker.hivemq.com:1883`, la validación de 4 tramas válidas persistidas en `telemetria_valida.csv`, la observación de órdenes transmitidas en `.../ordenes` y el descarte controlado de 5 tramas corruptas o fuera de rango inyectadas por el emisor CLI sin detener el servicio.

![Consola del receptor y telemetria_valida.csv](assets/captura_receptor.png)

### (b) Consola del Monitor de Estado y Muestra de `eventos_comunicacion.csv`
La captura demuestra el registro exclusivo de transiciones de estado (`INICIAL -> ONLINE`, `ONLINE -> SIN_DATOS` tras `20.6 s`, `SIN_DATOS -> ONLINE` y `ONLINE -> OFFLINE`) en `eventos_comunicacion.csv` sin duplicar registros repetidos. En ejecución real con Wokwi, la transición `OFFLINE` la dispara el broker automáticamente mediante el Testamento LWT configurado en `wokwi/main.py` al detener la simulación tras vencer `keepalive = 15 s`.

![Consola del monitor y eventos_comunicacion.csv](assets/captura_monitor.png)

### (c) Simulación en Wokwi (ESP32 + Consola Serial)
Archivo esperado en `docs/assets/captura_wokwi_telemetria_ordenes.png` mostrando la lectura de sensores del ESP32 en Wokwi, la aplicación de una orden válida (`[ORDEN APLICADA]` reflejada en el LED rojo en GPIO 2) y el rechazo de una orden inválida (`[ORDEN RECHAZADA]`).

---

## 7. Dificultades Encontradas y Soluciones Aplicadas

1. **Atenuación ADC en MicroPython v1.20+:** Ejemplos previos empleaban constantes obsoletas como `ATTN_11V` o rangos de 1.1 V que saturaban el potenciómetro a 3.3 V. Se resolvió configurando `adc_ph.atten(ADC.ATTN_11DB)` y `adc_ph.width(ADC.WIDTH_12BIT)` para cubrir el rango completo `0–3.3 V` (`0–4095`).
2. **Migración a `CallbackAPIVersion.VERSION2` en `paho-mqtt >= 2.1.0`:** La API v2 requiere declarar `CallbackAPIVersion.VERSION2` en `mqtt.Client` y actualizar las firmas de `on_connect` y `on_disconnect`. Se actualizaron los tres scripts del backend eliminando advertencias de deprecación.
3. **Bloqueos en red y sockets no bloqueantes en `umqtt_simple.py`:** Un `time.sleep(backoff)` congelaría la lectura local y la interrupción del botón GPIO 4 ante caídas de red, y `check_msg()` podía fallar al leer tramas parciales. Se implementó un bucle basado en `time.ticks_ms()`/`time.ticks_diff()` con backoff exponencial (`2..60 s`) y restauración de `settimeout(5)` tras leer el primer byte en `umqtt_simple.py`.
4. **Validación estricta de tipos JSON y consistencia de QoS:** Como en Python `isinstance(True, int)` es `True`, se excluyeron explícitamente booleanos en campos numéricos y valores `NaN`/`Inf`, y se documentó con exactitud el QoS real implementado por cada tema (`QoS 0` en telemetría, `QoS 1` en estado/LWT y `QoS 1/0` en órdenes).
