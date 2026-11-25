"""Esquemas Pydantic v2 con validación estricta de telemetría, órdenes y API REST."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.config import PHYSICAL_LIMITS


def _validate_strict_finite_number(value: Any, field_name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{field_name}' debe ser numérico (no booleano ni texto).")
    fval = float(value)
    if not math.isfinite(fval):
        raise ValueError(f"'{field_name}' contiene NaN o Infinity.")
    if not (lo <= fval <= hi):
        raise ValueError(f"'{field_name}' fuera de rango físico [{lo}, {hi}]: {fval}.")
    return round(fval, 2)


class TelemetryPayloadIn(BaseModel):
    """Valida tramas MQTT entrantes de las 5 variables acuícolas."""

    model_config = ConfigDict(extra="ignore")

    device_id: str | None = None
    ph: Any
    temperatura_c: Any
    tds_ppm: Any
    ec_ppm: Any
    salinidad_ppm: Any
    actuador_estado: bool
    modo_operacion: Literal["AUTO", "MANUAL"]
    timestamp_dispositivo: datetime | None = None

    @field_validator("ph")
    @classmethod
    def check_ph(cls, v: Any) -> float:
        return _validate_strict_finite_number(v, "ph", *PHYSICAL_LIMITS["ph"])

    @field_validator("temperatura_c")
    @classmethod
    def check_temp(cls, v: Any) -> float:
        return _validate_strict_finite_number(v, "temperatura_c", *PHYSICAL_LIMITS["temperatura"])

    @field_validator("tds_ppm")
    @classmethod
    def check_tds(cls, v: Any) -> float:
        return _validate_strict_finite_number(v, "tds_ppm", *PHYSICAL_LIMITS["tds"])

    @field_validator("ec_ppm")
    @classmethod
    def check_ec(cls, v: Any) -> float:
        return _validate_strict_finite_number(v, "ec_ppm", *PHYSICAL_LIMITS["ec"])

    @field_validator("salinidad_ppm")
    @classmethod
    def check_sal(cls, v: Any) -> float:
        return _validate_strict_finite_number(v, "salinidad_ppm", *PHYSICAL_LIMITS["salinidad"])

    @field_validator("actuador_estado", mode="before")
    @classmethod
    def check_actuador(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, int) and v in (0, 1):
            return bool(v)
        raise ValueError("'actuador_estado' debe ser booleano o entero 0/1.")


class CommandAckIn(BaseModel):
    command_id: str
    device_id: str | None = None
    estado: Literal["APLICADA", "RECHAZADA"]
    detalle: str = ""


class ControlCommandRequest(BaseModel):
    """Solicitud de orden remota hacia el actuador/modo del ESP32."""

    modo: Literal["AUTO", "MANUAL"] | None = None
    actuador: bool | None = None
    simular_silencio: bool | None = None

    @model_validator(mode="after")
    def validate_combinations(self) -> "ControlCommandRequest":
        if self.modo is None and self.actuador is None and self.simular_silencio is None:
            raise ValueError("Debe especificar al menos 'modo', 'actuador' o 'simular_silencio'.")
        if self.modo == "AUTO" and self.actuador is not None:
            raise ValueError("No se puede fijar 'actuador' al solicitar modo AUTO.")
        return self


class ThresholdUpdateRequest(BaseModel):
    """Actualización de umbrales óptimos para un parámetro acuícola."""

    parametro: Literal["ph", "temperatura", "tds", "ec", "salinidad"]
    min_optimo: float
    max_optimo: float

    @model_validator(mode="after")
    def validate_bounds(self) -> "ThresholdUpdateRequest":
        if not (math.isfinite(self.min_optimo) and math.isfinite(self.max_optimo)):
            raise ValueError("Los umbrales deben ser números finitos.")
        if self.min_optimo >= self.max_optimo:
            raise ValueError("min_optimo debe ser estrictamente menor que max_optimo.")
        lo, hi = PHYSICAL_LIMITS[self.parametro]
        if self.min_optimo < lo or self.max_optimo > hi:
            raise ValueError(
                f"Los umbrales para '{self.parametro}' deben estar dentro del rango físico [{lo}, {hi}]."
            )
        return self


class AlertActionRequest(BaseModel):
    estado: Literal["RECONOCIDA", "RESUELTA"]


class ThresholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estanque_id: int
    parametro: str
    min_optimo: float
    max_optimo: float
    min_fisico: float
    max_fisico: float
    unidad: str
    actualizado_en: datetime


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estanque_id: int
    client_id_mqtt: str
    nombre: str
    estado_conexion: str
    modo_operacion: str
    actuador_activo: bool
    intervalo_pub_seg: int
    ultimo_latido: datetime | None


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispositivo_id: int
    ph: float
    temperatura_c: float
    tds_ppm: float
    ec_ppm: float
    salinidad_ppm: float
    actuador_estado: bool
    modo_operacion: str
    calidad_dato: str
    timestamp_dispositivo: datetime | None
    recibido_en: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispositivo_id: int
    lectura_id: int | None
    parametro: str
    valor_detectado: float | None
    umbral_infringido: str
    severidad: str
    mensaje: str
    estado: str
    creada_en: datetime
    resuelta_en: datetime | None


class CommEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispositivo_id: int
    estado_anterior: str
    estado_nuevo: str
    gravedad: str
    detalle: str
    registrado_en: datetime


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispositivo_id: int
    command_id: str
    tipo_orden: str
    payload_json: dict[str, Any]
    estado: str
    detalle_respuesta: str | None
    creada_en: datetime
    actualizada_en: datetime


class RejectedMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topico: str
    payload_crudo: str
    motivo_rechazo: str
    recibido_en: datetime


class ParameterStats(BaseModel):
    parametro: str
    unidad: str
    count: int
    promedio: float
    mediana: float
    minimo: float
    maximo: float
    desviacion_std: float
    tasa_variacion: float
    cumplimiento_pct: float
    violaciones: int
    min_optimo: float
    max_optimo: float
    histograma: list[dict[str, Any]] = Field(default_factory=list)


class AnalyticsSummaryOut(BaseModel):
    rango_inicio: datetime | None
    rango_fin: datetime | None
    total_lecturas: int
    lecturas_validas: int
    lecturas_sospechosas: int
    indice_salud_pct: float
    uptime_pct: float
    parametros: list[ParameterStats]
    violaciones_por_franja: dict[str, int]
