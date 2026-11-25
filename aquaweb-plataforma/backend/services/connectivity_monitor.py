"""Monitor de conectividad (ONLINE / SIN_DATOS / OFFLINE) y expiración de órdenes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.models import Dispositivo, EventoComunicacion, OrdenControl, utcnow
from backend.services.telemetry_processor import ensure_default_entities
from backend.services.ws_manager import LiveWebSocketManager

logger = logging.getLogger("aquaweb.connectivity")

SEVERITY_BY_STATE = {
    "ONLINE": "INFO",
    "SIN_DATOS": "WARNING",
    "OFFLINE": "CRITICAL",
}


class ConnectivityMonitor:
    """Supervisa transiciones de estado del ESP32 y timeouts de órdenes remotas."""

    def __init__(
        self,
        session_factory: sessionmaker,
        ws: LiveWebSocketManager | None = None,
        silence_multiplier: int | None = None,
        command_timeout_seg: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.ws = ws
        self.silence_multiplier = silence_multiplier or settings.silence_multiplier
        self.command_timeout_seg = command_timeout_seg or settings.command_timeout_seg

    def transition_device_state(
        self,
        db: Session,
        device: Dispositivo,
        nuevo_estado: str,
        detalle: str,
        now: datetime | None = None,
    ) -> EventoComunicacion | None:
        """Registra en eventos_comunicacion ÚNICAMENTE cuando hay cambio de estado."""
        if nuevo_estado not in SEVERITY_BY_STATE:
            return None
        if device.estado_conexion == nuevo_estado:
            return None

        ts = now or utcnow()
        estado_anterior = device.estado_conexion
        device.estado_conexion = nuevo_estado
        if nuevo_estado == "ONLINE":
            device.ultimo_latido = ts

        evt = EventoComunicacion(
            dispositivo_id=device.id,
            estado_anterior=estado_anterior,
            estado_nuevo=nuevo_estado,
            gravedad=SEVERITY_BY_STATE[nuevo_estado],
            detalle=detalle,
            registrado_en=ts,
        )
        db.add(evt)
        db.flush()

        if self.ws is not None:
            self.ws.broadcast_threadsafe(
                {
                    "event": "connectivity",
                    "device_id": device.client_id_mqtt,
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": nuevo_estado,
                    "gravedad": evt.gravedad,
                    "detalle": detalle,
                    "registrado_en": ts.isoformat(),
                }
            )
        return evt

    def handle_status_message(
        self,
        device_id_mqtt: str,
        payload_bytes: bytes,
        retain: bool = False,
        now: datetime | None = None,
    ) -> str | None:
        """Procesa mensajes del tema .../estado (ONLINE al conectar / OFFLINE vía LWT)."""
        estado = payload_bytes.decode("utf-8", errors="replace").strip().upper()
        if estado not in ("ONLINE", "OFFLINE"):
            return None

        ts = now or utcnow()
        try:
            with self.session_factory() as db:
                device = ensure_default_entities(db, device_id_mqtt)
                if estado == "ONLINE":
                    device.ultimo_latido = ts
                    detalle = (
                        "Estado ONLINE recibido (mensaje retenido)."
                        if retain
                        else "Nodo ESP32 conectado y publicado como ONLINE."
                    )
                else:
                    detalle = "Desconexión abrupta detectada vía Last Will (LWT OFFLINE)."
                self.transition_device_state(db, device, estado, detalle, now=ts)
                db.commit()
                return estado
        except SQLAlchemyError as err:
            logger.error("Error registrando estado %s en PostgreSQL: %s", estado, err)
            return None

    def handle_command_ack(self, payload_bytes: bytes, now: datetime | None = None) -> bool:
        """Procesa confirmaciones de .../ordenes_ack (APLICADA / RECHAZADA)."""
        import json
        from backend.schemas import CommandAckIn

        try:
            ack = CommandAckIn.model_validate(json.loads(payload_bytes.decode("utf-8")))
        except Exception as err:
            logger.warning("ACK de orden inválido: %s", err)
            return False

        ts = now or utcnow()
        try:
            with self.session_factory() as db:
                orden = db.scalar(select(OrdenControl).where(OrdenControl.command_id == ack.command_id))
                if orden is None:
                    return False
                orden.estado = ack.estado
                orden.detalle_respuesta = ack.detalle
                orden.actualizada_en = ts
                if ack.estado == "APLICADA":
                    device = db.get(Dispositivo, orden.dispositivo_id)
                    if device is not None:
                        if "modo" in orden.payload_json:
                            device.modo_operacion = orden.payload_json["modo"]
                        if "actuador" in orden.payload_json:
                            device.actuador_activo = bool(orden.payload_json["actuador"])
                db.commit()
                if self.ws is not None:
                    self.ws.broadcast_threadsafe(
                        {
                            "event": "command_ack",
                            "command_id": ack.command_id,
                            "estado": ack.estado,
                            "detalle": ack.detalle,
                            "actualizada_en": ts.isoformat(),
                        }
                    )
                return True
        except SQLAlchemyError as err:
            logger.error("Error actualizando ACK de orden: %s", err)
            return False

    def evaluate_cycle(self, now: datetime | None = None) -> dict[str, int]:
        """Evalúa silencio (ONLINE -> SIN_DATOS) y órdenes vencidas (ENVIADA -> EXPIRADA)."""
        ts = now or utcnow()
        marked_silent = 0
        expired_cmds = 0

        try:
            with self.session_factory() as db:
                devices = list(db.scalars(select(Dispositivo)))
                for dev in devices:
                    if dev.estado_conexion == "ONLINE" and dev.ultimo_latido is not None:
                        latido = dev.ultimo_latido
                        if latido.tzinfo is None:
                            latido = latido.replace(tzinfo=timezone.utc)
                        umbral_seg = self.silence_multiplier * dev.intervalo_pub_seg
                        elapsed = (ts - latido).total_seconds()
                        if elapsed >= umbral_seg:
                            evt = self.transition_device_state(
                                db,
                                dev,
                                "SIN_DATOS",
                                f"Sin telemetría durante {elapsed:.1f} s (umbral {umbral_seg} s).",
                                now=ts,
                            )
                            if evt is not None:
                                marked_silent += 1

                cutoff = ts - timedelta(seconds=self.command_timeout_seg)
                pending_orders = list(
                    db.scalars(select(OrdenControl).where(OrdenControl.estado == "ENVIADA"))
                )
                for orden in pending_orders:
                    creada = orden.creada_en
                    if creada.tzinfo is None:
                        creada = creada.replace(tzinfo=timezone.utc)
                    if creada <= cutoff:
                        orden.estado = "EXPIRADA"
                        orden.detalle_respuesta = (
                            f"Sin confirmación en .../ordenes_ack tras {self.command_timeout_seg} s."
                        )
                        orden.actualizada_en = ts
                        expired_cmds += 1

                db.commit()
        except SQLAlchemyError as err:
            logger.error("Error en ciclo del monitor de conectividad: %s", err)

        return {"marked_silent": marked_silent, "expired_commands": expired_cmds}
