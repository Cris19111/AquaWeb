import type {
  AlertItem,
  AnalyticsSummary,
  CommEvent,
  ControlCommand,
  OverviewResponse,
  ParameterKey,
  ParameterStats,
  RejectedMessage,
  TelemetryReading,
  Threshold,
} from "../types";

export const PARAM_META: Record<
  ParameterKey,
  { label: string; field: keyof TelemetryReading; unit: string; color: string }
> = {
  ph: { label: "pH", field: "ph", unit: "pH", color: "#0284c7" },
  temperatura: { label: "Temperatura", field: "temperatura_c", unit: "°C", color: "#ea580c" },
  tds: { label: "TDS", field: "tds_ppm", unit: "ppm", color: "#7c3aed" },
  ec: { label: "Conductividad (EC)", field: "ec_ppm", unit: "ppm", color: "#0d9488" },
  salinidad: { label: "Salinidad", field: "salinidad_ppm", unit: "ppm", color: "#2563eb" },
};

const initialThresholds: Threshold[] = [
  { id: 1, estanque_id: 1, parametro: "ph", min_optimo: 6.5, max_optimo: 9.5, min_fisico: 0, max_fisico: 14, unidad: "pH", actualizado_en: new Date().toISOString() },
  { id: 2, estanque_id: 1, parametro: "temperatura", min_optimo: 20, max_optimo: 30, min_fisico: -5, max_fisico: 60, unidad: "°C", actualizado_en: new Date().toISOString() },
  { id: 3, estanque_id: 1, parametro: "tds", min_optimo: 4000, max_optimo: 15000, min_fisico: 0, max_fisico: 50000, unidad: "ppm", actualizado_en: new Date().toISOString() },
  { id: 4, estanque_id: 1, parametro: "ec", min_optimo: 10000, max_optimo: 35000, min_fisico: 0, max_fisico: 80000, unidad: "ppm", actualizado_en: new Date().toISOString() },
  { id: 5, estanque_id: 1, parametro: "salinidad", min_optimo: 5000, max_optimo: 23000, min_fisico: 0, max_fisico: 50000, unidad: "ppm", actualizado_en: new Date().toISOString() },
];

function buildInitialReadings(): TelemetryReading[] {
  const now = Date.now();
  const totalPoints = 336; // 7 días cada 30 min
  const list: TelemetryReading[] = [];
  for (let i = 0; i < totalPoints; i++) {
    const ts = new Date(now - (totalPoints - 1 - i) * 30 * 60 * 1000);
    const dayPhase = ((ts.getHours() + ts.getMinutes() / 60) / 24) * Math.PI * 2;
    const multiDay = (i / 144) * Math.PI * 2;

    let ph = 7.85 + 0.55 * Math.sin(dayPhase - 1.2) + ((i % 7) - 3) * 0.04;
    if (i >= 92 && i <= 96) ph += 1.4;
    if (i >= 240 && i <= 244) ph -= 1.55;

    let temp = 27.3 + 2.05 * Math.sin(dayPhase - 1.8) + ((i % 5) - 2) * 0.08;
    if (i >= 148 && i <= 152) temp += 1.75;

    const ec = 21800 + 3200 * Math.sin(multiDay) + ((i % 11) - 5) * 185;
    const tds = ec * 0.48;
    const salinidad = ec * 0.65;
    const actuador = ph < 6.5 || ph > 9.5 || temp < 20 || temp > 30;

    list.push({
      id: i + 1,
      dispositivo_id: 1,
      ph: Number(ph.toFixed(2)),
      temperatura_c: Number(temp.toFixed(2)),
      tds_ppm: Number(tds.toFixed(1)),
      ec_ppm: Number(ec.toFixed(1)),
      salinidad_ppm: Number(salinidad.toFixed(1)),
      actuador_estado: actuador,
      modo_operacion: "AUTO",
      calidad_dato: i === 180 || i === 181 ? "SOSPECHOSA" : "VALIDA",
      recibido_en: ts.toISOString(),
    });
  }
  return list;
}

class DemoStore {
  thresholds: Threshold[] = initialThresholds.map((t) => ({ ...t }));
  readings: TelemetryReading[] = buildInitialReadings();
  modo: "AUTO" | "MANUAL" = "AUTO";
  actuador = false;
  estadoConexion: "ONLINE" | "SIN_DATOS" | "OFFLINE" = "ONLINE";

