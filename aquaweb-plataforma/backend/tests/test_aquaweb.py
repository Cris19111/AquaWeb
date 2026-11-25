"""Suite de pruebas automatizadas para AquaWeb IoT (pytest)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import settings
from backend.database import Base, get_db
from backend.main import app
from backend.models import (
    Alerta,
    Dispositivo,
    EventoComunicacion,
    LecturaTelemetria,
    MensajeRechazado,
    OrdenControl,
)
from backend.services.buffer import LocalTelemetryBuffer
from backend.services.connectivity_monitor import ConnectivityMonitor
from backend.services.telemetry_processor import TelemetryProcessor, ensure_default_entities


@pytest.fixture()
def test_session_factory() -> Generator[sessionmaker, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def api_client(test_session_factory: sessionmaker) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with test_session_factory() as db:
        dev = ensure_default_entities(db, settings.mqtt_device_id)
        dev.estado_conexion = "ONLINE"
        dev.ultimo_latido = datetime.now(timezone.utc)
        db.commit()

    # Evitar conectar al broker MQTT externo durante pruebas unitarias
    prev_mqtt = settings.mqtt_enabled
    settings.mqtt_enabled = False
    try:
        with TestClient(app) as client:
            yield client
    finally:
        settings.mqtt_enabled = prev_mqtt
        app.dependency_overrides.clear()


def _valid_payload(**overrides) -> bytes:
    base = {
        "device_id": "estanque-01",
        "ph": 7.85,
        "temperatura_c": 26.5,
        "tds_ppm": 9800.0,
        "ec_ppm": 20500.0,
        "salinidad_ppm": 13400.0,
        "actuador_estado": False,
        "modo_operacion": "AUTO",
    }
    base.update(overrides)
    return json.dumps(base).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Validación estricta de telemetría válida, corrupta y fuera de rango físico
# ---------------------------------------------------------------------------
def test_telemetry_validation_valid_and_rejected(test_session_factory: sessionmaker, tmp_path: Path):
    buf = LocalTelemetryBuffer(tmp_path / "buffer_pendiente.jsonl")
    proc = TelemetryProcessor(test_session_factory, buf)
    topic = "utp/ds8/grupo/aquaweb/estanque-01/telemetria"

    res_ok = proc.process_raw_telemetry(topic, _valid_payload(), "estanque-01")
    assert res_ok["status"] == "persisted"
    assert res_ok["calidad_dato"] == "VALIDA"

    invalid_cases = [
        b"",
        b"{ph: 7.5, roto",
        b'{"ph": NaN, "temperatura_c": 26, "tds_ppm": 5000, "ec_ppm": 12000, "salinidad_ppm": 8000, "actuador_estado": false, "modo_operacion": "AUTO"}',
        _valid_payload(ph=-2.0),
        _valid_payload(ph=19.0),
        _valid_payload(temperatura_c=200.0),
        _valid_payload(ph=True),
    ]
    for bad in invalid_cases:
        res = proc.process_raw_telemetry(topic, bad, "estanque-01")
        assert res["status"] == "rejected"

    with test_session_factory() as db:
        lecturas = list(db.scalars(select(LecturaTelemetria)))
        rechazados = list(db.scalars(select(MensajeRechazado)))
        assert len(lecturas) == 1
        assert len(rechazados) == len(invalid_cases)


# ---------------------------------------------------------------------------
# 2. Sensor congelado, salto abrupto y alertas sin duplicados con auto-resolución
# ---------------------------------------------------------------------------
def test_frozen_sensor_abrupt_jump_and_alert_hysteresis(test_session_factory: sessionmaker, tmp_path: Path):
    buf = LocalTelemetryBuffer(tmp_path / "buffer_pendiente.jsonl")
    proc = TelemetryProcessor(test_session_factory, buf, frozen_cycles=3, resolve_cycles=2)
    topic = "utp/ds8/grupo/aquaweb/estanque-01/telemetria"
    t0 = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)

    # 3 lecturas idénticas con pH alto (10.2 > 9.5) -> 1 sola alerta de pH + alerta sensor_congelado
    for i in range(3):
        res = proc.process_raw_telemetry(
            topic,
            _valid_payload(ph=10.2, temperatura_c=27.0),
            "estanque-01",
            now=t0 + timedelta(seconds=i * 5),
        )
        assert res["status"] == "persisted"
        if i == 2:
            assert res["calidad_dato"] == "SOSPECHOSA"

    with test_session_factory() as db:
        ph_alerts = list(db.scalars(select(Alerta).where(Alerta.parametro == "ph")))
        frozen_alerts = list(db.scalars(select(Alerta).where(Alerta.parametro == "sensor_congelado")))
        assert len(ph_alerts) == 1, "No debe crear alertas duplicadas en ciclos consecutivos"
        assert ph_alerts[0].estado == "ACTIVA"
        assert len(frozen_alerts) == 1

    # Salto abrupto de pH (> 2.5 unidades en 5 s: de 10.2 a 7.2 = Δ3.0) -> SOSPECHOSA
    res_jump = proc.process_raw_telemetry(
        topic,
        _valid_payload(ph=7.2, temperatura_c=27.1),
        "estanque-01",
        now=t0 + timedelta(seconds=15),
    )
    assert res_jump["calidad_dato"] == "SOSPECHOSA"

    # Segundo ciclo estable dentro de rango óptimo -> resuelve automáticamente la alerta de pH
    proc.process_raw_telemetry(
        topic,
        _valid_payload(ph=7.3, temperatura_c=27.2),
        "estanque-01",
        now=t0 + timedelta(seconds=20),
    )

    with test_session_factory() as db:
        ph_alert = db.scalar(select(Alerta).where(Alerta.parametro == "ph"))
        jump_alert = db.scalar(select(Alerta).where(Alerta.parametro == "salto_ph"))
        assert ph_alert is not None and ph_alert.estado == "RESUELTA"
        assert ph_alert.resuelta_en is not None
        assert jump_alert is not None


# ---------------------------------------------------------------------------
# 3. Resiliencia ante caída de PostgreSQL: buffer_pendiente.jsonl + drenado
# ---------------------------------------------------------------------------
def test_postgres_outage_buffer_and_drain(test_session_factory: sessionmaker, tmp_path: Path):
    buf_file = tmp_path / "buffer_pendiente.jsonl"
    buf = LocalTelemetryBuffer(buf_file)

    class FailingSessionFactory:
        def __call__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    proc_down = TelemetryProcessor(FailingSessionFactory(), buf)  # type: ignore[arg-type]
    topic = "utp/ds8/grupo/aquaweb/estanque-01/telemetria"

    r1 = proc_down.process_raw_telemetry(topic, _valid_payload(ph=7.5), "estanque-01")
    r2 = proc_down.process_raw_telemetry(topic, _valid_payload(ph=7.7), "estanque-01")
    assert r1["status"] == "buffered"
    assert r2["status"] == "buffered"
    assert buf_file.exists()
    assert buf.pending_count() == 2

    # Base de datos recuperada -> drenar en lote
    proc_up = TelemetryProcessor(test_session_factory, buf)
    drained = proc_up.drain_buffer()
    assert drained == 2
    assert buf.pending_count() == 0
    assert not buf_file.exists()

    with test_session_factory() as db:
        lecturas = list(db.scalars(select(LecturaTelemetria).order_by(LecturaTelemetria.id.asc())))
        assert len(lecturas) == 2
        assert lecturas[0].ph == 7.5
        assert lecturas[1].ph == 7.7


# ---------------------------------------------------------------------------
# 4. Transiciones ONLINE -> SIN_DATOS -> OFFLINE y expiración de órdenes
# ---------------------------------------------------------------------------
def test_connectivity_transitions_and_command_expiration(test_session_factory: sessionmaker):
    monitor = ConnectivityMonitor(test_session_factory, silence_multiplier=3, command_timeout_seg=15)
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    # ONLINE (repetido 2 veces -> solo 1 evento)
    monitor.handle_status_message("estanque-01", b"ONLINE", retain=False, now=t0)
    monitor.handle_status_message("estanque-01", b"ONLINE", retain=False, now=t0 + timedelta(seconds=2))

    # Crear orden pendiente para validar expiración por timeout
    with test_session_factory() as db:
        dev = db.scalar(select(Dispositivo).where(Dispositivo.client_id_mqtt == "estanque-01"))
        assert dev is not None
        db.add(
            OrdenControl(
                dispositivo_id=dev.id,
                command_id="99999999-9999-4999-8999-999999999999",
                tipo_orden="CAMBIO_MODO",
                payload_json={"modo": "MANUAL"},
                estado="ENVIADA",
                creada_en=t0,
                actualizada_en=t0,
            )
        )
        db.commit()

    # Después de 18 s desde t0 (16 s desde el último ONLINE >= 3*5s silencio y >= 15s timeout orden)
    summary = monitor.evaluate_cycle(now=t0 + timedelta(seconds=18))
    assert summary["marked_silent"] == 1
    assert summary["expired_commands"] == 1

    # LWT OFFLINE
    monitor.handle_status_message("estanque-01", b"OFFLINE", retain=True, now=t0 + timedelta(seconds=25))

    with test_session_factory() as db:
        events = list(db.scalars(select(EventoComunicacion).order_by(EventoComunicacion.id.asc())))
        states = [e.estado_nuevo for e in events]
        assert states == ["ONLINE", "SIN_DATOS", "OFFLINE"]
        orden = db.scalar(select(OrdenControl))
        assert orden is not None and orden.estado == "EXPIRADA"


# ---------------------------------------------------------------------------
# 5. Endpoints FastAPI: REST, seguridad X-API-Key (401) y validación (422)
# ---------------------------------------------------------------------------
def test_fastapi_endpoints_auth_and_validation(api_client: TestClient, test_session_factory: sessionmaker):
    # Health y overview accesibles
    assert api_client.get("/api/health").status_code == 200
    ov = api_client.get("/api/overview")
    assert ov.status_code == 200
    assert ov.json()["dispositivo"]["client_id_mqtt"] == "estanque-01"

    # Sin X-API-Key -> 401
    r_no_key = api_client.post("/api/commands", json={"modo": "MANUAL", "actuador": True})
    assert r_no_key.status_code == 401

    r_bad_key = api_client.put(
        "/api/thresholds",
        headers={"X-API-Key": "wrong-key"},
        json={"parametro": "ph", "min_optimo": 6.8, "max_optimo": 9.0},
    )
    assert r_bad_key.status_code == 401

    headers = {"X-API-Key": settings.api_key}

    # Umbrales inválidos: min >= max -> 422
    r_inv_range = api_client.put(
        "/api/thresholds",
        headers=headers,
        json={"parametro": "ph", "min_optimo": 9.5, "max_optimo": 6.5},
    )
    assert r_inv_range.status_code == 422

    # Umbral fuera de rango físico -> 422
    r_inv_phys = api_client.put(
        "/api/thresholds",
        headers=headers,
        json={"parametro": "ph", "min_optimo": 6.5, "max_optimo": 18.0},
    )
    assert r_inv_phys.status_code == 422

    # Umbral válido -> 200
    r_ok_thr = api_client.put(
        "/api/thresholds",
        headers=headers,
        json={"parametro": "ph", "min_optimo": 6.8, "max_optimo": 9.2},
    )
    assert r_ok_thr.status_code == 200
    assert r_ok_thr.json()["min_optimo"] == 6.8

    # Orden válida con dispositivo ONLINE -> 201
    r_cmd = api_client.post(
        "/api/commands",
        headers=headers,
        json={"modo": "MANUAL", "actuador": True},
    )
    assert r_cmd.status_code == 201
    assert r_cmd.json()["estado"] == "ENVIADA"

    # Marcar dispositivo OFFLINE -> orden debe rechazarse con HTTP 422
    with test_session_factory() as db:
        dev = db.scalar(select(Dispositivo))
        assert dev is not None
        dev.estado_conexion = "OFFLINE"
        db.commit()

    r_cmd_off = api_client.post(
        "/api/commands",
        headers=headers,
        json={"modo": "MANUAL", "actuador": False},
    )
    assert r_cmd_off.status_code == 422

    # Analítica y calidad de datos
    assert api_client.get("/api/analytics?range=7d").status_code == 200
    assert api_client.get("/api/data-quality").status_code == 200
    assert api_client.get("/api/connectivity/events").status_code == 200
