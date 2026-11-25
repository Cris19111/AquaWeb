import { useEffect, useState } from "react";
import { Download, FileJson } from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchTelemetry, fetchThresholds } from "../lib/api";
import { PARAM_META } from "../lib/demoData";
import { exportDataJSON, exportReadingsCSV } from "../lib/exportUtils";
import type { ParameterKey, ServerConfig, TelemetryReading, Threshold } from "../types";

interface Props {
  config: ServerConfig;
  onDemoFallback: (used: boolean) => void;
}

const RANGES = ["1h", "6h", "24h", "7d", "30d"] as const;

export function HistoryPage({ config, onDemoFallback }: Props) {
  const [range, setRange] = useState<string>("7d");
  const [aggregation, setAggregation] = useState<"raw" | "minute" | "hour">("hour");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [paramPrimary, setParamPrimary] = useState<ParameterKey>("ph");
  const [compareLeft, setCompareLeft] = useState<ParameterKey>("temperatura");
  const [compareRight, setCompareRight] = useState<ParameterKey>("ph");

  const [readings, setReadings] = useState<TelemetryReading[]>([]);
  const [thresholds, setThresholds] = useState<Threshold[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      fetchTelemetry(config, range, aggregation, customStart || undefined, customEnd || undefined),
      fetchThresholds(config),
    ]).then(([telRes, thrRes]) => {
      if (!active) return;
      setReadings(telRes.data);
      setThresholds(thrRes.data);
      onDemoFallback(telRes.usedDemo || thrRes.usedDemo);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [config, range, aggregation, customStart, customEnd, onDemoFallback]);

  const chartData = readings.map((r) => ({
    ...r,
    hora: new Date(r.recibido_en).toLocaleString("es-PA", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));

  const activeMeta = PARAM_META[paramPrimary];
  const activeThr = thresholds.find((t) => t.parametro === paramPrimary);

  const leftMeta = PARAM_META[compareLeft];
  const rightMeta = PARAM_META[compareRight];

  return (
    <div className="space-y-6">
      {/* Barra de filtros y exportación */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => {
                  setCustomStart("");
                  setCustomEnd("");
                  setRange(r);
                }}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  range === r && !customStart
                    ? "bg-sky-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {r}
              </button>
            ))}

            <select
              value={aggregation}
              onChange={(e) => setAggregation(e.target.value as "raw" | "minute" | "hour")}
              className="ml-2 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700"
            >
              <option value="raw">Crudo</option>
              <option value="minute">Promedio / min</option>
              <option value="hour">Promedio / hora</option>
            </select>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              type="datetime-local"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
              title="Inicio personalizado"
            />
            <span className="text-xs text-slate-400">a</span>
            <input
              type="datetime-local"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
              title="Fin personalizado"
            />

            <button
              onClick={() => exportReadingsCSV(readings, `aquaweb_${range}_${aggregation}.csv`)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-3.5 w-3.5" /> CSV
            </button>
            <button
              onClick={() => exportDataJSON(readings, `aquaweb_${range}_${aggregation}.json`)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              <FileJson className="h-3.5 w-3.5" /> JSON
            </button>
          </div>
        </div>
      </div>

      {/* Gráfica individual con banda sombreada óptima */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              Serie de Tiempo — {activeMeta.label} ({activeMeta.unit})
            </h3>
            <p className="text-xs text-slate-500">
              Banda verde sombreada indica el rango óptimo configurado (
              {activeThr ? `${activeThr.min_optimo} – ${activeThr.max_optimo} ${activeThr.unidad}` : "—"}).
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(PARAM_META) as ParameterKey[]).map((k) => (
              <button
                key={k}
                onClick={() => setParamPrimary(k)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${
                  paramPrimary === k ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {PARAM_META[k].label}
              </button>
            ))}
          </div>
        </div>

        <div className="h-80 w-full">
          {loading ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">Cargando serie...</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 20, left: 4, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="hora" tick={{ fontSize: 11 }} minTickGap={35} />
                <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip />
                {activeThr && (
                  <ReferenceArea
                    y1={activeThr.min_optimo}
                    y2={activeThr.max_optimo}
                    fill="#10b981"
                    fillOpacity={0.12}
                    strokeOpacity={0.3}
                  />
                )}
                <Line
                  type="monotone"
                  dataKey={activeMeta.field as string}
                  name={`${activeMeta.label} (${activeMeta.unit})`}
                  stroke={activeMeta.color}
                  strokeWidth={2.2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Gráfica comparativa de doble eje */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">Análisis Comparativo de Doble Eje</h3>
            <p className="text-xs text-slate-500">
              Cruza dos variables acuícolas en el mismo periodo (ej. Temperatura vs. pH o EC vs. Salinidad).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="font-semibold text-slate-600">Eje Izq:</label>
            <select
              value={compareLeft}
              onChange={(e) => setCompareLeft(e.target.value as ParameterKey)}
              className="rounded-lg border border-slate-300 px-2.5 py-1"
            >
              {(Object.keys(PARAM_META) as ParameterKey[]).map((k) => (
                <option key={k} value={k}>
                  {PARAM_META[k].label}
                </option>
              ))}
            </select>
            <label className="ml-2 font-semibold text-slate-600">Eje Der:</label>
            <select
              value={compareRight}
              onChange={(e) => setCompareRight(e.target.value as ParameterKey)}
              className="rounded-lg border border-slate-300 px-2.5 py-1"
            >
              {(Object.keys(PARAM_META) as ParameterKey[]).map((k) => (
                <option key={k} value={k}>
                  {PARAM_META[k].label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: 4, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="hora" tick={{ fontSize: 11 }} minTickGap={35} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke={leftMeta.color} domain={["auto", "auto"]} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke={rightMeta.color} domain={["auto", "auto"]} />
              <Tooltip />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey={leftMeta.field as string}
                name={`${leftMeta.label} (${leftMeta.unit})`}
                stroke={leftMeta.color}
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey={rightMeta.field as string}
                name={`${rightMeta.label} (${rightMeta.unit})`}
                stroke={rightMeta.color}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
