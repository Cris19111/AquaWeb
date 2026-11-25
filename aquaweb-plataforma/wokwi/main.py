"""Firmware MicroPython v1.20+ para ESP32 — Plataforma AquaWeb IoT.

Monitoreo y control determinístico (sin IA/ML) para estanques camaroneros:
- GPIO 34: Potenciómetro pH (0.00 – 14.00 pH) con ADC.ATTN_11DB (nunca ATTN_11V)
- GPIO 15: Sensor DHT22 de Temperatura (°C)
- GPIO 35: Potenciómetro Conductividad/EC base (0 – 50000 ppm), derivando
           coherentemente TDS (~0.48 * EC) y Salinidad (~0.65 * EC)
- GPIO 2 : Actuador Bomba/Aireador (LED rojo + 220 Ohm)
- GPIO 5 : Indicador de conectividad Wi-Fi/MQTT (LED azul + 220 Ohm)
- GPIO 4 : Botón físico de bypass manual (PULL_DOWN, IRQ_RISING, debounce)
"""

import dht
import json
import math
from machine import ADC, Pin
import machine
import network
import time
import ubinascii

from umqtt_simple import MQTTClient, MQTTException

# ============================================================================
# CONFIGURACIÓN DEL NODO Y TEMAS MQTT
# ============================================================================
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 15

GRUPO = "grupo"
DEVICE_ID = "estanque-01"
TOPIC_PREFIX = "utp/ds8/{}/aquaweb/{}".format(GRUPO, DEVICE_ID)
TOPIC_TELEMETRIA = "{}/telemetria".format(TOPIC_PREFIX)
TOPIC_ESTADO = "{}/estado".format(TOPIC_PREFIX)
TOPIC_ORDENES = "{}/ordenes".format(TOPIC_PREFIX)
TOPIC_ORDENES_ACK = "{}/ordenes_ack".format(TOPIC_PREFIX)

INTERVALO_PUB_MS = 5000
INTERVALO_MUESTREO_MS = 2000
INTERVALO_PING_MS = 7000
INTERVALO_PARPADEO_MS = 400
DEBOUNCE_MS = 250

BACKOFF_INICIAL_S = 2
BACKOFF_MAX_S = 60

# ============================================================================
# PINES GPIO (ESP32 DevKitC v4)
# ============================================================================
PIN_POT_PH = 34
PIN_POT_EC = 35
PIN_DHT_TEMP = 15
PIN_LED_ACTUADOR = 2
PIN_LED_CONEXION = 5
PIN_BTN_BYPASS = 4

ADC_MAX_12BIT = 4095

# ============================================================================
# INICIALIZACIÓN DE PERIFÉRICOS (MicroPython v1.20+)
# ============================================================================
adc_ph = ADC(Pin(PIN_POT_PH))
adc_ph.atten(ADC.ATTN_11DB)
adc_ph.width(ADC.WIDTH_12BIT)

adc_ec = ADC(Pin(PIN_POT_EC))
adc_ec.atten(ADC.ATTN_11DB)
adc_ec.width(ADC.WIDTH_12BIT)

sensor_dht = dht.DHT22(Pin(PIN_DHT_TEMP))

led_actuador = Pin(PIN_LED_ACTUADOR, Pin.OUT)
led_actuador.value(0)

led_conexion = Pin(PIN_LED_CONEXION, Pin.OUT)
led_conexion.value(0)

btn_bypass = Pin(PIN_BTN_BYPASS, Pin.IN, Pin.PULL_DOWN)

# ============================================================================
# ESTADO DEL NODO Y UMBRALES ÓPTIMOS/FÍSICOS DE REFERENCIA
# ============================================================================
LIMITES_FISICOS = {
    "ph": (0.0, 14.0),
    "temperatura": (-5.0, 60.0),
    "tds": (0.0, 50000.0),
    "ec": (0.0, 80000.0),
    "salinidad": (0.0, 50000.0),
}

