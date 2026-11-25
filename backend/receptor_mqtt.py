#!/usr/bin/env python3
"""Receptor MQTT de telemetría para AquaWeb IoT (Avance 3).

Se suscribe mediante comodines a utp/ds8/grupo/aquaweb/# utilizando
paho-mqtt >= 2.0 (CallbackAPIVersion.VERSION2), valida estrictamente cada
mensaje recibido en .../telemetria y persiste las lecturas válidas en
backend/data/telemetria_valida.csv sin detenerse ante tramas corruptas.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import paho.mqtt.client as mqtt

try:
    from backend import config
except ImportError:
    import config


def obtener_fecha_hora() -> str:
    """Retorna marca de tiempo local legible en formato ISO-8601."""
    return datetime.now().isoformat(timespec="seconds")


def validar_telemetria(payload_bytes: bytes) -> tuple[bool, dict[str, Any] | None, str]:
    """Valida JSON, campos obligatorios, tipos estrictos y rangos físicos.

    Retorna (es_valido, datos_normalizados, motivo_error).
    """
    try:
        texto = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
        return False, None, f"Error de decodificación UTF-8: {err}"

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as err:
        return False, None, f"JSON corrupto o malformado: {err}"

    if not isinstance(datos, dict):
        return False, None, f"Se esperaba objeto JSON (dict), se recibió {type(datos).__name__}."

    campos_obligatorios = ("ph", "temperatura", "actuador", "modo")
    faltantes = [c for c in campos_obligatorios if c not in datos]
    if faltantes:
        return False, None, f"Faltan campos obligatorios: {', '.join(faltantes)}."

    ph = datos["ph"]
    temperatura = datos["temperatura"]
    actuador = datos["actuador"]
    modo = datos["modo"]

    if isinstance(ph, bool) or not isinstance(ph, (int, float)) or not math.isfinite(float(ph)):
        return False, None, f"Tipo inválido para 'ph': {ph!r}."
    ph_val = round(float(ph), 2)
    if not (config.PH_MIN <= ph_val <= config.PH_MAX):
        return False, None, f"'ph' fuera de rango [{config.PH_MIN}, {config.PH_MAX}]: {ph_val}."

    if (
        isinstance(temperatura, bool)
        or not isinstance(temperatura, (int, float))
        or not math.isfinite(float(temperatura))
    ):
        return False, None, f"Tipo inválido para 'temperatura': {temperatura!r}."
    temp_val = round(float(temperatura), 2)
    if not (config.TEMP_MIN <= temp_val <= config.TEMP_MAX):
        return (
            False,
            None,
            f"'temperatura' fuera de rango [{config.TEMP_MIN}, {config.TEMP_MAX}]: {temp_val}.",
        )

    if isinstance(actuador, bool) or not isinstance(actuador, int) or actuador not in config.ACTUADOR_VALIDOS:
        return False, None, f"'actuador' debe ser 0 o 1 (entero), recibido: {actuador!r}."

    if not isinstance(modo, str) or modo not in config.MODOS_VALIDOS:
        return False, None, f"'modo' inválido (esperado {config.MODOS_VALIDOS}), recibido: {modo!r}."

    return (
        True,
        {
            "ph": ph_val,
            "temperatura": temp_val,
            "actuador": actuador,
            "modo": modo,
        },
        "",
    )


def inicializar_csv(ruta_csv: Path, headers: list[str]) -> None:
    """Crea la carpeta data y escribe el encabezado CSV si el archivo no existe."""
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    if not ruta_csv.exists() or ruta_csv.stat().st_size == 0:
        with ruta_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)


def registrar_telemetria_csv(ruta_csv: Path, fecha_hora: str, datos: dict[str, Any]) -> None:
    """Anexa una lectura validada al archivo telemetria_valida.csv."""
    inicializar_csv(ruta_csv, config.TELEMETRIA_HEADERS)
    with ruta_csv.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            fecha_hora,
            f"{datos['ph']:.2f}",
            f"{datos['temperatura']:.2f}",
            datos["actuador"],
            datos["modo"],
        ])
        f.flush()


class ReceptorMQTT:
    """Encapsula el cliente paho-mqtt v2 para recepción y persistencia."""

    def __init__(self, broker: str, port: int, ruta_csv: Path) -> None:
        self.broker = broker
        self.port = port
        self.ruta_csv = ruta_csv
        self.mensajes_validos = 0
        self.mensajes_descartados = 0

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"aquaweb-receptor-{config.GRUPO}-{int(time.time()) % 10000}",
        )
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if not reason_code.is_failure:
            print(f"[CONECTADO] Broker {self.broker}:{self.port} | Suscrito a '{config.TOPIC_WILDCARD}'")
            client.subscribe(config.TOPIC_WILDCARD, qos=0)
        else:
            print(f"[ERROR CONEXION] Código de rechazo: {reason_code}")

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        print(f"[DESCONECTADO] Sesión finalizada (motivo: {reason_code}).")

    def on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        fecha_hora = obtener_fecha_hora()
        if msg.topic == config.TOPIC_TELEMETRIA:
            es_valido, datos, motivo = validar_telemetria(msg.payload)
            if not es_valido or datos is None:
                self.mensajes_descartados += 1
                crudo = msg.payload.decode("utf-8", errors="replace")
                print(
                    f"[{fecha_hora}] [ADVERTENCIA - DESCARTADO #{self.mensajes_descartados}] "
                    f"{motivo} | Payload: {crudo!r}",
                    flush=True,
                )
                return

            registrar_telemetria_csv(self.ruta_csv, fecha_hora, datos)
            self.mensajes_validos += 1
            print(
                f"[{fecha_hora}] [TELEMETRIA OK #{self.mensajes_validos}] "
                f"pH={datos['ph']:.2f} | Temp={datos['temperatura']:.2f} °C | "
                f"Actuador={datos['actuador']} | Modo={datos['modo']}",
                flush=True,
            )
        elif msg.topic == config.TOPIC_ESTADO:
            estado = msg.payload.decode("utf-8", errors="replace").strip()
            if estado:
                ret = " (retenido)" if msg.retain else ""
                print(f"[{fecha_hora}] [ESTADO NODO{ret}] {estado}", flush=True)
        elif msg.topic == config.TOPIC_ORDENES:
            orden = msg.payload.decode("utf-8", errors="replace")
            print(f"[{fecha_hora}] [ORDEN ENVIADA] {orden}", flush=True)
        else:
            print(f"[{fecha_hora}] [OTRO TEMA] {msg.topic} -> {msg.payload!r}", flush=True)

    def ejecutar(self, duracion_seg: float = 0.0) -> int:
        """Inicia la recepción continua o por duración limitada."""
        inicializar_csv(self.ruta_csv, config.TELEMETRIA_HEADERS)
        print("=== AquaWeb IoT | Receptor MQTT (paho-mqtt v2) ===", flush=True)
        print(f"Broker : {self.broker}:{self.port}", flush=True)
        print(f"Grupo  : {config.GRUPO} | Wildcard: {config.TOPIC_WILDCARD}", flush=True)
        print(f"CSV    : {self.ruta_csv}", flush=True)
        print("-" * 74, flush=True)

        self.client.connect(self.broker, self.port, keepalive=config.KEEPALIVE_SEG)
        self.client.loop_start()
        inicio = time.monotonic()
        try:
            while True:
                if duracion_seg > 0 and (time.monotonic() - inicio) >= duracion_seg:
                    break
                time.sleep(0.25)
        except KeyboardInterrupt:
            print("\n[INFO] Receptor detenido por usuario (Ctrl+C).", flush=True)
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            print(
                f"[RESUMEN RECEPTOR] Validos={self.mensajes_validos} | "
                f"Descartados={self.mensajes_descartados}",
                flush=True,
            )
        return 0


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Receptor MQTT de telemetría para AquaWeb IoT (Avance 3)."
    )
    parser.add_argument("--broker", default=config.BROKER_HOST, help="Hostname del broker MQTT.")
    parser.add_argument("--port", type=int, default=config.BROKER_PORT, help="Puerto TCP del broker.")
    parser.add_argument(
        "--duracion",
        type=float,
        default=0.0,
        help="Segundos de ejecución (0 para ejecución continua hasta Ctrl+C).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_argumentos(argv)
    receptor = ReceptorMQTT(args.broker, args.port, config.TELEMETRIA_CSV)
    return receptor.ejecutar(duracion_seg=args.duracion)


if __name__ == "__main__":
    sys.exit(main())
