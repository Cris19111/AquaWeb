# AquaWeb IoT — Avance 3: Módulo de Comunicación MQTT

Sistema de monitoreo y control determinístico de calidad de agua para estanques camaroneros en Panamá (sin uso de IA/ML), correspondiente a la asignatura **Desarrollo de Software VIII** (Universidad Tecnológica de Panamá, Prof. José Collado).

- **Estudiante:** Cristian Joel Pinto Ortega — Cédula: `8-1015-1885`
- **Grupo MQTT:** `grupo` (`utp/ds8/grupo/aquaweb/...`)
- **Enlace al repositorio GitHub:** https://github.com/Cris19111/AquaWeb
- **Dashboard Web (GitHub Pages):** https://cris19111.github.io/AquaWeb/
- **Enlace al proyecto en Wokwi:** Cargar los archivos de `wokwi/` (`diagram.json`, `umqtt_simple.py`, `main.py`) en Wokwi (ESP32 MicroPython) e incorporar la URL compartida del proyecto al entregar.

Este avance amplía el nodo embebido en **ESP32 + MicroPython v1.20+** (Wokwi) y el procesamiento local del **Avance 2** incorporando comunicación bidireccional mediante **MQTT** (`broker.hivemq.com:1883`), Last Will & Testament (**LWT**), reconexión con **backoff exponencial (2 a 60 s)**, validación estricta de telemetría y órdenes JSON, monitoreo independiente de estado de enlace y persistencia estructurada en archivos CSV.

---

## 1. Arquitectura del Avance 3

```text
+-----------------------------------+       MQTT (broker.hivemq.com:1883)       +-----------------------------------+
|  Nodo Embebido ESP32 (Wokwi)      |                                           |  Backend Python (paho-mqtt >= 2)  |
|  - GPIO 34: Potenciómetro pH      | --- .../telemetria (JSON, QoS 0, 5 s) --> |  - receptor_mqtt.py               |
|  - GPIO 15: DHT22 Temperatura     | --- .../estado (ONLINE/LWT, QoS 1) -----> |    Valida JSON y rangos físicos   |
|  - GPIO 2 : LED rojo (Actuador)   |                                           |    -> data/telemetria_valida.csv  |
|  - GPIO 5 : LED azul (WiFi/MQTT)  | <--- .../ordenes (JSON control/umbral) -- |  - monitor_estado.py              |
|  - GPIO 4 : Botón IRQ Bypass      |                                           |    ONLINE / SIN_DATOS / OFFLINE   |
|  - Operación offline + Backoff    |                                           |    -> data/eventos_comunicacion   |
+-----------------------------------+                                           +-----------------------------------+
```

---

## 2. Esquema de Temas MQTT (Verificado en Código)

Configuración centralizada y sincronizada en [`backend/config.py`](backend/config.py) y [`wokwi/main.py`](wokwi/main.py):
- **Broker por defecto:** `broker.hivemq.com` (Puerto `1883`; alternativo comentado: `test.mosquitto.org`)
- **Identificador de grupo:** `GRUPO = "grupo"`

| Tema MQTT | Dirección | QoS | Retenido | Contenido / Formato |
| :--- | :--- | :--- | :--- | :--- |
| `utp/ds8/grupo/aquaweb/telemetria` | Dispositivo → Broker | `0` (publicación ESP32 y suscripción backend) | No (`False`) | JSON con `ph`, `temperatura`, `actuador`, `modo`, `umbral_ph_min`, `umbral_ph_max` |
| `utp/ds8/grupo/aquaweb/estado` | Dispositivo → Broker | `1` (publicación `ONLINE`, Testamento LWT `OFFLINE` y suscripción del monitor) | Sí (`True`) | Cadena `"ONLINE"` al conectar / `"OFFLINE"` emitido automáticamente por el broker vía LWT |
| `utp/ds8/grupo/aquaweb/ordenes` | Broker → Dispositivo | `1` (publicación emisor CLI) / `0` (suscripción ESP32 en `umqtt_simple.py`) | No (`False`) | JSON para cambio de `modo`/`actuador`, ajuste de umbrales (`umbral_ph_min`, `umbral_ph_max`) o `simular_silencio` |

---

## 3. Estructura del Repositorio

```text
Avance 3/
├── wokwi/
│   ├── diagram.json                 # Circuito ESP32 (pH, DHT22, 2 LEDs, botón IRQ)
│   ├── umqtt_simple.py              # Cliente MQTT ligero local para MicroPython
│   └── main.py                      # Firmware ESP32 MicroPython v1.20+ (MQTT + LWT + Backoff)
├── backend/
│   ├── config.py                    # Parámetros centralizados (broker, grupo, temas, rangos)
│   ├── receptor_mqtt.py             # Receptor paho-mqtt v2 con validación y CSV de telemetría
│   ├── monitor_estado.py            # Monitor independiente ONLINE / SIN_DATOS / OFFLINE
│   ├── simulador_pruebas.py         # Utilidad CLI emisora de órdenes y tramas de prueba
│   ├── simulacion_sensores.py       # Simulador local heredado del Avance 2
│   └── data/
│       ├── telemetria_valida.csv    # Lecturas validadas recibidas por MQTT
│       ├── eventos_comunicacion.csv # Cambios de estado del enlace MQTT
│       ├── estado_actual.json       # Persistencia JSON del Avance 2
│       └── historial_sensores.csv   # Historial CSV del Avance 2
├── docs/
│   ├── diagrama_flujo_avance3.puml  # Código fuente PlantUML del diagrama de flujo
│   ├── informe_avance3.md           # Informe técnico completo (<= 5 páginas)
│   ├── generar_informe_docx.py      # Generador automático de DOCX (Arial 12, justificado)
│   ├── Informe_Avance3_AquaWeb_IoT.docx
│   ├── Informe_Avance3_AquaWeb_IoT.pdf
│   └── assets/                      # Diagrama renderizado y capturas de evidencia
├── requirements.txt                 # Dependencias del backend (paho-mqtt>=2.1.0)
└── README.md                        # Documentación general del Avance 3
```