estado_sistema = {
    "modo_operacion": "AUTO",     # "AUTO" | "MANUAL"
    "actuador_estado": False,     # True | False
    "simular_silencio": False,
    "umbrales": {
        "ph": {"min": 6.5, "max": 9.5},
        "temperatura": {"min": 20.0, "max": 30.0},
        "tds": {"min": 4000.0, "max": 15000.0},
        "ec": {"min": 10000.0, "max": 35000.0},
        "salinidad": {"min": 5000.0, "max": 23000.0},
    },
}

mqtt_cliente_activo = None
irq_cambio_pendiente = False
irq_ultimo_ms = 0


def isr_boton_bypass(pin):
    """Interrupción física en GPIO 4 con antirrebote por software."""
    global irq_cambio_pendiente, irq_ultimo_ms
    ahora = time.ticks_ms()
    if time.ticks_diff(ahora, irq_ultimo_ms) > DEBOUNCE_MS:
        irq_ultimo_ms = ahora
        irq_cambio_pendiente = True


btn_bypass.irq(trigger=Pin.IRQ_RISING, handler=isr_boton_bypass)


def leer_ph():
    """Escala ADC 12-bit de GPIO 34 a pH 0.00 - 14.00."""
    crudo = adc_ph.read()
    return round((crudo / ADC_MAX_12BIT) * 14.0, 2)


def leer_conductividad_y_derivados():
    """Lee EC en GPIO 35 (0 - 45000 ppm) y deriva TDS y Salinidad coherentemente."""
    crudo = adc_ec.read()
    ec_ppm = round((crudo / ADC_MAX_12BIT) * 45000.0, 2)
    tds_ppm = round(min(50000.0, ec_ppm * 0.48), 2)
    salinidad_ppm = round(min(50000.0, ec_ppm * 0.65), 2)
    return ec_ppm, tds_ppm, salinidad_ppm


def leer_temperatura(respaldo_temp):
    """Lee DHT22 en GPIO 15 protegiendo fallos temporales 1-Wire."""
    try:
        sensor_dht.measure()
        return round(sensor_dht.temperature(), 2), True
    except OSError:
        return respaldo_temp, False


def actualizar_actuador(lecturas):
    """Control determinístico por umbrales en AUTO o control directo en MANUAL."""
    if estado_sistema["modo_operacion"] == "MANUAL":
        led_actuador.value(1 if estado_sistema["actuador_estado"] else 0)
        return

    u = estado_sistema["umbrales"]
    fuera_rango = (
        lecturas["ph"] < u["ph"]["min"]
        or lecturas["ph"] > u["ph"]["max"]
        or lecturas["temperatura_c"] < u["temperatura"]["min"]
        or lecturas["temperatura_c"] > u["temperatura"]["max"]
        or lecturas["tds_ppm"] < u["tds"]["min"]
        or lecturas["tds_ppm"] > u["tds"]["max"]
        or lecturas["ec_ppm"] < u["ec"]["min"]
        or lecturas["ec_ppm"] > u["ec"]["max"]
        or lecturas["salinidad_ppm"] < u["salinidad"]["min"]
        or lecturas["salinidad_ppm"] > u["salinidad"]["max"]
    )
    estado_sistema["actuador_estado"] = fuera_rango
    led_actuador.value(1 if fuera_rango else 0)


def procesar_irq_boton(lecturas):
    """Atiende fuera de la ISR la conmutación del bypass manual (GPIO 4)."""
    global irq_cambio_pendiente
    if not irq_cambio_pendiente:
        return False

    irq_cambio_pendiente = False
    if estado_sistema["modo_operacion"] == "AUTO":
        estado_sistema["modo_operacion"] = "MANUAL"
        estado_sistema["actuador_estado"] = True
        led_actuador.value(1)
        print("[IRQ GPIO 4] Bypass manual ACTIVADO -> modo=MANUAL, actuador=ON")
    else:
        estado_sistema["modo_operacion"] = "AUTO"
        actualizar_actuador(lecturas)
        print(
            "[IRQ GPIO 4] Modo AUTO restaurado -> actuador={}".format(
                "ON" if estado_sistema["actuador_estado"] else "OFF"
            )
        )
    return True


