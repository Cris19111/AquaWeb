"""Firmware MicroPython (v1.20+) para ESP32 - AquaWeb IoT (Avance 3).

Módulo de Comunicación MQTT + Adquisición Local para estanques camaroneros:
- Sensor 1 (pH simulado): Potenciómetro en GPIO 34 (ADC con ADC.ATTN_11DB).
- Sensor 2 (Temperatura): Sensor DHT22 en GPIO 15.
- Actuador (Bomba/Aireador): LED rojo con resistencia de 220 Ω en GPIO 2.
- Indicador de conexión Wi-Fi/MQTT: LED azul con resistencia de 220 Ω en GPIO 5.
- Botón físico de interrupción (Bypass manual): Pushbutton verde en GPIO 4
  configurado con Pin.PULL_DOWN, Pin.IRQ_RISING y debounce por software.
"""

import dht
import json
import math
from machine import ADC, Pin
import network
import time
import ubinascii
import machine

from umqtt_simple import MQTTClient, MQTTException

# ============================================================================
# CONFIGURACIÓN EDITABLE (Único punto de ajuste del nodo ESP32)
# ============================================================================
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""

MQTT_BROKER = "broker.hivemq.com"
# MQTT_BROKER = "test.mosquitto.org"  # Broker público alternativo
MQTT_PORT = 1883
MQTT_KEEPALIVE = 15

GRUPO = "grupo"
TOPIC_PREFIX = "utp/ds8/{}/aquaweb".format(GRUPO)
TOPIC_TELEMETRIA = "{}/telemetria".format(TOPIC_PREFIX)
TOPIC_ESTADO = "{}/estado".format(TOPIC_PREFIX)
TOPIC_ORDENES = "{}/ordenes".format(TOPIC_PREFIX)

INTERVALO_PUB_MS = 5000      # Publicación de telemetría cada 5 segundos
INTERVALO_MUESTREO_MS = 2000 # Muestreo local (útil en operación offline)
INTERVALO_PING_MS = 7000     # Keepalive PINGREQ cuando hay silencio simulado
INTERVALO_PARPADEO_MS = 400  # Parpadeo del LED azul cuando está desconectado
DEBOUNCE_MS = 250

# Backoff exponencial de reconexión: 2 -> 4 -> 8 -> 16 -> 32 -> 60 s
BACKOFF_INICIAL_S = 2
BACKOFF_MAX_S = 60

# ============================================================================
# ASIGNACIÓN DE PINES GPIO (ESP32 DevKitC v4)
# ============================================================================
PIN_POT_PH = 34
PIN_DHT_TEMP = 15
PIN_LED_ACTUADOR = 2
PIN_LED_CONEXION = 5
PIN_BTN_BYPASS = 4

ADC_MAX_12BIT = 4095
PH_MIN_ESCALA = 0.0
PH_MAX_ESCALA = 14.0

# Umbrales por defecto (temperatura fija de Avance 2, umbrales de pH editables vía MQTT)
TEMP_OPTIMA_MIN = 20.0
TEMP_OPTIMA_MAX = 30.0

# ============================================================================
# INICIALIZACIÓN DE PERIFÉRICOS
# ============================================================================
adc_ph = ADC(Pin(PIN_POT_PH))
adc_ph.atten(ADC.ATTN_11DB)    # Obligatorio en MicroPython v1.20+ (nunca ATTN_11V)
adc_ph.width(ADC.WIDTH_12BIT)  # Resolución 0 - 4095

sensor_dht = dht.DHT22(Pin(PIN_DHT_TEMP))

led_actuador = Pin(PIN_LED_ACTUADOR, Pin.OUT)
led_actuador.value(0)

led_conexion = Pin(PIN_LED_CONEXION, Pin.OUT)
led_conexion.value(0)

btn_bypass = Pin(PIN_BTN_BYPASS, Pin.IN, Pin.PULL_DOWN)

