"""API REST + WebSocket (/ws/live) FastAPI para la plataforma AquaWeb IoT."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import Base, SessionLocal, check_db_connection, engine, get_db
from backend.models import (
    Alerta,
    Dispositivo,
    Estanque,
    EventoComunicacion,
    LecturaTelemetria,
    MensajeRechazado,
    OrdenControl,
    UmbralParametro,
    utcnow,
)
from backend.schemas import (
    AlertActionRequest,
    AlertOut,
    AnalyticsSummaryOut,
    CommEventOut,
    CommandOut,
    ControlCommandRequest,
    DeviceOut,
    RejectedMessageOut,
    ThresholdOut,
    ThresholdUpdateRequest,
)
from backend.services.analytics import aggregate_readings, compute_descriptive_analytics, compute_uptime_pct
from backend.services.buffer import LocalTelemetryBuffer
from backend.services.connectivity_monitor import ConnectivityMonitor
from backend.services.mqtt_worker import AquaWebMQTTWorker
from backend.services.telemetry_processor import TelemetryProcessor, ensure_default_entities
from backend.services.ws_manager import ws_manager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("aquaweb.api")

telemetry_buffer = LocalTelemetryBuffer(settings.buffer_path)
telemetry_processor = TelemetryProcessor(SessionLocal, telemetry_buffer, ws=ws_manager)
connectivity_monitor = ConnectivityMonitor(SessionLocal, ws=ws_manager)
mqtt_worker = AquaWebMQTTWorker(telemetry_processor, connectivity_monitor)


def _resolve_range_window(
    range_preset: str,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    now = utcnow()
    end_dt = end or now
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start is not None:
        start_dt = start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)
        return start_dt, end_dt

    deltas = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    return end_dt - deltas.get(range_preset, timedelta(hours=24)), end_dt


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Protege endpoints críticos de control remoto y edición de umbrales."""
    if not settings.api_key:
        return
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera X-API-Key inválida o ausente.",
        )


def _get_target_device(db: Session, device_id: str | None = None) -> Dispositivo:
    target = device_id or settings.mqtt_device_id
    device = db.scalar(select(Dispositivo).where(Dispositivo.client_id_mqtt == target))
    if device is None:
        device = db.scalar(select(Dispositivo).order_by(Dispositivo.id.asc()))
    if device is None:
        device = ensure_default_entities(db, target)
        db.commit()
    return device


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_manager.bind_loop(asyncio.get_running_loop())
    if check_db_connection():
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            ensure_default_entities(db, settings.mqtt_device_id)
            db.commit()
    else:
        logger.warning("Base de datos no accesible al iniciar; buffer local activado.")
    mqtt_worker.start()
    try:
        yield
    finally:
        mqtt_worker.stop()


app = FastAPI(
    title="AquaWeb IoT API",
    description="Plataforma determinística de telemetría, alertas y analítica descriptiva acuícola (sin IA/ML).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.github\.io",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_private_network_access_header(request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "database_connected": check_db_connection(),
        "mqtt_connected": mqtt_worker.connected,
        "buffer_pending": telemetry_buffer.pending_count(),
        "timestamp": utcnow().isoformat(),
    }


@app.get("/api/devices", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db)) -> list[Dispositivo]:
    devices = list(db.scalars(select(Dispositivo).order_by(Dispositivo.id.asc())))
    if not devices:
        dev = ensure_default_entities(db, settings.mqtt_device_id)
        db.commit()
        devices = [dev]
    return devices