def _es_numero_valido(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return False
    return not (math.isnan(valor) or math.isinf(valor))


def enviar_ack(command_id, estado, detalle):
    """Publica acuse de recibo QoS 1 en .../ordenes_ack."""
    if mqtt_cliente_activo is None or not command_id:
        return
    ack = {
        "command_id": command_id,
        "device_id": DEVICE_ID,
        "estado": estado,
        "detalle": detalle,
    }
    try:
        mqtt_cliente_activo.publish(
            TOPIC_ORDENES_ACK,
            json.dumps(ack).encode("utf-8"),
            retain=False,
            qos=1,
        )
        print("[ORDEN ACK TX] {} -> {}".format(estado, detalle))
    except Exception as err:
        print("[ACK ERROR] No se pudo publicar ACK:", err)


def validar_y_aplicar_orden(payload_bytes):
    """Valida atómicamente una orden JSON recibida y responde en .../ordenes_ack."""
    command_id = None
    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception as err:
        print("[ORDEN RECHAZADA] JSON malformado:", err)
        return

    if not isinstance(data, dict) or len(data) == 0:
        print("[ORDEN RECHAZADA] Payload vacío o no es objeto JSON.")
        return

    command_id = data.get("command_id")
    nuevo_modo = estado_sistema["modo_operacion"]
    nuevo_actuador = estado_sistema["actuador_estado"]
    nuevo_silencio = estado_sistema["simular_silencio"]
    nuevos_umbrales = {}

    if "modo" in data:
        modo = data["modo"]
        if not isinstance(modo, str) or modo not in ("AUTO", "MANUAL"):
            msg = "Modo inválido: {}".format(modo)
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        nuevo_modo = modo

    if "actuador" in data:
        act = data["actuador"]
        if isinstance(act, bool):
            act_bool = act
        elif isinstance(act, int) and act in (0, 1):
            act_bool = bool(act)
        else:
            msg = "Valor de actuador inválido: {}".format(act)
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        if nuevo_modo != "MANUAL":
            msg = "No se permite forzar actuador en modo AUTO."
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        nuevo_actuador = act_bool

    if "parametro" in data:
        param = data["parametro"]
        if param not in LIMITES_FISICOS:
            msg = "Parámetro desconocido: {}".format(param)
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        min_opt = data.get("min_optimo")
        max_opt = data.get("max_optimo")
        if not (_es_numero_valido(min_opt) and _es_numero_valido(max_opt)):
            msg = "Umbrales no numéricos para {}".format(param)
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        min_f, max_f = LIMITES_FISICOS[param]
        min_v = round(float(min_opt), 2)
        max_v = round(float(max_opt), 2)
        if not (min_f <= min_v < max_v <= max_f):
            msg = "Rango inválido para {}: [{}, {}] fuera de [{}, {}]".format(
                param, min_v, max_v, min_f, max_f
            )
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        nuevos_umbrales[param] = {"min": min_v, "max": max_v}

    if "simular_silencio" in data:
        sil = data["simular_silencio"]
        if not isinstance(sil, bool):
            msg = "simular_silencio debe ser booleano."
            print("[ORDEN RECHAZADA]", msg)
            enviar_ack(command_id, "RECHAZADA", msg)
            return
        nuevo_silencio = sil

    # Aplicación atómica
    estado_sistema["modo_operacion"] = nuevo_modo
    estado_sistema["actuador_estado"] = nuevo_actuador
    estado_sistema["simular_silencio"] = nuevo_silencio
    for k, v in nuevos_umbrales.items():
        estado_sistema["umbrales"][k] = v

    if estado_sistema["modo_operacion"] == "MANUAL":
        led_actuador.value(1 if estado_sistema["actuador_estado"] else 0)

    resumen = "modo={} actuador={} umbrales_actualizados={}".format(
        estado_sistema["modo_operacion"],
        estado_sistema["actuador_estado"],
        list(nuevos_umbrales.keys()),
    )
    print("[ORDEN APLICADA]", resumen)
    enviar_ack(command_id, "APLICADA", resumen)


def on_mqtt_message(topic, msg):
    topic_str = topic.decode("utf-8") if isinstance(topic, bytes) else str(topic)
    print("[MQTT RX] {} -> {}".format(topic_str, msg))
    if topic_str == TOPIC_ORDENES:
        validar_y_aplicar_orden(msg)


def construir_client_id():
    uid = ubinascii.hexlify(machine.unique_id()).decode("utf-8")
    return "aquaweb-{}-{}-{}".format(GRUPO, DEVICE_ID, uid[-6:])


def conectar_wifi(wlan, timeout_ms=8000):
    if not wlan.active():
        wlan.active(True)
    if wlan.isconnected():
        return True
    print("[WIFI] Conectando a '{}'...".format(WIFI_SSID))
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    inicio = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), inicio) >= timeout_ms:
            print("[WIFI ERROR] Tiempo agotado.")
            return False
        led_conexion.value(1 - led_conexion.value())
        time.sleep_ms(150)
    print("[WIFI OK] IP:", wlan.ifconfig()[0])
    return True