# ============================================================================
# ESTADO GLOBAL DEL SISTEMA Y VARIABLES DE INTERRUPCIÓN
# ============================================================================
estado_sistema = {
    "modo": "AUTO",           # "AUTO" | "MANUAL"
    "actuador": 0,            # 0 | 1
    "umbral_ph_min": 6.5,
    "umbral_ph_max": 9.5,
    "simular_silencio": False,
}

# Banderas compartidas con la ISR del botón físico (GPIO 4)
irq_cambio_pendiente = False
irq_ultimo_ms = 0


def isr_boton_bypass(pin):
    """Rutina de interrupción (ISR) en GPIO 4 con debounce por software."""
    global irq_cambio_pendiente, irq_ultimo_ms
    ahora = time.ticks_ms()
    if time.ticks_diff(ahora, irq_ultimo_ms) > DEBOUNCE_MS:
        irq_ultimo_ms = ahora
        irq_cambio_pendiente = True


btn_bypass.irq(trigger=Pin.IRQ_RISING, handler=isr_boton_bypass)


def leer_ph():
    """Lee el ADC de GPIO 34 y escala linealmente a 0.00 - 14.00 pH."""
    crudo = adc_ph.read()
    ph = PH_MIN_ESCALA + (crudo / ADC_MAX_12BIT) * (PH_MAX_ESCALA - PH_MIN_ESCALA)
    return round(ph, 2)


def leer_temperatura(respaldo_temp):
    """Lee la temperatura del DHT22 en GPIO 15 protegiendo errores 1-Wire."""
    try:
        sensor_dht.measure()
        return round(sensor_dht.temperature(), 2), True
    except OSError:
        return respaldo_temp, False


def actualizar_actuador(ph, temp):
    """Aplica control automático por umbrales o mantiene el estado manual."""
    if estado_sistema["modo"] == "MANUAL":
        led_actuador.value(estado_sistema["actuador"])
        return

    fuera_de_rango = (
        ph < estado_sistema["umbral_ph_min"]
        or ph > estado_sistema["umbral_ph_max"]
        or temp < TEMP_OPTIMA_MIN
        or temp > TEMP_OPTIMA_MAX
    )
    estado_sistema["actuador"] = 1 if fuera_de_rango else 0
    led_actuador.value(estado_sistema["actuador"])


def procesar_irq_boton(ph, temp):
    """Atiende fuera de la ISR la conmutación del botón físico de bypass."""
    global irq_cambio_pendiente
    if not irq_cambio_pendiente:
        return False

    irq_cambio_pendiente = False
    if estado_sistema["modo"] == "AUTO":
        estado_sistema["modo"] = "MANUAL"
        estado_sistema["actuador"] = 1
        led_actuador.value(1)
        print("[IRQ GPIO 4] Boton presionado -> Modo MANUAL (Bypass FORZADO ON)")
    else:
        estado_sistema["modo"] = "AUTO"
        actualizar_actuador(ph, temp)
        print(
            "[IRQ GPIO 4] Boton presionado -> Modo AUTO restaurado | actuador={}".format(
                estado_sistema["actuador"]
            )
        )
    return True