@app.get("/api/overview")
def get_overview(
    device_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    device = _get_target_device(db, device_id)
    estanque = db.get(Estanque, device.estanque_id)
    latest_two = list(
        db.scalars(
            select(LecturaTelemetria)
            .where(LecturaTelemetria.dispositivo_id == device.id)
            .order_by(desc(LecturaTelemetria.recibido_en))
            .limit(20)
        )
    )
    thresholds = list(
        db.scalars(
            select(UmbralParametro).where(UmbralParametro.estanque_id == device.estanque_id)
        )
    )
    active_alerts = list(
        db.scalars(
            select(Alerta)
            .where(Alerta.dispositivo_id == device.id, Alerta.estado.in_(("ACTIVA", "RECONOCIDA")))
            .order_by(desc(Alerta.creada_en))
        )
    )
    recent_chron = list(reversed(latest_two))
    latest = latest_two[0] if latest_two else None
    previous = latest_two[1] if len(latest_two) > 1 else None

    def _serialize_reading(r: LecturaTelemetria | None) -> dict[str, Any] | None:
        if r is None:
            return None
        return {
            "id": r.id,
            "ph": float(r.ph),
            "temperatura_c": float(r.temperatura_c),
            "tds_ppm": float(r.tds_ppm),
            "ec_ppm": float(r.ec_ppm),
            "salinidad_ppm": float(r.salinidad_ppm),
            "actuador_estado": bool(r.actuador_estado),
            "modo_operacion": r.modo_operacion,
            "calidad_dato": r.calidad_dato,
            "recibido_en": r.recibido_en.isoformat(),
        }

    return {
        "estanque": {
            "id": estanque.id,
            "nombre": estanque.nombre,
            "ubicacion": estanque.ubicacion,
            "especie": estanque.especie,
            "volumen_m3": float(estanque.volumen_m3),
        }
        if estanque
        else None,
        "dispositivo": DeviceOut.model_validate(device).model_dump(mode="json"),
        "ultima_lectura": _serialize_reading(latest),
        "lectura_anterior": _serialize_reading(previous),
        "sparkline": [_serialize_reading(r) for r in recent_chron],
        "umbrales": [ThresholdOut.model_validate(u).model_dump(mode="json") for u in thresholds],
        "alertas_activas": len(active_alerts),
        "buffer_pendiente": telemetry_buffer.pending_count(),
        "mqtt_conectado": mqtt_worker.connected,
    }


@app.get("/api/telemetry")
def get_telemetry(
    device_id: str | None = Query(default=None),
    range_preset: str = Query(default="24h", alias="range"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    aggregation: str = Query(default="raw", pattern="^(raw|minute|hour)$"),
    limit: int = Query(default=2000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    device = _get_target_device(db, device_id)
    start_dt, end_dt = _resolve_range_window(range_preset, start, end)
    rows = list(
        db.scalars(
            select(LecturaTelemetria)
            .where(
                LecturaTelemetria.dispositivo_id == device.id,
                LecturaTelemetria.recibido_en >= start_dt,
                LecturaTelemetria.recibido_en <= end_dt,
            )
            .order_by(LecturaTelemetria.recibido_en.asc())
            .limit(limit)
        )
    )
    items = aggregate_readings(rows, granularity=aggregation)
    return {
        "device_id": device.client_id_mqtt,
        "range_start": start_dt.isoformat(),
        "range_end": end_dt.isoformat(),
        "aggregation": aggregation,
        "count": len(items),
        "items": items,
    }


@app.get("/api/analytics", response_model=AnalyticsSummaryOut)
def get_analytics(
    device_id: str | None = Query(default=None),
    range_preset: str = Query(default="7d", alias="range"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryOut:
    device = _get_target_device(db, device_id)
    start_dt, end_dt = _resolve_range_window(range_preset, start, end)
    return compute_descriptive_analytics(db, device, start_dt, end_dt)


@app.get("/api/alerts", response_model=list[AlertOut])
def list_alerts(
    device_id: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    severidad: str | None = Query(default=None),
    parametro: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Alerta]:
    device = _get_target_device(db, device_id)
    stmt = select(Alerta).where(Alerta.dispositivo_id == device.id)
    if estado:
        stmt = stmt.where(Alerta.estado == estado)
    if severidad:
        stmt = stmt.where(Alerta.severidad == severidad)
    if parametro:
        stmt = stmt.where(Alerta.parametro == parametro)
    stmt = stmt.order_by(desc(Alerta.creada_en)).limit(limit)
    return list(db.scalars(stmt))


@app.patch("/api/alerts/{alert_id}", response_model=AlertOut)
def update_alert_status(
    alert_id: int,
    body: AlertActionRequest,
    db: Session = Depends(get_db),
) -> Alerta:
    alerta = db.get(Alerta, alert_id)
    if alerta is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    alerta.estado = body.estado
    if body.estado == "RESUELTA":
        alerta.resuelta_en = utcnow()
    db.commit()
    db.refresh(alerta)
    return alerta


@app.get("/api/connectivity/events")
def get_connectivity_events(
    device_id: str | None = Query(default=None),
    range_preset: str = Query(default="7d", alias="range"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    device = _get_target_device(db, device_id)
    start_dt, end_dt = _resolve_range_window(range_preset, None, None)
    events = list(
        db.scalars(
            select(EventoComunicacion)
            .where(EventoComunicacion.dispositivo_id == device.id)
            .order_by(desc(EventoComunicacion.registrado_en))
            .limit(limit)
        )
    )
    uptime = compute_uptime_pct(events, device, start_dt, end_dt)
    return {
        "device_id": device.client_id_mqtt,
        "estado_actual": device.estado_conexion,
        "uptime_pct": uptime,
        "events": [CommEventOut.model_validate(e).model_dump(mode="json") for e in events],
    }


@app.get("/api/data-quality")
def get_data_quality(
    device_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    device = _get_target_device(db, device_id)
    suspicious = list(
        db.scalars(
            select(LecturaTelemetria)
            .where(
                LecturaTelemetria.dispositivo_id == device.id,
                LecturaTelemetria.calidad_dato == "SOSPECHOSA",
            )
            .order_by(desc(LecturaTelemetria.recibido_en))
            .limit(limit)
        )
    )
    rejected = list(
        db.scalars(
            select(MensajeRechazado).order_by(desc(MensajeRechazado.recibido_en)).limit(limit)
        )
    )
    return {
        "lecturas_sospechosas": aggregate_readings(suspicious, granularity="raw"),
        "mensajes_rechazados": [
            RejectedMessageOut.model_validate(m).model_dump(mode="json") for m in rejected
        ],
    }


@app.get("/api/thresholds", response_model=list[ThresholdOut])
def get_thresholds(
    device_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[UmbralParametro]:
    device = _get_target_device(db, device_id)
    return list(
        db.scalars(
            select(UmbralParametro)
            .where(UmbralParametro.estanque_id == device.estanque_id)
            .order_by(UmbralParametro.id.asc())
        )
    )


@app.put("/api/thresholds", response_model=ThresholdOut, dependencies=[Depends(verify_api_key)])
def update_threshold(
    body: ThresholdUpdateRequest,
    device_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UmbralParametro:
    device = _get_target_device(db, device_id)
    umbral = db.scalar(
        select(UmbralParametro).where(
            UmbralParametro.estanque_id == device.estanque_id,
            UmbralParametro.parametro == body.parametro,
        )
    )
    if umbral is None:
        raise HTTPException(status_code=404, detail="Parámetro de umbral no encontrado.")

    umbral.min_optimo = round(body.min_optimo, 2)
    umbral.max_optimo = round(body.max_optimo, 2)
    umbral.actualizado_en = utcnow()

    cmd_id = str(uuid.uuid4())
    payload = {
        "command_id": cmd_id,
        "parametro": body.parametro,
        "min_optimo": umbral.min_optimo,
        "max_optimo": umbral.max_optimo,
    }
    orden = OrdenControl(
        dispositivo_id=device.id,
        command_id=cmd_id,
        tipo_orden="ACTUALIZAR_UMBRALES",
        payload_json=payload,
        estado="ENVIADA",
        detalle_respuesta="Enviado al broker MQTT tras actualizar PostgreSQL.",
    )
    db.add(orden)
    db.commit()
    db.refresh(umbral)

    mqtt_worker.publish_command(device.client_id_mqtt, payload)
    return umbral


@app.get("/api/commands", response_model=list[CommandOut])
def list_commands(
    device_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[OrdenControl]:
    device = _get_target_device(db, device_id)
    return list(
        db.scalars(
            select(OrdenControl)
            .where(OrdenControl.dispositivo_id == device.id)
            .order_by(desc(OrdenControl.creada_en))
            .limit(limit)
        )
    )


@app.post(
    "/api/commands",
    response_model=CommandOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
)
def send_control_command(
    body: ControlCommandRequest,
    device_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OrdenControl:
    device = _get_target_device(db, device_id)
    if device.estado_conexion == "OFFLINE":
        raise HTTPException(
            status_code=422,
            detail="No se pueden enviar órdenes remotas: el dispositivo se encuentra OFFLINE.",
        )

    effective_mode = body.modo or device.modo_operacion
    if body.actuador is not None and effective_mode != "MANUAL":
        raise HTTPException(
            status_code=422,
            detail="Para cambiar el actuador manualmente, el dispositivo debe estar en modo MANUAL.",
        )

    cmd_id = str(uuid.uuid4())
    payload: dict[str, Any] = {"command_id": cmd_id}
    if body.modo is not None:
        payload["modo"] = body.modo
    if body.actuador is not None:
        payload["actuador"] = 1 if body.actuador else 0
    if body.simular_silencio is not None:
        payload["simular_silencio"] = body.simular_silencio

    tipo = (
        "CONTROL_ACTUADOR"
        if body.actuador is not None
        else ("SIMULAR_SILENCIO" if body.simular_silencio is not None else "CAMBIO_MODO")
    )

    orden = OrdenControl(
        dispositivo_id=device.id,
        command_id=cmd_id,
        tipo_orden=tipo,
        payload_json=payload,
        estado="ENVIADA",
        detalle_respuesta="Orden publicada en broker MQTT; esperando ordenes_ack.",
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)

    mqtt_worker.publish_command(device.client_id_mqtt, payload)
    return orden


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"event": "connected", "timestamp": utcnow().isoformat()})
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"event": "pong", "timestamp": utcnow().isoformat()})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