---

## 4. Tabla de Pines GPIO (ESP32 DevKitC v4 en Wokwi)

| Componente | Pin del Componente | Pin ESP32 | Configuración | Función |
| :--- | :--- | :--- | :--- | :--- |
| `wokwi-potentiometer` (`pot_ph`) | `SIG` | **GPIO 34** | `ADC`, `ADC.ATTN_11DB`, `12-bit` | Sensor simulado de pH (`0.00` – `14.00`) |
| `wokwi-dht22` (`dht_temp`) | `SDA` | **GPIO 15** | Bus 1-Wire (`dht.DHT22`) | Sensor de temperatura (`°C`) |
| `wokwi-led` rojo + `220 Ω` (`led_bomba`) | `A` / `C` | **GPIO 2** / `GND.2` | `Pin.OUT` | Actuador bomba / aireador |
| `wokwi-led` azul + `220 Ω` (`led_estado`) | `A` / `C` | **GPIO 5** / `GND.2` | `Pin.OUT` | Indicador Wi-Fi/MQTT (fijo: conectado; parpadeo/apagado: desconectado) |
| `wokwi-pushbutton` verde (`btn_emergencia`) | `1.l` / `2.l` | `3V3` / **GPIO 4** | `Pin.IN`, `PULL_DOWN`, `IRQ_RISING` | Interrupción física de bypass manual (`debounce 250 ms`) |

---

## 5. Instrucciones para Reproducir la Demostración en Clase

### Paso 1: Instalar dependencias del backend
```bash
pip install -r requirements.txt
```

### Paso 2: Iniciar el Receptor MQTT y el Monitor de Estado (en terminales separadas)
1. **Terminal 1 — Receptor de telemetría:**
   ```bash
   python backend/receptor_mqtt.py
   ```
   Se suscribe a `utp/ds8/grupo/aquaweb/#`, guarda lecturas válidas en `backend/data/telemetria_valida.csv` y descarta mensajes corruptos o fuera de rango sin detenerse.

2. **Terminal 2 — Monitor de estado de comunicación:**
   ```bash
   python backend/monitor_estado.py
   ```
   Evalúa cada `1 s` el silencio máximo (`SILENCIO_MAX_SEG = 20 s`) y registra únicamente transiciones entre `ONLINE`, `SIN_DATOS` y `OFFLINE` en `backend/data/eventos_comunicacion.csv`.

### Paso 3: Ejecutar el Nodo ESP32 en Wokwi
1. Abrir Wokwi y cargar los 3 archivos de `wokwi/`: `diagram.json`, `umqtt_simple.py` y `main.py` (confirmando `GRUPO = "grupo"` y `MQTT_BROKER = "broker.hivemq.com"`).
2. Presionar **Start Simulation**. El LED azul (`GPIO 5`) parpadea durante el enlace Wi-Fi y queda fijo al publicar `ONLINE` retenido (QoS 1) en `utp/ds8/grupo/aquaweb/estado`.
3. Variar el potenciómetro (`GPIO 34`) y el DHT22 (`GPIO 15`) para observar las lecturas reales llegando a `receptor_mqtt.py` cada 5 s y el encendido del LED rojo (`GPIO 2`) al salir del rango óptimo.

### Paso 4: Enviar Órdenes y Provocar Escenarios con el Emisor CLI
En una **Terminal 3**, utilizar `backend/simulador_pruebas.py` exclusivamente como **emisor de pruebas**:
```bash
# Enviar órdenes válidas al ESP32 en Wokwi (se observa [ORDEN APLICADA] y cambio de LED rojo)
python backend/simulador_pruebas.py --escenario orden-valida

# Enviar órdenes inválidas al ESP32 en Wokwi (se observa [ORDEN RECHAZADA] sin alterar estado)
python backend/simulador_pruebas.py --escenario orden-invalida

# Inyectar telemetría corrupta hacia receptor_mqtt.py (descarte sin detener el servicio)
python backend/simulador_pruebas.py --escenario dato-invalido

# Provocar estado SIN_DATOS manteniendo keepalive (PINGREQ activo en el ESP32)
python backend/simulador_pruebas.py --escenario silencio-on
# (Esperar > 20 s hasta ver ONLINE -> SIN_DATOS en monitor_estado.py, luego reanudar:)
python backend/simulador_pruebas.py --escenario silencio-off
```

### Paso 5: Verificar el Testamento LWT Real (`OFFLINE`)
1. Con la simulación de Wokwi corriendo y el monitor en `ONLINE`, presionar **Stop Simulation** en Wokwi (sin enviar `DISCONNECT`).
2. Transcurrido el `keepalive` (`15 s` + margen de gracia del broker), el broker `broker.hivemq.com` dispara automáticamente el Last Will `"OFFLINE"` (QoS 1, retenido) en `utp/ds8/grupo/aquaweb/estado`, lo cual registra la transición `ONLINE -> OFFLINE (CRITICO)` en `monitor_estado.py` y `eventos_comunicacion.csv`.

### Paso 6: Regenerar el Informe Técnico (DOCX y PDF)
```bash
python docs/generar_informe_docx.py
```
Luego exportar `docs/Informe_Avance3_AquaWeb_IoT.docx` a `docs/Informe_Avance3_AquaWeb_IoT.pdf` (con Microsoft Word o LibreOffice).
