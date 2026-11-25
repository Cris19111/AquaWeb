"""Procesador de telemetría: validación estricta, detección de fallos de sensor,
alertas con histéresis/cooldown y buffer local ante caídas de PostgreSQL.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import DEFAULT_THRESHOLDS, MAX_ABRUPT_JUMP, settings
from backend.models import (
    Alerta,
    Dispositivo,
    Estanque,
    EventoComunicacion,
    LecturaTelemetria,
    MensajeRechazado,
    UmbralParametro,
    utcnow,
)
from backend.schemas import TelemetryPayloadIn
from backend.services.buffer import LocalTelemetryBuffer
from backend.services.ws_manager import LiveWebSocketManager

logger = logging.getLogger("aquaweb.telemetry")

PARAM_FIELD_MAP: dict[str, str] = {
    "ph": "ph",
    "temperatura": "temperatura_c",
    "tds": "tds_ppm",
    "ec": "ec_ppm",
    "salinidad": "salinidad_ppm",
}


def ensure_default_entities(db: Session, client_id_mqtt: str) -> Dispositivo:
    """Garantiza la existencia del estanque, umbrales base y dispositivo MQTT."""
    device = db.scalar(select(Dispositivo).where(Dispositivo.client_id_mqtt == client_id_mqtt))
    if device is not None:
        return device

    estanque = db.scalar(select(Estanque).order_by(Estanque.id.asc()))
    if estanque is None:
        estanque = Estanque(
            nombre="Estanque Camaronero #1 - Aguadulce",
            ubicacion="Aguadulce, Coclé, Panamá",
            especie="Litopenaeus vannamei",
            volumen_m3=4500.0,
            activo=True,
        )
        db.add(estanque)
        db.flush()

    existing_params = {
        u.parametro
        for u in db.scalars(select(UmbralParametro).where(UmbralParametro.estanque_id == estanque.id))
    }
    for param, cfg in DEFAULT_THRESHOLDS.items():
        if param not in existing_params:
            db.add(
                UmbralParametro(
                    estanque_id=estanque.id,
                    parametro=param,
                    min_optimo=float(cfg["min_optimo"]),
                    max_optimo=float(cfg["max_optimo"]),
                    min_fisico=float(cfg["min_fisico"]),
                    max_fisico=float(cfg["max_fisico"]),
                    unidad=str(cfg["unidad"]),
                )
            )

    device = Dispositivo(
        estanque_id=estanque.id,
        client_id_mqtt=client_id_mqtt,
        nombre=f"Nodo ESP32 ({client_id_mqtt})",
        estado_conexion="OFFLINE",
        modo_operacion="AUTO",
        actuador_activo=False,
        intervalo_pub_seg=settings.default_pub_interval_seg,
    )
    db.add(device)
    db.flush()
    return device


def _reject_nan_constant(val: str) -> Any:
    raise ValueError(f"Constante JSON no permitida: {val}")


class TelemetryProcessor:
    """Procesa telemetría MQTT con validación, calidad de datos, alertas y resiliencia."""

    def __init__(
        self,
        session_factory: sessionmaker,
        buffer: LocalTelemetryBuffer,
        ws: LiveWebSocketManager | None = None,
        frozen_cycles: int | None = None,
        resolve_cycles: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.buffer = buffer
        self.ws = ws
        self.frozen_cycles = frozen_cycles or settings.frozen_sensor_cycles
        self.resolve_cycles = resolve_cycles or settings.alert_resolve_cycles

        # Historial corto en memoria por dispositivo para detectar congelamiento y saltos
        self._recent_vectors: dict[str, deque[tuple[float, float, float, float, float]]] = defaultdict(
            lambda: deque(maxlen=max(self.frozen_cycles, 5))
        )
        self._last_reading_meta: dict[str, tuple[datetime, dict[str, float]]] = {}
        # Histéresis de resolución: ciclos consecutivos en rango óptimo por (device_id, parametro)
        self._healthy_streaks: dict[tuple[int, str], int] = defaultdict(int)

    def validate_raw_payload(self, payload_bytes: bytes) -> tuple[TelemetryPayloadIn | None, str | None]:
        """Decodifica UTF-8, rechaza NaN/Infinity y valida esquema Pydantic + rangos físicos."""
        try:
            text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError as err:
            return None, f"Error de decodificación UTF-8: {err}"

        if not text.strip():
            return None, "Payload vacío."

        try:
            raw_obj = json.loads(text, parse_constant=_reject_nan_constant)
        except Exception as err:
            return None, f"JSON corrupto o con NaN/Infinity: {err}"

        if not isinstance(raw_obj, dict):
            return None, f"El payload debe ser un objeto JSON, recibido {type(raw_obj).__name__}."

        try:
            validated = TelemetryPayloadIn.model_validate(raw_obj)
            return validated, None
        except ValidationError as err:
            reasons = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in err.errors())
            return None, f"Validación de telemetría fallida: {reasons}"

    def _detect_sensor_faults(
        self,
        device_key: str,
        payload: TelemetryPayloadIn,
        now: datetime,
    ) -> tuple[str, list[tuple[str, str, float]]]:
        """Detecta sensor congelado (N ciclos idénticos) y saltos abruptos improbables."""
        faults: list[tuple[str, str, float]] = []
        vec = (
            payload.ph,
            payload.temperatura_c,
            payload.tds_ppm,
            payload.ec_ppm,
            payload.salinidad_ppm,
        )
        history = self._recent_vectors[device_key]
        history.append(vec)

        if len(history) >= self.frozen_cycles and len(set(list(history)[-self.frozen_cycles :])) == 1:
            faults.append(
                (
                    "sensor_congelado",
                    f"Valores exactamente idénticos durante {self.frozen_cycles} ciclos consecutivos "
                    f"(pH={payload.ph}, Temp={payload.temperatura_c} °C, EC={payload.ec_ppm} ppm).",
                    payload.ph,
                )
            )

        current_map = {
            "ph": payload.ph,
            "temperatura": payload.temperatura_c,
            "tds": payload.tds_ppm,
            "ec": payload.ec_ppm,
            "salinidad": payload.salinidad_ppm,
        }
        prev = self._last_reading_meta.get(device_key)
        if prev is not None:
            prev_ts, prev_vals = prev
            dt_sec = abs((now - prev_ts).total_seconds())
            if dt_sec <= 30.0:
                for param, max_delta in MAX_ABRUPT_JUMP.items():
                    delta = abs(current_map[param] - prev_vals[param])
                    if delta > max_delta:
                        faults.append(
                            (
                                f"salto_{param}",
                                f"Salto abrupto improbable en '{param}': Δ={delta:.2f} en {dt_sec:.1f} s "
                                f"(límite {max_delta:.2f}). Revisar sonda.",
                                current_map[param],
                            )
                        )

        self._last_reading_meta[device_key] = (now, current_map)
        quality = "SOSPECHOSA" if faults else "VALIDA"
        return quality, faults

    def _upsert_active_alert(
        self,
        db: Session,
        device_id: int,
        lectura_id: int,
        parametro: str,
        valor: float,
        umbral_str: str,
        severidad: str,
        mensaje: str,
    ) -> Alerta:
        """Crea alerta o actualiza la alerta activa existente (anti-ruido / sin duplicados)."""
        existing = db.scalar(
            select(Alerta)
            .where(
                Alerta.dispositivo_id == device_id,
                Alerta.parametro == parametro,
                Alerta.estado.in_(("ACTIVA", "RECONOCIDA")),
            )
            .order_by(Alerta.creada_en.desc())
        )
        if existing is not None:
            existing.lectura_id = lectura_id
            existing.valor_detectado = valor
            existing.umbral_infringido = umbral_str
            existing.severidad = severidad
            existing.mensaje = mensaje
            return existing

        alerta = Alerta(
            dispositivo_id=device_id,
            lectura_id=lectura_id,
            parametro=parametro,
            valor_detectado=valor,
            umbral_infringido=umbral_str,
            severidad=severidad,
            mensaje=mensaje,
            estado="ACTIVA",
        )
        db.add(alerta)
        return alerta

    def _evaluate_thresholds_with_hysteresis(
        self,
        db: Session,
        device: Dispositivo,
        lectura: LecturaTelemetria,
        now: datetime,
    ) -> None:
        """Evalúa umbrales óptimos con histéresis para evitar inundación de alertas."""
        umbrales = list(
            db.scalars(select(UmbralParametro).where(UmbralParametro.estanque_id == device.estanque_id))
        )
        for u in umbrales:
            field_name = PARAM_FIELD_MAP.get(u.parametro)
            if not field_name:
                continue
            val = float(getattr(lectura, field_name))
            span = max(u.max_optimo - u.min_optimo, 0.1)
            key = (device.id, u.parametro)

            if val < u.min_optimo or val > u.max_optimo:
                self._healthy_streaks[key] = 0
                desv = (u.min_optimo - val) if val < u.min_optimo else (val - u.max_optimo)
                severidad = "CRITICA" if desv >= 0.15 * span else "ADVERTENCIA"
                umbral_str = (
                    f"< {u.min_optimo:.2f} {u.unidad}"
                    if val < u.min_optimo
                    else f"> {u.max_optimo:.2f} {u.unidad}"
                )
                msg = (
                    f"{u.parametro.upper()} fuera de rango óptimo ({val:.2f} {u.unidad}; "
                    f"óptimo {u.min_optimo:.2f}–{u.max_optimo:.2f} {u.unidad})."
                )
                self._upsert_active_alert(
                    db, device.id, lectura.id, u.parametro, val, umbral_str, severidad, msg
                )
            else:
                self._healthy_streaks[key] += 1
                if self._healthy_streaks[key] >= self.resolve_cycles:
                    activas = list(
                        db.scalars(
                            select(Alerta).where(
                                Alerta.dispositivo_id == device.id,
                                Alerta.parametro == u.parametro,
                                Alerta.estado.in_(("ACTIVA", "RECONOCIDA")),
                            )
                        )
                    )
                    for al in activas:
                        al.estado = "RESUELTA"
                        al.resuelta_en = now

    def _persist_validated_record(
        self,
        db: Session,
        device_id_mqtt: str,
        payload: TelemetryPayloadIn,
        calidad_dato: str,
        faults: list[tuple[str, str, float]],
        recibido_en: datetime,
    ) -> dict[str, Any]:
        device = ensure_default_entities(db, device_id_mqtt)
        prev_status = device.estado_conexion
        device.ultimo_latido = recibido_en
        device.modo_operacion = payload.modo_operacion
        device.actuador_activo = payload.actuador_estado
        if prev_status != "ONLINE":
            device.estado_conexion = "ONLINE"
            db.add(
                EventoComunicacion(
                    dispositivo_id=device.id,
                    estado_anterior=prev_status,
                    estado_nuevo="ONLINE",
                    gravedad="INFO",
                    detalle="Telemetría recibida: enlace restablecido a ONLINE.",
                    registrado_en=recibido_en,
                )
            )

        lectura = LecturaTelemetria(
            dispositivo_id=device.id,
            ph=payload.ph,
            temperatura_c=payload.temperatura_c,
            tds_ppm=payload.tds_ppm,
            ec_ppm=payload.ec_ppm,
            salinidad_ppm=payload.salinidad_ppm,
            actuador_estado=payload.actuador_estado,
            modo_operacion=payload.modo_operacion,
            calidad_dato=calidad_dato,
            timestamp_dispositivo=payload.timestamp_dispositivo,
            recibido_en=recibido_en,
        )
        db.add(lectura)
        db.flush()

        for fault_param, fault_msg, fault_val in faults:
            self._upsert_active_alert(
                db=db,
                device_id=device.id,
                lectura_id=lectura.id,
                parametro=fault_param,
                valor=fault_val,
                umbral_str="mantenimiento_sensor",
                severidad="ADVERTENCIA",
                mensaje=fault_msg,
            )

        self._evaluate_thresholds_with_hysteresis(db, device, lectura, recibido_en)

        return {
            "event": "telemetry",
            "device_id": device.client_id_mqtt,
            "estado_conexion": device.estado_conexion,
            "modo_operacion": device.modo_operacion,
            "actuador_activo": device.actuador_activo,
            "reading": {
                "id": lectura.id,
                "dispositivo_id": device.id,
                "ph": lectura.ph,
                "temperatura_c": lectura.temperatura_c,
                "tds_ppm": lectura.tds_ppm,
                "ec_ppm": lectura.ec_ppm,
                "salinidad_ppm": lectura.salinidad_ppm,
                "actuador_estado": lectura.actuador_estado,
                "modo_operacion": lectura.modo_operacion,
                "calidad_dato": lectura.calidad_dato,
                "recibido_en": recibido_en.isoformat(),
            },
        }

    def drain_buffer(self) -> int:
        """Drena en lote las lecturas almacenadas en buffer_pendiente.jsonl hacia PostgreSQL."""
        if self.buffer.pending_count() == 0:
            return 0

        def _persist_one(record: dict[str, Any]) -> None:
            payload = TelemetryPayloadIn.model_validate(record["payload"])
            recibido_en = datetime.fromisoformat(record["recibido_en"])
            with self.session_factory() as db:
                self._persist_validated_record(
                    db=db,
                    device_id_mqtt=record["device_id"],
                    payload=payload,
                    calidad_dato=record.get("calidad_dato", "VALIDA"),
                    faults=[],
                    recibido_en=recibido_en,
                )
                db.commit()

        drained = self.buffer.drain(_persist_one)
        if drained:
            logger.info("Drenadas %d lecturas desde buffer local hacia PostgreSQL.", drained)
        return drained

    def process_raw_telemetry(
        self,
        topic: str,
        payload_bytes: bytes,
        device_id_mqtt: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Punto de entrada principal del worker MQTT para tramas de telemetría."""
        ts = now or utcnow()
        validated, err_msg = self.validate_raw_payload(payload_bytes)
        if err_msg or validated is None:
            crudo = payload_bytes.decode("utf-8", errors="replace")[:4000]
            logger.warning("Telemetría rechazada en %s: %s", topic, err_msg)
            try:
                with self.session_factory() as db:
                    db.add(
                        MensajeRechazado(
                            topico=topic,
                            payload_crudo=crudo,
                            motivo_rechazo=err_msg or "Error de validación desconocido.",
                            recibido_en=ts,
                        )
                    )
                    db.commit()
            except SQLAlchemyError as db_err:
                logger.error("No se pudo auditar mensaje rechazado (BD caída): %s", db_err)
            return {"status": "rejected", "reason": err_msg}

        dev_key = validated.device_id or device_id_mqtt
        calidad_dato, faults = self._detect_sensor_faults(dev_key, validated, ts)

        try:
            # Primero drenar pendientes si la BD volvió a estar disponible
            self.drain_buffer()
            with self.session_factory() as db:
                event_payload = self._persist_validated_record(
                    db=db,
                    device_id_mqtt=dev_key,
                    payload=validated,
                    calidad_dato=calidad_dato,
                    faults=faults,
                    recibido_en=ts,
                )
                db.commit()
            if self.ws is not None:
                self.ws.broadcast_threadsafe(event_payload)
            return {"status": "persisted", "calidad_dato": calidad_dato, "faults": len(faults)}
        except SQLAlchemyError as db_err:
            logger.error("PostgreSQL no disponible (%s). Guardando lectura en buffer local.", db_err)
            self.buffer.append(
                {
                    "device_id": dev_key,
                    "topico": topic,
                    "calidad_dato": calidad_dato,
                    "recibido_en": ts.isoformat(),
                    "payload": validated.model_dump(mode="json"),
                }
            )
            return {"status": "buffered", "pending": self.buffer.pending_count()}
