"""Analítica descriptiva y estadística para AquaWeb IoT (estrictamente sin IA/ML)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Dispositivo, EventoComunicacion, LecturaTelemetria, UmbralParametro
from backend.schemas import AnalyticsSummaryOut, ParameterStats
from backend.services.telemetry_processor import PARAM_FIELD_MAP


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _time_slot(dt: datetime) -> str:
    """Clasifica hora en franja horaria: manana (06-11), tarde (12-17), noche (18-05)."""
    hour = dt.hour
    if 6 <= hour < 12:
        return "manana"
    if 12 <= hour < 18:
        return "tarde"
    return "noche"


def _build_histogram(values: list[float], bins: int = 8) -> list[dict[str, Any]]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        return [{"rango": f"{vmin:.2f}", "desde": vmin, "hasta": vmax, "conteo": len(values)}]

    step = (vmax - vmin) / bins
    counts = [0] * bins
    for v in values:
        idx = int((v - vmin) / step)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1

    result: list[dict[str, Any]] = []
    for i in range(bins):
        lo = vmin + i * step
        hi = vmin + (i + 1) * step
        result.append(
            {
                "rango": f"{lo:.1f}–{hi:.1f}",
                "desde": round(lo, 2),
                "hasta": round(hi, 2),
                "conteo": counts[i],
            }
        )
    return result


def compute_uptime_pct(
    events: list[EventoComunicacion],
    device: Dispositivo,
    start_dt: datetime,
    end_dt: datetime,
) -> float:
    """Calcula porcentaje de disponibilidad (tiempo en estado ONLINE) en el rango."""
    total_sec = max((_as_utc(end_dt) - _as_utc(start_dt)).total_seconds(), 1.0)
    if not events:
        return 100.0 if device.estado_conexion == "ONLINE" else 0.0

    ordered = sorted(events, key=lambda e: _as_utc(e.registrado_en))
    start_utc = _as_utc(start_dt)
    end_utc = _as_utc(end_dt)

    # Estado inicial al principio de la ventana
    current_state = ordered[0].estado_anterior if _as_utc(ordered[0].registrado_en) > start_utc else ordered[0].estado_nuevo
    if current_state == "INICIAL":
        current_state = ordered[0].estado_nuevo

    cursor = start_utc
    online_sec = 0.0
    for evt in ordered:
        evt_ts = _as_utc(evt.registrado_en)
        if evt_ts <= start_utc:
            current_state = evt.estado_nuevo
            continue
        if evt_ts > end_utc:
            break
        if current_state == "ONLINE":
            online_sec += max((evt_ts - cursor).total_seconds(), 0.0)
        cursor = evt_ts
        current_state = evt.estado_nuevo

    if current_state == "ONLINE" and end_utc > cursor:
        online_sec += (end_utc - cursor).total_seconds()

    return round(min(100.0, max(0.0, (online_sec / total_sec) * 100.0)), 2)


def aggregate_readings(
    readings: list[LecturaTelemetria],
    granularity: str = "raw",
) -> list[dict[str, Any]]:
    """Agrega lecturas en formato crudo, promedio por minuto o promedio por hora."""
    if granularity == "raw" or not readings:
        return [
            {
                "id": r.id,
                "dispositivo_id": r.dispositivo_id,
                "ph": round(float(r.ph), 2),
                "temperatura_c": round(float(r.temperatura_c), 2),
                "tds_ppm": round(float(r.tds_ppm), 2),
                "ec_ppm": round(float(r.ec_ppm), 2),
                "salinidad_ppm": round(float(r.salinidad_ppm), 2),
                "actuador_estado": bool(r.actuador_estado),
                "modo_operacion": r.modo_operacion,
                "calidad_dato": r.calidad_dato,
                "recibido_en": _as_utc(r.recibido_en).isoformat(),
            }
            for r in readings
        ]

    buckets: dict[datetime, list[LecturaTelemetria]] = defaultdict(list)
    for r in readings:
        ts = _as_utc(r.recibido_en)
        if granularity == "minute":
            key = ts.replace(second=0, microsecond=0)
        else:
            key = ts.replace(minute=0, second=0, microsecond=0)
        buckets[key].append(r)

    aggregated: list[dict[str, Any]] = []
    for bucket_ts in sorted(buckets.keys()):
        group = buckets[bucket_ts]
        n = len(group)
        aggregated.append(
            {
                "id": group[-1].id,
                "dispositivo_id": group[-1].dispositivo_id,
                "ph": round(sum(float(x.ph) for x in group) / n, 2),
                "temperatura_c": round(sum(float(x.temperatura_c) for x in group) / n, 2),
                "tds_ppm": round(sum(float(x.tds_ppm) for x in group) / n, 2),
                "ec_ppm": round(sum(float(x.ec_ppm) for x in group) / n, 2),
                "salinidad_ppm": round(sum(float(x.salinidad_ppm) for x in group) / n, 2),
                "actuador_estado": any(x.actuador_estado for x in group),
                "modo_operacion": group[-1].modo_operacion,
                "calidad_dato": "SOSPECHOSA" if any(x.calidad_dato == "SOSPECHOSA" for x in group) else "VALIDA",
                "recibido_en": bucket_ts.isoformat(),
                "muestras": n,
            }
        )
    return aggregated


def compute_descriptive_analytics(
    db: Session,
    device: Dispositivo,
    start_dt: datetime,
    end_dt: datetime,
) -> AnalyticsSummaryOut:
    """Genera resumen estadístico, índice de salud, franjas de violación e histogramas."""
    readings = list(
        db.scalars(
            select(LecturaTelemetria)
            .where(
                LecturaTelemetria.dispositivo_id == device.id,
                LecturaTelemetria.recibido_en >= start_dt,
                LecturaTelemetria.recibido_en <= end_dt,
            )
            .order_by(LecturaTelemetria.recibido_en.asc())
        )
    )
    umbrales = {
        u.parametro: u
        for u in db.scalars(
            select(UmbralParametro).where(UmbralParametro.estanque_id == device.estanque_id)
        )
    }
    events = list(
        db.scalars(
            select(EventoComunicacion)
            .where(EventoComunicacion.dispositivo_id == device.id)
            .order_by(EventoComunicacion.registrado_en.asc())
        )
    )

    total = len(readings)
    validas = sum(1 for r in readings if r.calidad_dato == "VALIDA")
    sospechosas = total - validas
    violaciones_franja = {"manana": 0, "tarde": 0, "noche": 0}
    param_stats: list[ParameterStats] = []

    for param, field_name in PARAM_FIELD_MAP.items():
        u = umbrales.get(param)
        min_opt = float(u.min_optimo) if u else 0.0
        max_opt = float(u.max_optimo) if u else 100.0
        unidad = u.unidad if u else ""
        values = [float(getattr(r, field_name)) for r in readings]

        if not values:
            param_stats.append(
                ParameterStats(
                    parametro=param,
                    unidad=unidad,
                    count=0,
                    promedio=0.0,
                    mediana=0.0,
                    minimo=0.0,
                    maximo=0.0,
                    desviacion_std=0.0,
                    tasa_variacion=0.0,
                    cumplimiento_pct=100.0,
                    violaciones=0,
                    min_optimo=min_opt,
                    max_optimo=max_opt,
                    histograma=[],
                )
            )
            continue

        dentro = 0
        violaciones = 0
        for r, v in zip(readings, values):
            if min_opt <= v <= max_opt:
                dentro += 1
            else:
                violaciones += 1
                violaciones_franja[_time_slot(_as_utc(r.recibido_en))] += 1

        promedio = round(statistics.fmean(values), 2)
        mediana = round(statistics.median(values), 2)
        minimo = round(min(values), 2)
        maximo = round(max(values), 2)
        std_dev = round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0
        base = values[0] if abs(values[0]) > 1e-6 else 1.0
        tasa_var = round(((values[-1] - values[0]) / abs(base)) * 100.0, 2)
        cumplimiento = round((dentro / len(values)) * 100.0, 2)

        param_stats.append(
            ParameterStats(
                parametro=param,
                unidad=unidad,
                count=len(values),
                promedio=promedio,
                mediana=mediana,
                minimo=minimo,
                maximo=maximo,
                desviacion_std=std_dev,
                tasa_variacion=tasa_var,
                cumplimiento_pct=cumplimiento,
                violaciones=violaciones,
                min_optimo=min_opt,
                max_optimo=max_opt,
                histograma=_build_histogram(values, bins=8),
            )
        )

    indice_salud = (
        round(sum(p.cumplimiento_pct for p in param_stats) / len(param_stats), 2)
        if param_stats
        else 100.0
    )
    uptime = compute_uptime_pct(events, device, start_dt, end_dt)

    return AnalyticsSummaryOut(
        rango_inicio=start_dt,
        rango_fin=end_dt,
        total_lecturas=total,
        lecturas_validas=validas,
        lecturas_sospechosas=sospechosas,
        indice_salud_pct=indice_salud,
        uptime_pct=uptime,
        parametros=param_stats,
        violaciones_por_franja=violaciones_franja,
    )
