"""Worker MQTT con paho-mqtt >= 2.1.0 (CallbackAPIVersion.VERSION2) y reconexión automática."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from backend.config import settings
from backend.services.connectivity_monitor import ConnectivityMonitor
from backend.services.telemetry_processor import TelemetryProcessor

logger = logging.getLogger("aquaweb.mqtt")


class AquaWebMQTTWorker:
    """Consume telemetría, estado LWT y ACKs del ESP32, y publica órdenes remotas."""

    def __init__(
        self,
        processor: TelemetryProcessor,
        monitor: ConnectivityMonitor,
    ) -> None:
        self.processor = processor
        self.monitor = monitor
        self.connected = False
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._legacy_topic_devices: set[str] = {settings.mqtt_device_id}

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"aquaweb-backend-{settings.mqtt_grupo}-{int(time.time()) % 100000}",
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if not reason_code.is_failure:
            self.connected = True
            client.subscribe(settings.topic_all_devices, qos=1)
            logger.info(
                "MQTT conectado a %s:%s | Suscrito a '%s'",
                settings.mqtt_broker_host,
                settings.mqtt_broker_port,
                settings.topic_all_devices,
            )
        else:
            self.connected = False
            logger.error("Error de conexión MQTT: %s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self.connected = False
        logger.warning("Desconectado del broker MQTT (%s). Reconexión automática activa.", reason_code)

    def _parse_topic(self, topic: str) -> tuple[str, str, bool] | None:
        # Soporta esquema plataforma: utp/ds8/<GRUPO>/aquaweb/<DEVICE_ID>/<canal>
        # y esquema Avance 3: utp/ds8/<GRUPO>/aquaweb/<canal>
        parts = topic.split("/")
        if len(parts) >= 6 and parts[0] == "utp" and parts[3] == "aquaweb":
            return parts[4], parts[5], False
        if len(parts) == 5 and parts[0] == "utp" and parts[3] == "aquaweb":
            return settings.mqtt_device_id, parts[4], True
        return None

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        parsed = self._parse_topic(msg.topic)
        if parsed is None:
            return
        device_id, channel, is_legacy = parsed
        if is_legacy:
            self._legacy_topic_devices.add(device_id)
        try:
            if channel == "telemetria":
                self.processor.process_raw_telemetry(msg.topic, msg.payload, device_id)
            elif channel == "estado":
                self.monitor.handle_status_message(device_id, msg.payload, retain=bool(msg.retain))
            elif channel == "ordenes_ack":
                self.monitor.handle_command_ack(msg.payload)
        except Exception as err:
            logger.exception("Error inesperado procesando mensaje en %s: %s", msg.topic, err)

    def publish_command(self, device_id: str, payload: dict[str, Any]) -> bool:
        """Publica una orden remota QoS 1 en .../ordenes (plataforma y Avance 3)."""
        if not self.connected:
            return False
        topic = f"{settings.topic_prefix(device_id)}/ordenes"
        info = self.client.publish(topic, json.dumps(payload), qos=1, retain=False)
        if device_id in self._legacy_topic_devices:
            legacy_topic = f"utp/ds8/{settings.mqtt_grupo}/aquaweb/ordenes"
            legacy_payload: dict[str, Any] = {}
            if "modo" in payload:
                legacy_payload["modo"] = payload["modo"]
            if "actuador" in payload:
                legacy_payload["actuador"] = payload["actuador"]
            if "simular_silencio" in payload:
                legacy_payload["simular_silencio"] = payload["simular_silencio"]
            if payload.get("parametro") == "ph":
                legacy_payload["umbral_ph_min"] = payload["min_optimo"]
                legacy_payload["umbral_ph_max"] = payload["max_optimo"]
            if legacy_payload:
                self.client.publish(legacy_topic, json.dumps(legacy_payload), qos=1, retain=False)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.monitor.evaluate_cycle()
                self.processor.drain_buffer()
            except Exception as err:
                logger.error("Error en bucle de supervisión: %s", err)
            self._stop_event.wait(2.0)

    def start(self) -> None:
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        if not settings.mqtt_enabled:
            logger.info("MQTT_ENABLED=false; worker MQTT omitido.")
            return
        try:
            self.client.connect_async(
                settings.mqtt_broker_host,
                settings.mqtt_broker_port,
                keepalive=settings.mqtt_keepalive_seg,
            )
            self.client.loop_start()
        except Exception as err:
            logger.error("No se pudo iniciar enlace MQTT (%s); se reintentará en segundo plano.", err)

    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=3.0)
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