def conectar_mqtt(client_id):
    client = MQTTClient(
        client_id=client_id,
        server=MQTT_BROKER,
        port=MQTT_PORT,
        keepalive=MQTT_KEEPALIVE,
    )
    client.set_callback(on_mqtt_message)
    client.set_last_will(TOPIC_ESTADO, b"OFFLINE", retain=True, qos=1)
    client.connect(clean_session=True)
    client.subscribe(TOPIC_ORDENES, qos=1)
    client.publish(TOPIC_ESTADO, b"ONLINE", retain=True, qos=1)
    print("[MQTT OK] ONLINE retenido (QoS 1) en {}".format(TOPIC_ESTADO))
    return client


def capturar_lecturas(ultima_temp):
    ph = leer_ph()
    ec_ppm, tds_ppm, salinidad_ppm = leer_conductividad_y_derivados()
    temp, dht_ok = leer_temperatura(ultima_temp)
    if dht_ok:
        ultima_temp = temp
    lecturas = {
        "device_id": DEVICE_ID,
        "ph": ph,
        "temperatura_c": temp,
        "tds_ppm": tds_ppm,
        "ec_ppm": ec_ppm,
        "salinidad_ppm": salinidad_ppm,
    }
    return lecturas, ultima_temp


def publicar_telemetria(client, lecturas):
    payload = {
        "device_id": DEVICE_ID,
        "ph": lecturas["ph"],
        "temperatura_c": lecturas["temperatura_c"],
        "tds_ppm": lecturas["tds_ppm"],
        "ec_ppm": lecturas["ec_ppm"],
        "salinidad_ppm": lecturas["salinidad_ppm"],
        "actuador_estado": estado_sistema["actuador_estado"],
        "modo_operacion": estado_sistema["modo_operacion"],
        "uptime_ms": time.ticks_ms(),
    }
    trama = json.dumps(payload)
    client.publish(TOPIC_TELEMETRIA, trama.encode("utf-8"), retain=False, qos=1)
    print("[TELEMETRIA TX] {}".format(trama))


