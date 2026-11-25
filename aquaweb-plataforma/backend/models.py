"""Modelos ORM SQLAlchemy 2.0 alineados al esquema PostgreSQL 16 de database/init.sql."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class Estanque(Base):
    __tablename__ = "estanques"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    ubicacion: Mapped[str] = mapped_column(String(180), nullable=False)
    especie: Mapped[str] = mapped_column(String(120), nullable=False, default="Litopenaeus vannamei")
    volumen_m3: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    dispositivos: Mapped[list["Dispositivo"]] = relationship(back_populates="estanque", cascade="all, delete-orphan")
    umbrales: Mapped[list["UmbralParametro"]] = relationship(back_populates="estanque", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("volumen_m3 > 0", name="chk_estanque_volumen"),)


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    estanque_id: Mapped[int] = mapped_column(ForeignKey("estanques.id", ondelete="CASCADE"), nullable=False)
    client_id_mqtt: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    estado_conexion: Mapped[str] = mapped_column(String(20), nullable=False, default="OFFLINE")
    modo_operacion: Mapped[str] = mapped_column(String(10), nullable=False, default="AUTO")
    actuador_activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intervalo_pub_seg: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    ultimo_latido: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    estanque: Mapped["Estanque"] = relationship(back_populates="dispositivos")
    lecturas: Mapped[list["LecturaTelemetria"]] = relationship(back_populates="dispositivo", cascade="all, delete-orphan")
    alertas: Mapped[list["Alerta"]] = relationship(back_populates="dispositivo", cascade="all, delete-orphan")
    eventos: Mapped[list["EventoComunicacion"]] = relationship(back_populates="dispositivo", cascade="all, delete-orphan")
    ordenes: Mapped[list["OrdenControl"]] = relationship(back_populates="dispositivo", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("estado_conexion IN ('ONLINE', 'SIN_DATOS', 'OFFLINE')", name="chk_disp_estado"),
        CheckConstraint("modo_operacion IN ('AUTO', 'MANUAL')", name="chk_disp_modo"),
        CheckConstraint("intervalo_pub_seg >= 1 AND intervalo_pub_seg <= 3600", name="chk_disp_intervalo"),
    )


class UmbralParametro(Base):
    __tablename__ = "umbrales_parametros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    estanque_id: Mapped[int] = mapped_column(ForeignKey("estanques.id", ondelete="CASCADE"), nullable=False)
    parametro: Mapped[str] = mapped_column(String(20), nullable=False)
    min_optimo: Mapped[float] = mapped_column(Float, nullable=False)
    max_optimo: Mapped[float] = mapped_column(Float, nullable=False)
    min_fisico: Mapped[float] = mapped_column(Float, nullable=False)
    max_fisico: Mapped[float] = mapped_column(Float, nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    estanque: Mapped["Estanque"] = relationship(back_populates="umbrales")

    __table_args__ = (
        UniqueConstraint("estanque_id", "parametro", name="uq_umbral_estanque_parametro"),
        CheckConstraint(
            "parametro IN ('ph', 'temperatura', 'tds', 'ec', 'salinidad')",
            name="chk_umbral_parametro",
        ),
        CheckConstraint(
            "min_fisico <= min_optimo AND min_optimo < max_optimo AND max_optimo <= max_fisico",
            name="chk_umbrales_orden",
        ),
    )


class LecturaTelemetria(Base):
    __tablename__ = "lecturas_telemetria"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    dispositivo_id: Mapped[int] = mapped_column(ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False)
    ph: Mapped[float] = mapped_column(Float, nullable=False)
    temperatura_c: Mapped[float] = mapped_column(Float, nullable=False)
    tds_ppm: Mapped[float] = mapped_column(Float, nullable=False)
    ec_ppm: Mapped[float] = mapped_column(Float, nullable=False)
    salinidad_ppm: Mapped[float] = mapped_column(Float, nullable=False)
    actuador_estado: Mapped[bool] = mapped_column(Boolean, nullable=False)
    modo_operacion: Mapped[str] = mapped_column(String(10), nullable=False)
    calidad_dato: Mapped[str] = mapped_column(String(15), nullable=False, default="VALIDA")
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    dispositivo: Mapped["Dispositivo"] = relationship(back_populates="lecturas")

    __table_args__ = (
        Index("idx_lecturas_dispositivo_recibido", "dispositivo_id", recibido_en.desc()),
        CheckConstraint("ph >= 0.0 AND ph <= 14.0", name="chk_tel_ph"),
        CheckConstraint("temperatura_c >= -5.0 AND temperatura_c <= 60.0", name="chk_tel_temp"),
        CheckConstraint("tds_ppm >= 0.0 AND tds_ppm <= 50000.0", name="chk_tel_tds"),
        CheckConstraint("ec_ppm >= 0.0 AND ec_ppm <= 80000.0", name="chk_tel_ec"),
        CheckConstraint("salinidad_ppm >= 0.0 AND salinidad_ppm <= 50000.0", name="chk_tel_sal"),
        CheckConstraint("modo_operacion IN ('AUTO', 'MANUAL')", name="chk_tel_modo"),
        CheckConstraint("calidad_dato IN ('VALIDA', 'SOSPECHOSA')", name="chk_tel_calidad"),
    )


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    dispositivo_id: Mapped[int] = mapped_column(ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False)
    lectura_id: Mapped[int | None] = mapped_column(ForeignKey("lecturas_telemetria.id", ondelete="SET NULL"), nullable=True)
    parametro: Mapped[str] = mapped_column(String(30), nullable=False)
    valor_detectado: Mapped[float | None] = mapped_column(Float, nullable=True)
    umbral_infringido: Mapped[str] = mapped_column(String(60), nullable=False)
    severidad: Mapped[str] = mapped_column(String(20), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVA")
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resuelta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dispositivo: Mapped["Dispositivo"] = relationship(back_populates="alertas")

    __table_args__ = (
        CheckConstraint("severidad IN ('ADVERTENCIA', 'CRITICA')", name="chk_alerta_sev"),
        CheckConstraint("estado IN ('ACTIVA', 'RECONOCIDA', 'RESUELTA')", name="chk_alerta_est"),
    )


class EventoComunicacion(Base):
    __tablename__ = "eventos_comunicacion"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    dispositivo_id: Mapped[int] = mapped_column(ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False)
    estado_anterior: Mapped[str] = mapped_column(String(20), nullable=False)
    estado_nuevo: Mapped[str] = mapped_column(String(20), nullable=False)
    gravedad: Mapped[str] = mapped_column(String(15), nullable=False)
    detalle: Mapped[str] = mapped_column(Text, nullable=False)
    registrado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    dispositivo: Mapped["Dispositivo"] = relationship(back_populates="eventos")

    __table_args__ = (
        CheckConstraint("estado_nuevo IN ('ONLINE', 'SIN_DATOS', 'OFFLINE')", name="chk_evt_estado"),
        CheckConstraint("gravedad IN ('INFO', 'WARNING', 'CRITICAL')", name="chk_evt_grav"),
    )


class OrdenControl(Base):
    __tablename__ = "ordenes_control"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    dispositivo_id: Mapped[int] = mapped_column(ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False)
    command_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, unique=True)
    tipo_orden: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="ENVIADA")
    detalle_respuesta: Mapped[str | None] = mapped_column(Text, nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actualizada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    dispositivo: Mapped["Dispositivo"] = relationship(back_populates="ordenes")

    __table_args__ = (
        CheckConstraint(
            "estado IN ('ENVIADA', 'APLICADA', 'RECHAZADA', 'EXPIRADA')",
            name="chk_orden_estado",
        ),
    )


class MensajeRechazado(Base):
    __tablename__ = "mensajes_rechazados"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    topico: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_crudo: Mapped[str] = mapped_column(Text, nullable=False)
    motivo_rechazo: Mapped[str] = mapped_column(Text, nullable=False)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