def _es_numero_valido(valor):
    """Verifica que un valor sea int o float finito (excluyendo bool)."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return False
    return not (math.isnan(valor) or math.isinf(valor))


def validar_y_aplicar_orden(payload_bytes):
    """Valida estrictamente una orden JSON recibida en .../ordenes.

    No altera ningún parámetro si alguna validación falla.
    """
    try:
        texto = payload_bytes.decode("utf-8")
        data = json.loads(texto)
    except Exception as err:
        print("[ORDEN RECHAZADA] JSON corrupto o no decodificable:", err)
        return

    if not isinstance(data, dict) or len(data) == 0:
        print("[ORDEN RECHAZADA] El payload debe ser un objeto JSON no vacío.")
        return

    claves_permitidas = (
        "modo",
        "actuador",
        "umbral_ph_min",
        "umbral_ph_max",
        "simular_silencio",
    )
    for clave in data:
        if clave not in claves_permitidas:
            print("[ORDEN RECHAZADA] Clave no permitida en orden:", clave)
            return

    nuevo_modo = estado_sistema["modo"]
    nuevo_actuador = estado_sistema["actuador"]
    nuevo_ph_min = estado_sistema["umbral_ph_min"]
    nuevo_ph_max = estado_sistema["umbral_ph_max"]
    nuevo_silencio = estado_sistema["simular_silencio"]

    if "modo" in data:
        modo = data["modo"]
        if not isinstance(modo, str) or modo not in ("AUTO", "MANUAL"):
            print("[ORDEN RECHAZADA] 'modo' inválido (use 'AUTO' o 'MANUAL'):", modo)
            return
        nuevo_modo = modo

    if "actuador" in data:
        act = data["actuador"]
        if isinstance(act, bool) or not isinstance(act, int) or act not in (0, 1):
            print("[ORDEN RECHAZADA] 'actuador' debe ser entero 0 o 1:", act)
            return
        if nuevo_modo != "MANUAL":
            print("[ORDEN RECHAZADA] No se puede fijar 'actuador' en modo AUTO.")
            return
        nuevo_actuador = act

    if "umbral_ph_min" in data:
        val_min = data["umbral_ph_min"]
        if not _es_numero_valido(val_min):
            print("[ORDEN RECHAZADA] 'umbral_ph_min' debe ser numérico:", val_min)
            return
        nuevo_ph_min = round(float(val_min), 2)

    if "umbral_ph_max" in data:
        val_max = data["umbral_ph_max"]
        if not _es_numero_valido(val_max):
            print("[ORDEN RECHAZADA] 'umbral_ph_max' debe ser numérico:", val_max)
            return
        nuevo_ph_max = round(float(val_max), 2)

    if not (0.0 <= nuevo_ph_min < nuevo_ph_max <= 14.0):
        print(
            "[ORDEN RECHAZADA] Rango lógico de pH inválido (0.0 <= min < max <= 14.0): "
            "min={}, max={}".format(nuevo_ph_min, nuevo_ph_max)
        )
        return

    if "simular_silencio" in data:
        silencio = data["simular_silencio"]
        if not isinstance(silencio, bool):
            print("[ORDEN RECHAZADA] 'simular_silencio' debe ser booleano:", silencio)
            return
        nuevo_silencio = silencio

    # Aplicar cambios de forma atómica tras superar todas las validaciones
    estado_sistema["modo"] = nuevo_modo
    estado_sistema["actuador"] = nuevo_actuador
    estado_sistema["umbral_ph_min"] = nuevo_ph_min
    estado_sistema["umbral_ph_max"] = nuevo_ph_max
    estado_sistema["simular_silencio"] = nuevo_silencio

    if estado_sistema["modo"] == "MANUAL":
        led_actuador.value(estado_sistema["actuador"])

    print(
        "[ORDEN APLICADA] modo={} | actuador={} | umbrales_ph=[{}, {}] | silencio={}".format(
            estado_sistema["modo"],
            estado_sistema["actuador"],
            estado_sistema["umbral_ph_min"],
            estado_sistema["umbral_ph_max"],
            estado_sistema["simular_silencio"],
        )
    )


def on_mqtt_message(topic, msg):
    """Callback ejecutado cuando llega un mensaje por MQTT."""
    topic_str = topic.decode("utf-8") if isinstance(topic, bytes) else str(topic)
    print("[MQTT RX] {} -> {}".format(topic_str, msg))
    if topic_str == TOPIC_ORDENES:
        validar_y_aplicar_orden(msg)


def construir_client_id():
    """Genera un identificador único basado en la MAC del ESP32."""
    uid = ubinascii.hexlify(machine.unique_id()).decode("utf-8")
    return "aquaweb-esp32-{}-{}".format(GRUPO, uid[-6:])


def conectar_wifi(wlan, timeout_ms=8000):
    """Intenta conectar la interfaz Wi-Fi STA sin bloquear indefinidamente."""
    if not wlan.active():
        wlan.active(True)
    if wlan.isconnected():
        return True

    print("[WIFI] Conectando a '{}'...".format(WIFI_SSID))
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    inicio = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), inicio) >= timeout_ms:
            print("[WIFI ERROR] Tiempo de espera agotado conectando a Wi-Fi.")
            return False
        # Parpadeo corto durante intento de enlace
        led_conexion.value(1 - led_conexion.value())
        time.sleep_ms(150)

    print("[WIFI OK] IP asignada:", wlan.ifconfig()[0])
    return True


def conectar_mqtt(client_id):
    """Crea el cliente MQTT, registra Last Will y publica estado ONLINE."""
    client = MQTTClient(
        client_id=client_id,
        server=MQTT_BROKER,
        port=MQTT_PORT,
        keepalive=MQTT_KEEPALIVE,
    )
    client.set_callback(on_mqtt_message)

    # Configurar Testamento (Last Will) ANTES de connect()
    client.set_last_will(TOPIC_ESTADO, b"OFFLINE", retain=True, qos=1)

    print("[MQTT] Conectando a {}:{} (keepalive={}s)...".format(
        MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE
    ))
    client.connect(clean_session=True)
    client.subscribe(TOPIC_ORDENES, qos=0)
    client.publish(TOPIC_ESTADO, b"ONLINE", retain=True, qos=1)
    print("[MQTT OK] Conectado. Publicado ONLINE (retain=True) en {}".format(TOPIC_ESTADO))
    return client


def publicar_telemetria(client, ph, temp):
    """Serializa y publica la trama JSON de telemetría actual."""
    payload = {
        "ph": ph,
        "temperatura": temp,
        "actuador": estado_sistema["actuador"],
        "modo": estado_sistema["modo"],
        "umbral_ph_min": estado_sistema["umbral_ph_min"],
        "umbral_ph_max": estado_sistema["umbral_ph_max"],
    }
    trama = json.dumps(payload)
    client.publish(TOPIC_TELEMETRIA, trama.encode("utf-8"), retain=False, qos=0)
    print("[TELEMETRIA TX] {} -> {}".format(TOPIC_TELEMETRIA, trama))


def main():
    """Bucle principal no bloqueante con operación offline y backoff exponencial."""
    print("==================================================================")
    print("  AquaWeb IoT - Avance 3: ESP32 MicroPython + Comunicacion MQTT")
    print("  Broker: {}:{} | Grupo: {}".format(MQTT_BROKER, MQTT_PORT, GRUPO))
    print("  Temas : {}/*".format(TOPIC_PREFIX))
    print("==================================================================")

    wlan = network.WLAN(network.STA_IF)
    client_id = construir_client_id()
    mqtt_client = None
    conectado = False

    backoff_s = BACKOFF_INICIAL_S
    proximo_reintento_ms = time.ticks_ms()

    ultima_temp_valida = 26.0
    ph = leer_ph()
    temp, dht_ok = leer_temperatura(ultima_temp_valida)
    if dht_ok:
        ultima_temp_valida = temp
    actualizar_actuador(ph, temp)

    ahora = time.ticks_ms()
    ultimo_pub_ms = time.ticks_add(ahora, -INTERVALO_PUB_MS)
    ultimo_muestreo_ms = ahora
    ultimo_ping_ms = ahora
    ultimo_parpadeo_ms = ahora

    while True:
        ahora = time.ticks_ms()

        # 1. Atender botón físico en todo momento (online u offline)
        if procesar_irq_boton(ph, temp) and conectado and not estado_sistema["simular_silencio"]:
            try:
                publicar_telemetria(mqtt_client, ph, temp)
                ultimo_pub_ms = ahora
                ultimo_ping_ms = ahora
            except (OSError, MQTTException, Exception) as err:
                print("[MQTT ERROR] Fallo al publicar tras IRQ:", err)
                conectado = False

        # 2. Muestreo local periódico y protección automática del actuador
        if time.ticks_diff(ahora, ultimo_muestreo_ms) >= INTERVALO_MUESTREO_MS:
            ultimo_muestreo_ms = ahora
            ph = leer_ph()
            temp, dht_ok = leer_temperatura(ultima_temp_valida)
            if dht_ok:
                ultima_temp_valida = temp
            actualizar_actuador(ph, temp)

        # 3. Gestión de conexión y backoff exponencial no bloqueante
        if not conectado:
            if time.ticks_diff(ahora, ultimo_parpadeo_ms) >= INTERVALO_PARPADEO_MS:
                ultimo_parpadeo_ms = ahora
                led_conexion.value(1 - led_conexion.value())

            if time.ticks_diff(ahora, proximo_reintento_ms) >= 0:
                try:
                    if conectar_wifi(wlan):
                        mqtt_client = conectar_mqtt(client_id)
                        conectado = True
                        led_conexion.value(1)  # Fijo encendido al estar conectado
                        backoff_s = BACKOFF_INICIAL_S
                        ultimo_pub_ms = time.ticks_add(time.ticks_ms(), -INTERVALO_PUB_MS)
                        ultimo_ping_ms = time.ticks_ms()
                    else:
                        raise OSError("Wi-Fi sin enlace")
                except (OSError, MQTTException, Exception) as err:
                    conectado = False
                    led_conexion.value(0)
                    if mqtt_client is not None:
                        try:
                            mqtt_client.sock.close()
                        except Exception:
                            pass
                        mqtt_client = None
                    print(
                        "[OFFLINE] Fallo de red ({}). Operando localmente; reintento en {} s...".format(
                            err, backoff_s
                        )
                    )
                    proximo_reintento_ms = time.ticks_add(time.ticks_ms(), backoff_s * 1000)
                    backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
        else:
            # Verificar que el Wi-Fi siga activo
            if not wlan.isconnected():
                print("[WIFI CAIDO] Se perdió la conexión Wi-Fi. Pasando a operación offline.")
                conectado = False
                led_conexion.value(0)
                if mqtt_client is not None:
                    try:
                        mqtt_client.sock.close()
                    except Exception:
                        pass
                    mqtt_client = None
                proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
                continue

            led_conexion.value(1)

            # 4. Revisar órdenes MQTT entrantes de forma no bloqueante
            try:
                mqtt_client.check_msg()
            except (OSError, MQTTException, Exception) as err:
                print("[MQTT ERROR] Desconexión al leer mensajes:", err)
                conectado = False
                led_conexion.value(0)
                try:
                    mqtt_client.sock.close()
                except Exception:
                    pass
                mqtt_client = None
                proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
                continue

            # 5. Publicación periódica cada INTERVALO_PUB_MS (o ping en silencio controlado)
            if estado_sistema["simular_silencio"]:
                if time.ticks_diff(ahora, ultimo_ping_ms) >= INTERVALO_PING_MS:
                    try:
                        mqtt_client.ping()
                        ultimo_ping_ms = ahora
                        print("[SILENCIO ACTIVO] PINGREQ enviado (sin telemetría) para prueba SIN_DATOS.")
                    except (OSError, MQTTException, Exception) as err:
                        print("[MQTT ERROR] Fallo en ping:", err)
                        conectado = False
                        led_conexion.value(0)
                        mqtt_client = None
                        proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                        backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
            else:
                if time.ticks_diff(ahora, ultimo_pub_ms) >= INTERVALO_PUB_MS:
                    ultimo_pub_ms = ahora
                    ph = leer_ph()
                    temp, dht_ok = leer_temperatura(ultima_temp_valida)
                    if dht_ok:
                        ultima_temp_valida = temp
                    actualizar_actuador(ph, temp)
                    try:
                        publicar_telemetria(mqtt_client, ph, temp)
                        ultimo_ping_ms = ahora
                    except (OSError, MQTTException, Exception) as err:
                        print("[MQTT ERROR] Fallo al publicar telemetría:", err)
                        conectado = False
                        led_conexion.value(0)
                        try:
                            mqtt_client.sock.close()
                        except Exception:
                            pass
                        mqtt_client = None
                        proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                        backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)

        # Pequeña pausa no bloqueante para ceder CPU sin afectar IRQ ni check_msg
        time.sleep_ms(50)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        led_actuador.value(0)
        led_conexion.value(0)
        print("\n[INFO] Ejecución detenida manualmente.")
