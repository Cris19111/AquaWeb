import { AlertTriangle, Database, Droplets, Gauge, Waves } from "lucide-react";
import { GaugeCard } from "../components/GaugeCard";
import { PARAM_META } from "../lib/demoData";
import type { OverviewResponse, ParameterKey } from "../types";

interface Props {
  overview: OverviewResponse | null;
}

export function OverviewPage({ overview }: Props) {
  if (!overview) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-500">
        Cargando telemetría en tiempo real...
      </div>
    );
  }

  const latest = overview.ultima_lectura;
  const prev = overview.lectura_anterior;
  const params: ParameterKey[] = ["ph", "temperatura", "tds", "ec", "salinidad"];

  return (
    <div className="space-y-6">
      {/* Encabezado del Estanque */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:col-span-2">
          <div className="flex items-center gap-2 text-sky-700">
            <Waves className="h-5 w-5" />
            <h2 className="text-base font-bold text-slate-900">
              {overview.estanque?.nombre || "Estanque Camaronero #1"}
            </h2>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {overview.estanque?.ubicacion || "Panamá"} · Especie:{" "}
            <span className="font-medium italic text-slate-700">
              {overview.estanque?.especie || "Litopenaeus vannamei"}
            </span>{" "}
            · Volumen: {overview.estanque?.volumen_m3?.toLocaleString("es-PA") || "4,500"} m³
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-slate-500">Alertas Activas</span>
            <AlertTriangle className={`h-4 w-4 ${overview.alertas_activas > 0 ? "text-amber-500" : "text-emerald-500"}`} />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">{overview.alertas_activas}</p>
          <p className="text-xs text-slate-500">Reglas determinísticas + salud sensor</p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-slate-500">Calidad / Buffer</span>
            <Database className="h-4 w-4 text-sky-600" />
          </div>
          <p className="mt-2 text-lg font-bold text-slate-900">
            {latest?.calidad_dato || "SIN LECTURA"}
          </p>
          <p className="text-xs text-slate-500">
            Pendientes en buffer local: {overview.buffer_pendiente}
          </p>
        </div>
      </div>

      {/* 5 Tarjetas KPI + Gauges + Sparklines */}
      {latest ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {params.map((key) => {
            const meta = PARAM_META[key];
            const thr = overview.umbrales.find((u) => u.parametro === key);
            const val = Number(latest[meta.field]);
            const prevVal = prev ? Number(prev[meta.field]) : undefined;
            const spark = overview.sparkline.map((r) => ({ v: Number(r[meta.field]) }));

            return (
              <GaugeCard
                key={key}
                label={meta.label}
                unit={thr?.unidad || meta.unit}
                value={val}
                prevValue={prevVal}
                minOptimal={thr?.min_optimo ?? 0}
                maxOptimal={thr?.max_optimo ?? 100}
                minPhysical={thr?.min_fisico ?? 0}
                maxPhysical={thr?.max_fisico ?? 100}
                color={meta.color}
                sparkline={spark}
              />
            );
          })}

          {/* Tarjeta resumen de actuador */}
          <div className="flex flex-col justify-between rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-sky-950 p-5 text-white shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-sky-300">
                Estado Operativo del Nodo
              </span>
              <Gauge className="h-5 w-5 text-sky-300" />
            </div>
            <div className="my-4 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-300">Dispositivo MQTT</span>
                <span className="font-mono font-semibold">{overview.dispositivo.client_id_mqtt}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-300">Modo de Operación</span>
                <span className="rounded-md bg-white/10 px-2 py-0.5 font-semibold">
                  {overview.dispositivo.modo_operacion}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-300">Bomba / Aireador</span>
                <span
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-semibold ${
                    overview.dispositivo.actuador_activo
                      ? "bg-emerald-500/20 text-emerald-300"
                      : "bg-slate-700 text-slate-300"
                  }`}
                >
                  <Droplets className="h-3.5 w-3.5" />
                  {overview.dispositivo.actuador_activo ? "ENCENDIDO" : "APAGADO"}
                </span>
              </div>
            </div>
            <p className="text-xs text-slate-400">
              Intervalo de muestreo: cada {overview.dispositivo.intervalo_pub_seg} s · Enfoque determinístico (sin IA/ML).
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          Aún no se han recibido lecturas de telemetría para este dispositivo.
        </div>
      )}
    </div>
  );
}
