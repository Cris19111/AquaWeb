#!/usr/bin/env python3
"""Utilidad CLI de pruebas y simulación de escenarios MQTT para AquaWeb IoT (Avance 3).

Permite disparar desde terminal los escenarios de prueba requeridos para validación
y defensa en vivo contra el broker MQTT configurado en config.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import paho.mqtt.client as mqtt

try:
    from backend import config
except ImportError:
    import config


def crear_cliente_publicador(broker: str, port: int) -> mqtt.Client:
    """Conecta un cliente paho-mqtt v2 temporal para publicar escenarios de prueba."""
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"aquaweb-sim-{config.GRUPO}-{int(time.time()) % 10000}",
    )
    client.connect(broker, port, keepalive=config.KEEPALIVE_SEG)
    client.loop_start()
    return client


def publicar(
    client: mqtt.Client,
    topic: str,
    payload: str | bytes,
    retain: bool = False,
    qos: int = 1,
) -> None:
    """Publica un mensaje esperando confirmación del broker."""
    info = client.publish(topic, payload, qos=qos, retain=retain)
    info.wait_for_publish(timeout=5.0)
    texto = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    print(f"[TX] {topic} (retain={retain}, qos={qos}) -> {texto}", flush=True)


def escenario_normal(client: mqtt.Client, muestras: int = 3, espera: float = 2.0) -> None:
    """Simula dispositivo ONLINE enviando telemetría válida."""
    publicar(client, config.TOPIC_ESTADO, "ONLINE", retain=True, qos=1)
    tramas = [
        {"ph": 7.85, "temperatura": 26.4, "actuador": 0, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5},
        {"ph": 8.12, "temperatura": 27.1, "actuador": 0, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5},
        {"ph": 6.20, "temperatura": 28.0, "actuador": 1, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5},
    ]
    for i in range(muestras):
        payload = json.dumps(tramas[i % len(tramas)])
        publicar(client, config.TOPIC_TELEMETRIA, payload, retain=False, qos=0)
        if i < muestras - 1:
            time.sleep(espera)


def escenario_orden_valida(client: mqtt.Client) -> None:
    """Envía órdenes JSON válidas al tema .../ordenes."""
    ordenes = [
        {"modo": "MANUAL", "actuador": 1},
        {"umbral_ph_min": 7.0, "umbral_ph_max": 8.5},
        {"modo": "AUTO"},
    ]
    for orden in ordenes:
        publicar(client, config.TOPIC_ORDENES, json.dumps(orden), retain=False, qos=1)
        time.sleep(0.5)


def escenario_orden_invalida(client: mqtt.Client) -> None:
    """Envía órdenes inválidas/corruptas al tema .../ordenes."""
    ordenes_malas = [
        "{modo: MANUAL_CORRUPTO",
        json.dumps({"modo": "TURBO"}),
        json.dumps({"modo": "MANUAL", "actuador": 9}),
        json.dumps({"umbral_ph_min": 10.5, "umbral_ph_max": 6.0}),
    ]
    for payload in ordenes_malas:
        publicar(client, config.TOPIC_ORDENES, payload, retain=False, qos=1)
        time.sleep(0.5)


def escenario_dato_invalido(client: mqtt.Client) -> None:
    """Envía tramas de telemetría inválidas al tema .../telemetria."""
    tramas_malas = [
        "{ph: 7.5, temperatura: 26.0",
        json.dumps({"ph": 7.5, "temperatura": 26.0}),
        json.dumps({"ph": 19.5, "temperatura": 26.0, "actuador": 0, "modo": "AUTO"}),
        json.dumps({"ph": 7.4, "temperatura": 95.0, "actuador": 0, "modo": "AUTO"}),
        json.dumps({"ph": "alto", "temperatura": 26.0, "actuador": True, "modo": "AUTO"}),
    ]
    for payload in tramas_malas:
        publicar(client, config.TOPIC_TELEMETRIA, payload, retain=False, qos=0)
        time.sleep(0.5)


def escenario_silencio(client: mqtt.Client, activar: bool) -> None:
    """Envía la orden simular_silencio al nodo Wokwi."""
    publicar(
        client,
        config.TOPIC_ORDENES,
        json.dumps({"simular_silencio": activar}),
        retain=False,
        qos=1,
    )


def escenario_suite_completa(client: mqtt.Client, espera_silencio: float) -> None:
    """Ejecuta secuencia completa: ONLINE -> inválidos -> SIN_DATOS -> ONLINE -> OFFLINE."""
    print("\n--- [1/6] Estado ONLINE + Telemetria valida ---", flush=True)
    escenario_normal(client, muestras=3, espera=1.5)

    print("\n--- [2/6] Envio de ordenes validas e invalidas ---", flush=True)
    escenario_orden_valida(client)
    escenario_orden_invalida(client)

    print("\n--- [3/6] Envio de telemetria corrupta / fuera de rango ---", flush=True)
    escenario_dato_invalido(client)

    print(f"\n--- [4/6] Esperando {espera_silencio:.0f} s sin telemetria (provocar SIN_DATOS) ---", flush=True)
    time.sleep(espera_silencio)

    print("\n--- [5/6] Reanudando telemetria valida (SIN_DATOS -> ONLINE) ---", flush=True)
    publicar(
        client,
        config.TOPIC_TELEMETRIA,
        json.dumps({"ph": 7.65, "temperatura": 26.8, "actuador": 0, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5}),
        retain=False,
        qos=0,
    )
    time.sleep(2.0)

    print("\n--- [6/6] Simulando desconexion abrupta / LWT (OFFLINE) ---", flush=True)
    publicar(client, config.TOPIC_ESTADO, "OFFLINE", retain=True, qos=1)
    time.sleep(1.0)
    print("\n[SUITE COMPLETADA]", flush=True)


def menu_interactivo(client: mqtt.Client) -> None:
    """Menú interactivo en consola para demostración y defensa en vivo."""
    acciones = {
        "1": ("Publicar telemetría normal (ONLINE + 3 lecturas)", lambda: escenario_normal(client)),
        "2": ("Enviar orden válida", lambda: escenario_orden_valida(client)),
        "3": ("Enviar orden inválida", lambda: escenario_orden_invalida(client)),
        "4": ("Enviar dato de telemetría corrupto / fuera de rango", lambda: escenario_dato_invalido(client)),
        "5": ("Activar simulación de silencio en Wokwi", lambda: escenario_silencio(client, True)),
        "6": ("Desactivar simulación de silencio en Wokwi", lambda: escenario_silencio(client, False)),
        "7": ("Publicar estado OFFLINE (simular LWT)", lambda: publicar(client, config.TOPIC_ESTADO, "OFFLINE", retain=True, qos=1)),
        "8": ("Publicar estado ONLINE", lambda: publicar(client, config.TOPIC_ESTADO, "ONLINE", retain=True, qos=1)),
        "9": ("Ejecutar suite completa automatizada", lambda: escenario_suite_completa(client, config.SILENCIO_MAX_SEG + 3)),
    }
    while True:
        print("\n=== AquaWeb IoT | Simulador de Pruebas MQTT ===")
        print(f"Broker: {config.BROKER_HOST}:{config.BROKER_PORT} | Grupo: {config.GRUPO}")
        for k, (desc, _) in acciones.items():
            print(f"  {k}. {desc}")
        print("  0. Salir")
        opcion = input("Seleccione una opción: ").strip()
        if opcion == "0":
            break
        if opcion in acciones:
            acciones[opcion][1]()
        else:
            print("Opción no válida.")


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador CLI de escenarios de prueba MQTT para AquaWeb IoT."
    )
    parser.add_argument("--broker", default=config.BROKER_HOST, help="Hostname del broker MQTT.")
    parser.add_argument("--port", type=int, default=config.BROKER_PORT, help="Puerto TCP del broker.")
    parser.add_argument(
        "--escenario",
        choices=[
            "normal",
            "orden-valida",
            "orden-invalida",
            "dato-invalido",
            "silencio-on",
            "silencio-off",
            "online",
            "offline",
            "limpiar-estado",
            "suite-completa",
        ],
        help="Escenario directo a ejecutar sin menú interactivo.",
    )
    parser.add_argument(
        "--espera-silencio",
        type=float,
        default=float(config.SILENCIO_MAX_SEG + 3),
        help=f"Segundos de espera en suite-completa para disparar SIN_DATOS (defecto {config.SILENCIO_MAX_SEG + 3}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_argumentos(argv)
    client = crear_cliente_publicador(args.broker, args.port)
    try:
        if args.escenario is None:
            menu_interactivo(client)
        elif args.escenario == "normal":
            escenario_normal(client)
        elif args.escenario == "orden-valida":
            escenario_orden_valida(client)
        elif args.escenario == "orden-invalida":
            escenario_orden_invalida(client)
        elif args.escenario == "dato-invalido":
            escenario_dato_invalido(client)
        elif args.escenario == "silencio-on":
            escenario_silencio(client, True)
        elif args.escenario == "silencio-off":
            escenario_silencio(client, False)
        elif args.escenario == "online":
            publicar(client, config.TOPIC_ESTADO, "ONLINE", retain=True, qos=1)
        elif args.escenario == "offline":
            publicar(client, config.TOPIC_ESTADO, "OFFLINE", retain=True, qos=1)
        elif args.escenario == "limpiar-estado":
            publicar(client, config.TOPIC_ESTADO, b"", retain=True, qos=1)
        elif args.escenario == "suite-completa":
            escenario_suite_completa(client, args.espera_silencio)
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