  alerts: AlertItem[] = [
    {
      id: 101,
      dispositivo_id: 1,
      lectura_id: 181,
      parametro: "sensor_congelado",
      valor_detectado: 7.85,
      umbral_infringido: "mantenimiento_sensor",
      severidad: "ADVERTENCIA",
      mensaje: "Posible sensor congelado en 2 ciclos consecutivos; verificar sonda de pH.",
      estado: "ACTIVA",
      creada_en: new Date(Date.now() - 4 * 3600 * 1000).toISOString(),
      resuelta_en: null,
    },
    {
      id: 102,
      dispositivo_id: 1,
      lectura_id: 242,
      parametro: "ph",
      valor_detectado: 6.18,
      umbral_infringido: "< 6.50 pH",
      severidad: "ADVERTENCIA",
      mensaje: "pH por debajo del rango óptimo en madrugada; aireador activado.",
      estado: "RECONOCIDA",
      creada_en: new Date(Date.now() - 28 * 3600 * 1000).toISOString(),
      resuelta_en: null,
    },
    {
      id: 103,
      dispositivo_id: 1,
      lectura_id: 150,
      parametro: "temperatura",
      valor_detectado: 31.18,
      umbral_infringido: "> 30.00 °C",
      severidad: "CRITICA",
      mensaje: "Temperatura superficial superó 30.0 °C en pico vespertino.",
      estado: "RESUELTA",
      creada_en: new Date(Date.now() - 78 * 3600 * 1000).toISOString(),
      resuelta_en: new Date(Date.now() - 75 * 3600 * 1000).toISOString(),
    },
  ];

  events: CommEvent[] = [
    { id: 5, dispositivo_id: 1, estado_anterior: "OFFLINE", estado_nuevo: "ONLINE", gravedad: "INFO", detalle: "Nodo ESP32 reconectado tras backoff exponencial.", registrado_en: new Date(Date.now() - 46 * 3600 * 1000).toISOString() },
    { id: 4, dispositivo_id: 1, estado_anterior: "ONLINE", estado_nuevo: "OFFLINE", gravedad: "CRITICAL", detalle: "Desconexión abrupta detectada vía Last Will (LWT).", registrado_en: new Date(Date.now() - 47 * 3600 * 1000).toISOString() },
    { id: 3, dispositivo_id: 1, estado_anterior: "SIN_DATOS", estado_nuevo: "ONLINE", gravedad: "INFO", detalle: "Telemetría reanudada correctamente.", registrado_en: new Date(Date.now() - 101 * 3600 * 1000).toISOString() },
    { id: 2, dispositivo_id: 1, estado_anterior: "ONLINE", estado_nuevo: "SIN_DATOS", gravedad: "WARNING", detalle: "Sin telemetría durante 21.4 s (umbral 15 s).", registrado_en: new Date(Date.now() - 102 * 3600 * 1000).toISOString() },
    { id: 1, dispositivo_id: 1, estado_anterior: "INICIAL", estado_nuevo: "ONLINE", gravedad: "INFO", detalle: "Conexión inicial ESP32 en broker.hivemq.com.", registrado_en: new Date(Date.now() - 168 * 3600 * 1000).toISOString() },
  ];

  commands: ControlCommand[] = [
    {
      id: 1,
      dispositivo_id: 1,
      command_id: "11111111-1111-4111-8111-111111111111",
      tipo_orden: "ACTUALIZAR_UMBRALES",
      payload_json: { parametro: "ph", min_optimo: 6.5, max_optimo: 9.5 },
      estado: "APLICADA",
      detalle_respuesta: "Umbrales sincronizados con el nodo ESP32.",
      creada_en: new Date(Date.now() - 24 * 3600 * 1000).toISOString(),
      actualizada_en: new Date(Date.now() - 24 * 3600 * 1000 + 2000).toISOString(),
    },
    {
      id: 2,
      dispositivo_id: 1,
      command_id: "22222222-2222-4222-8222-222222222222",
      tipo_orden: "CONTROL_ACTUADOR",
      payload_json: { modo: "MANUAL", actuador: 1 },
      estado: "EXPIRADA",
      detalle_respuesta: "Sin confirmación en ordenes_ack tras 15 s durante microcorte.",
      creada_en: new Date(Date.now() - 47 * 3600 * 1000).toISOString(),
      actualizada_en: new Date(Date.now() - 47 * 3600 * 1000 + 15000).toISOString(),
    },
  ];

