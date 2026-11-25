#!/usr/bin/env python3
"""Monitor de estado de comunicación MQTT para AquaWeb IoT (Avance 3).

Script independiente que usa paho-mqtt >= 2.0 (CallbackAPIVersion.VERSION2)
con loop_start() y evaluación periódica no bloqueante cada 1 segundo.
Distingue exactamente tres estados: ONLINE, SIN_DATOS y OFFLINE, y persiste
únicamente las transiciones de estado en backend/data/eventos_comunicacion.csv.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

try:
    from backend import config
except ImportError:
    import config


GRAVEDAD_POR_ESTADO = {
    "ONLINE": "INFO",
    "SIN_DATOS": "ADVERTENCIA",
    "OFFLINE": "CRITICO",
}


def obtener_fecha_hora() -> str:
    """Retorna la marca de tiempo local en formato ISO-8601."""
    return datetime.now().isoformat(timespec="seconds")


def inicializar_eventos_csv(ruta_csv: Path) -> None:
    """Crea el directorio data y el encabezado de eventos_comunicacion.csv si falta."""
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    if not ruta_csv.exists() or ruta_csv.stat().st_size == 0:
        with ruta_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(config.EVENTOS_HEADERS)


def registrar_evento_csv(
    ruta_csv: Path,
    fecha: str,
    tipo: str,
    gravedad: str,
    detalle: str,
) -> None:
    """Escribe una fila de transición de estado en eventos_comunicacion.csv."""
    inicializar_eventos_csv(ruta_csv)
    with ruta_csv.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([fecha, tipo, gravedad, detalle])
        f.flush()


class MonitorEstadoComunicacion:
    """Máquina de estados ONLINE / SIN_DATOS / OFFLINE con evaluación no bloqueante."""

    def __init__(
        self,
        broker: str,
        port: int,
        silencio_max_seg: float,
        ruta_csv: Path,
    ) -> None:
        self.broker = broker
        self.port = port
        self.silencio_max_seg = silencio_max_seg
        self.ruta_csv = ruta_csv

        self._lock = threading.Lock()
        self.estado_actual: str | None = None
        self.ultimo_dato_ts: float | None = None
        self.transiciones_registradas = 0

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"aquaweb-monitor-{config.GRUPO}-{int(time.time()) % 10000}",
        )
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)

    def _cambiar_estado(self, nuevo_estado: str, detalle: str) -> None:
        """Transiciona y registra en CSV únicamente si el estado cambió."""
        if nuevo_estado not in GRAVEDAD_POR_ESTADO:
            return
        if self.estado_actual == nuevo_estado:
            return

        estado_anterior = self.estado_actual or "INICIAL"
        self.estado_actual = nuevo_estado
        gravedad = GRAVEDAD_POR_ESTADO[nuevo_estado]
        fecha = obtener_fecha_hora()

        registrar_evento_csv(self.ruta_csv, fecha, nuevo_estado, gravedad, detalle)
        self.transiciones_registradas += 1
        print(
            f"[{fecha}] [CAMBIO DE ESTADO #{self.transiciones_registradas}] "
            f"{estado_anterior} -> {nuevo_estado} ({gravedad}) | {detalle}",
            flush=True,
        )

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if not reason_code.is_failure:
            print(
                f"[CONECTADO] Monitor escuchando '{config.TOPIC_ESTADO}' y "
                f"'{config.TOPIC_TELEMETRIA}' en {self.broker}:{self.port}",
                flush=True,
            )
            client.subscribe([(config.TOPIC_ESTADO, 1), (config.TOPIC_TELEMETRIA, 0)])
        else:
            print(f"[ERROR CONEXION] Código: {reason_code}", flush=True)

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        print(f"[DESCONECTADO] Monitor desconectado del broker ({reason_code}).", flush=True)

    def on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        ahora_mono = time.monotonic()
        with self._lock:
            if msg.topic == config.TOPIC_ESTADO:
                payload = msg.payload.decode("utf-8", errors="replace").strip().upper()
                if not payload:
                    return
                if payload == "ONLINE":
                    self.ultimo_dato_ts = ahora_mono
                    origen = "retenido" if msg.retain else "en vivo"
                    self._cambiar_estado(
                        "ONLINE",
                        f"Dispositivo reportó ONLINE ({origen}) en {config.TOPIC_ESTADO}.",
                    )
                elif payload == "OFFLINE":
                    self.ultimo_dato_ts = None
                    origen = "LWT / desconexión" if not msg.retain else "estado OFFLINE/LWT"
                    self._cambiar_estado(
                        "OFFLINE",
                        f"Dispositivo desconectado ({origen}) en {config.TOPIC_ESTADO}.",
                    )

            elif msg.topic == config.TOPIC_TELEMETRIA:
                self.ultimo_dato_ts = ahora_mono
                if self.estado_actual == "SIN_DATOS":
                    self._cambiar_estado(
                        "ONLINE",
                        "Telemetría reanudada tras periodo de silencio.",
                    )
                elif self.estado_actual in (None, "OFFLINE"):
                    self._cambiar_estado(
                        "ONLINE",
                        "Telemetría activa recibida desde el dispositivo.",
                    )

    def evaluar_silencio(self) -> None:
        """Verifica periódicamente si un dispositivo ONLINE superó SILENCIO_MAX_SEG."""
        ahora_mono = time.monotonic()
        with self._lock:
            if self.estado_actual == "ONLINE" and self.ultimo_dato_ts is not None:
                silencio = ahora_mono - self.ultimo_dato_ts
                if silencio >= self.silencio_max_seg:
                    self._cambiar_estado(
                        "SIN_DATOS",
                        f"Sin telemetría durante {silencio:.1f} s "
                        f"(umbral máximo: {self.silencio_max_seg:.0f} s).",
                    )

    def ejecutar(self, duracion_seg: float = 0.0) -> int:
        """Inicia loop_start() y ejecuta evaluación no bloqueante cada 1 segundo."""
        inicializar_eventos_csv(self.ruta_csv)
        print("=== AquaWeb IoT | Monitor de Estado de Comunicación ===", flush=True)
        print(f"Broker      : {self.broker}:{self.port}", flush=True)
        print(f"Silencio max: {self.silencio_max_seg:.0f} s (evaluación cada {config.EVALUACION_MONITOR_SEG:.1f} s)", flush=True)
        print(f"CSV eventos : {self.ruta_csv}", flush=True)
        print("-" * 74, flush=True)

        self.client.connect(self.broker, self.port, keepalive=config.KEEPALIVE_SEG)
        self.client.loop_start()
        inicio = time.monotonic()
        proxima_eval = inicio + config.EVALUACION_MONITOR_SEG

        try:
            while True:
                ahora = time.monotonic()
                if duracion_seg > 0 and (ahora - inicio) >= duracion_seg:
                    break

                if ahora >= proxima_eval:
                    self.evaluar_silencio()
                    proxima_eval += config.EVALUACION_MONITOR_SEG

                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n[INFO] Monitor detenido por usuario (Ctrl+C).", flush=True)
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            print(
                f"[RESUMEN MONITOR] Estado final={self.estado_actual or 'SIN_EVENTOS'} | "
                f"Transiciones registradas={self.transiciones_registradas}",
                flush=True,
            )
        return 0


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor independiente de estado MQTT para AquaWeb IoT (Avance 3)."
    )
    parser.add_argument("--broker", default=config.BROKER_HOST, help="Hostname del broker MQTT.")
    parser.add_argument("--port", type=int, default=config.BROKER_PORT, help="Puerto TCP del broker.")
    parser.add_argument(
        "--silencio-max",
        type=float,
        default=float(config.SILENCIO_MAX_SEG),
        help=f"Segundos sin telemetría para declarar SIN_DATOS (por defecto {config.SILENCIO_MAX_SEG}).",
    )
    parser.add_argument(
        "--duracion",
        type=float,
        default=0.0,
        help="Segundos de ejecución (0 para ejecución continua hasta Ctrl+C).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_argumentos(argv)
    monitor = MonitorEstadoComunicacion(
        broker=args.broker,
        port=args.port,
        silencio_max_seg=args.silencio_max,
        ruta_csv=config.EVENTOS_CSV,
    )
    return monitor.ejecutar(duracion_seg=args.duracion)


if __name__ == "__main__":
    sys.exit(main())