def main():
    global mqtt_cliente_activo
    print("==================================================================")
    print("  AquaWeb IoT — Plataforma Full-Stack (ESP32 MicroPython v1.20+)")
    print("  Broker: {}:{} | Prefijo: {}".format(MQTT_BROKER, MQTT_PORT, TOPIC_PREFIX))
    print("==================================================================")

    wlan = network.WLAN(network.STA_IF)
    client_id = construir_client_id()
    conectado = False
    backoff_s = BACKOFF_INICIAL_S
    proximo_reintento_ms = time.ticks_ms()

    ultima_temp = 27.0
    lecturas, ultima_temp = capturar_lecturas(ultima_temp)
    actualizar_actuador(lecturas)

    ahora = time.ticks_ms()
    ultimo_pub_ms = time.ticks_add(ahora, -INTERVALO_PUB_MS)
    ultimo_muestreo_ms = ahora
    ultimo_ping_ms = ahora
    ultimo_parpadeo_ms = ahora

    while True:
        ahora = time.ticks_ms()

        if procesar_irq_boton(lecturas) and conectado and not estado_sistema["simular_silencio"]:
            try:
                publicar_telemetria(mqtt_cliente_activo, lecturas)
                ultimo_pub_ms = ahora
                ultimo_ping_ms = ahora
            except Exception as err:
                print("[MQTT ERROR] Fallo tras IRQ:", err)
                conectado = False

        if time.ticks_diff(ahora, ultimo_muestreo_ms) >= INTERVALO_MUESTREO_MS:
            ultimo_muestreo_ms = ahora
            lecturas, ultima_temp = capturar_lecturas(ultima_temp)
            actualizar_actuador(lecturas)

        if not conectado:
            if time.ticks_diff(ahora, ultimo_parpadeo_ms) >= INTERVALO_PARPADEO_MS:
                ultimo_parpadeo_ms = ahora
                led_conexion.value(1 - led_conexion.value())

            if time.ticks_diff(ahora, proximo_reintento_ms) >= 0:
                try:
                    if conectar_wifi(wlan):
                        mqtt_cliente_activo = conectar_mqtt(client_id)
                        conectado = True
                        led_conexion.value(1)
                        backoff_s = BACKOFF_INICIAL_S
                        ultimo_pub_ms = time.ticks_add(time.ticks_ms(), -INTERVALO_PUB_MS)
                        ultimo_ping_ms = time.ticks_ms()
                    else:
                        raise OSError("Wi-Fi sin enlace")
                except Exception as err:
                    conectado = False
                    led_conexion.value(0)
                    if mqtt_cliente_activo is not None:
                        try:
                            mqtt_cliente_activo.sock.close()
                        except Exception:
                            pass
                        mqtt_cliente_activo = None
                    print("[OFFLINE] {} | Operación autónoma; reintento en {} s".format(err, backoff_s))
                    proximo_reintento_ms = time.ticks_add(time.ticks_ms(), backoff_s * 1000)
                    backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
        else:
            if not wlan.isconnected():
                print("[WIFI CAIDO] Pasando a control local autónomo.")
                conectado = False
                led_conexion.value(0)
                mqtt_cliente_activo = None
                proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
                continue

            led_conexion.value(1)
            try:
                mqtt_cliente_activo.check_msg()
            except Exception as err:
                print("[MQTT ERROR] Desconexión:", err)
                conectado = False
                led_conexion.value(0)
                mqtt_cliente_activo = None
                proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)
                continue

            if estado_sistema["simular_silencio"]:
                if time.ticks_diff(ahora, ultimo_ping_ms) >= INTERVALO_PING_MS:
                    try:
                        mqtt_cliente_activo.ping()
                        ultimo_ping_ms = ahora
                        print("[SILENCIO] PINGREQ enviado sin telemetría.")
                    except Exception:
                        conectado = False
            elif time.ticks_diff(ahora, ultimo_pub_ms) >= INTERVALO_PUB_MS:
                ultimo_pub_ms = ahora
                lecturas, ultima_temp = capturar_lecturas(ultima_temp)
                actualizar_actuador(lecturas)
                try:
                    publicar_telemetria(mqtt_cliente_activo, lecturas)
                    ultimo_ping_ms = ahora
                except Exception as err:
                    print("[MQTT ERROR] Fallo al publicar:", err)
                    conectado = False
                    led_conexion.value(0)
                    mqtt_cliente_activo = None
                    proximo_reintento_ms = time.ticks_add(ahora, backoff_s * 1000)
                    backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)

        time.sleep_ms(50)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        led_actuador.value(0)
        led_conexion.value(0)
        print("\n[INFO] Detenido manualmente.")