  rejectedMessages: RejectedMessage[] = [
    {
      id: 1,
      topico: "utp/ds8/grupo/aquaweb/estanque-01/telemetria",
      payload_crudo: '{"ph": 19.8, "temperatura_c": 27.1, "tds_ppm": 10200, "ec_ppm": 21200, "salinidad_ppm": 13780}',
      motivo_rechazo: "'ph' fuera de rango físico [0.0, 14.0]: 19.8.",
      recibido_en: new Date(Date.now() - 18 * 3600 * 1000).toISOString(),
    },
    {
      id: 2,
      topico: "utp/ds8/grupo/aquaweb/estanque-01/telemetria",
      payload_crudo: "{ph: 7.5, temperatura_c: NaN",
      motivo_rechazo: "JSON corrupto o con NaN/Infinity.",
      recibido_en: new Date(Date.now() - 9 * 3600 * 1000).toISOString(),
    },
  ];

  getOverview(): OverviewResponse {
    const latest = this.readings[this.readings.length - 1];
    const prev = this.readings[this.readings.length - 2];
    return {
      estanque: {
        id: 1,
        nombre: "Estanque Camaronero #1 - Aguadulce",
        ubicacion: "Aguadulce, Coclé, Panamá",
        especie: "Litopenaeus vannamei",
        volumen_m3: 4500,
      },
      dispositivo: {
        id: 1,
        estanque_id: 1,
        client_id_mqtt: "estanque-01",
        nombre: "Nodo ESP32 Estanque #1 (Demo)",
        estado_conexion: this.estadoConexion,
        modo_operacion: this.modo,
        actuador_activo: this.actuador,
        intervalo_pub_seg: 5,
        ultimo_latido: latest?.recibido_en ?? null,
      },
      ultima_lectura: latest,
      lectura_anterior: prev,
      sparkline: this.readings.slice(-20),
      umbrales: this.thresholds,
      alertas_activas: this.alerts.filter((a) => a.estado !== "RESUELTA").length,
      buffer_pendiente: 0,
      mqtt_conectado: true,
    };
  }

  getFilteredReadings(range: string, aggregation: "raw" | "minute" | "hour", start?: string, end?: string): TelemetryReading[] {
    const now = Date.now();
    const mapMs: Record<string, number> = {
      "1h": 3600 * 1000,
      "6h": 6 * 3600 * 1000,
      "24h": 24 * 3600 * 1000,
      "7d": 7 * 24 * 3600 * 1000,
      "30d": 30 * 24 * 3600 * 1000,
    };
    const startMs = start ? new Date(start).getTime() : now - (mapMs[range] ?? 24 * 3600 * 1000);
    const endMs = end ? new Date(end).getTime() : now;

    const filtered = this.readings.filter((r) => {
      const t = new Date(r.recibido_en).getTime();
      return t >= startMs && t <= endMs;
    });

    if (aggregation === "raw" || filtered.length === 0) return filtered;

    const buckets = new Map<string, TelemetryReading[]>();
    for (const r of filtered) {
      const d = new Date(r.recibido_en);
      if (aggregation === "hour") d.setMinutes(0, 0, 0);
      else d.setSeconds(0, 0);
      const k = d.toISOString();
      const arr = buckets.get(k) || [];
      arr.push(r);
      buckets.set(k, arr);
    }
    return Array.from(buckets.entries()).map(([iso, grp]) => ({
      id: grp[grp.length - 1].id,
      dispositivo_id: 1,
      ph: Number((grp.reduce((a, b) => a + b.ph, 0) / grp.length).toFixed(2)),
      temperatura_c: Number((grp.reduce((a, b) => a + b.temperatura_c, 0) / grp.length).toFixed(2)),
      tds_ppm: Number((grp.reduce((a, b) => a + b.tds_ppm, 0) / grp.length).toFixed(1)),
      ec_ppm: Number((grp.reduce((a, b) => a + b.ec_ppm, 0) / grp.length).toFixed(1)),
      salinidad_ppm: Number((grp.reduce((a, b) => a + b.salinidad_ppm, 0) / grp.length).toFixed(1)),
      actuador_estado: grp.some((x) => x.actuador_estado),
      modo_operacion: grp[grp.length - 1].modo_operacion,
      calidad_dato: grp.some((x) => x.calidad_dato === "SOSPECHOSA") ? "SOSPECHOSA" : "VALIDA",
      recibido_en: iso,
      muestras: grp.length,
    }));
  }

  getAnalytics(range: string, start?: string, end?: string): AnalyticsSummary {
    const list = this.getFilteredReadings(range, "raw", start, end);
    const violacionesFranja = { manana: 0, tarde: 0, noche: 0 };
    const params: ParameterStats[] = (Object.keys(PARAM_META) as ParameterKey[]).map((key) => {
      const meta = PARAM_META[key];
      const thr = this.thresholds.find((t) => t.parametro === key)!;
      const vals = list.map((r) => Number(r[meta.field]));
      if (vals.length === 0) {
        return {
          parametro: key,
          unidad: thr.unidad,
          count: 0,
          promedio: 0,
          mediana: 0,
          minimo: 0,
          maximo: 0,
          desviacion_std: 0,
          tasa_variacion: 0,
          cumplimiento_pct: 100,
          violaciones: 0,
          min_optimo: thr.min_optimo,
          max_optimo: thr.max_optimo,
          histograma: [],
        };
      }
      const sorted = [...vals].sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      const mediana = sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
      const promedio = vals.reduce((a, b) => a + b, 0) / vals.length;
      const variance = vals.reduce((acc, v) => acc + (v - promedio) ** 2, 0) / vals.length;
      const std = Math.sqrt(variance);
      const minimo = sorted[0];
      const maximo = sorted[sorted.length - 1];
      const base = Math.abs(vals[0]) > 1e-6 ? vals[0] : 1;
      const tasa = ((vals[vals.length - 1] - vals[0]) / Math.abs(base)) * 100;

      let dentro = 0;
      let viol = 0;
      list.forEach((r, idx) => {
        const v = vals[idx];
        if (v >= thr.min_optimo && v <= thr.max_optimo) {
          dentro += 1;
        } else {
          viol += 1;
          const h = new Date(r.recibido_en).getHours();
          if (h >= 6 && h < 12) violacionesFranja.manana += 1;
          else if (h >= 12 && h < 18) violacionesFranja.tarde += 1;
          else violacionesFranja.noche += 1;
        }
      });

      const bins = 8;
      const step = maximo === minimo ? 1 : (maximo - minimo) / bins;
      const counts = Array.from({ length: bins }, () => 0);
      vals.forEach((v) => {
        const bi = Math.min(bins - 1, Math.floor((v - minimo) / step));
        counts[bi] += 1;
      });
      const histograma = counts.map((conteo, bi) => ({
        rango: `${(minimo + bi * step).toFixed(1)}–${(minimo + (bi + 1) * step).toFixed(1)}`,
        desde: Number((minimo + bi * step).toFixed(2)),
        hasta: Number((minimo + (bi + 1) * step).toFixed(2)),
        conteo,
      }));

      return {
        parametro: key,
        unidad: thr.unidad,
        count: vals.length,
        promedio: Number(promedio.toFixed(2)),
        mediana: Number(mediana.toFixed(2)),
        minimo: Number(minimo.toFixed(2)),
        maximo: Number(maximo.toFixed(2)),
        desviacion_std: Number(std.toFixed(2)),
        tasa_variacion: Number(tasa.toFixed(2)),
        cumplimiento_pct: Number(((dentro / vals.length) * 100).toFixed(2)),
        violaciones: viol,
        min_optimo: thr.min_optimo,
        max_optimo: thr.max_optimo,
        histograma,
      };
    });

    const validas = list.filter((r) => r.calidad_dato === "VALIDA").length;
    const indiceSalud = Number(
      (params.reduce((acc, p) => acc + p.cumplimiento_pct, 0) / params.length).toFixed(2)
    );

    return {
      rango_inicio: list[0]?.recibido_en ?? null,
      rango_fin: list[list.length - 1]?.recibido_en ?? null,
      total_lecturas: list.length,
      lecturas_validas: validas,
      lecturas_sospechosas: list.length - validas,
      indice_salud_pct: indiceSalud,
      uptime_pct: 98.81,
      parametros: params,
      violaciones_por_franja: violacionesFranja,
    };
  }
}

export const demoStore = new DemoStore();
