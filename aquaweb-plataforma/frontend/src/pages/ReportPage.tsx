import { useEffect, useState } from "react";
import { Download, FileJson, Printer } from "lucide-react";
import { fetchAlerts, fetchAnalytics, fetchTelemetry } from "../lib/api";
import { PARAM_META } from "../lib/demoData";
import { exportDataJSON, exportReadingsCSV } from "../lib/exportUtils";
import type { AlertItem, AnalyticsSummary, OverviewResponse, ServerConfig, TelemetryReading } from "../types";

interface Props {
  config: ServerConfig;
  overview: OverviewResponse | null;
  onDemoFallback: (used: boolean) => void;
}

export function ReportPage({ config, overview, onDemoFallback }: Props) {
  const [range, setRange] = useState("7d");
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [readings, setReadings] = useState<TelemetryReading[]>([]);

  useEffect(() => {
    Promise.all([
      fetchAnalytics(config, range),
      fetchAlerts(config),
      fetchTelemetry(config, range, "hour"),
    ]).then(([an, al, tel]) => {
      setAnalytics(an.data);
      setAlerts(al.data);
      setReadings(tel.data);
      onDemoFallback(an.usedDemo || al.usedDemo || tel.usedDemo);
    });
  }, [config, range, onDemoFallback]);

  return (
    <div className="space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-slate-800">Periodo del Reporte:</span>
          {["24h", "7d", "30d"].map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                range === r ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-600"
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => exportReadingsCSV(readings, `reporte_aquaweb_${range}.csv`)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <Download className="h-4 w-4" /> Exportar CSV
          </button>
          <button
            onClick={() => exportDataJSON({ overview, analytics, alerts }, `reporte_aquaweb_${range}.json`)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <FileJson className="h-4 w-4" /> Exportar JSON
          </button>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800"
          >
            <Printer className="h-4 w-4" /> Imprimir / Guardar PDF
          </button>
        </div>
      </div>

      {/* Documento Imprimible */}
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="border-b-2 border-sky-700 pb-4">
          <p className="text-xs font-bold uppercase tracking-widest text-sky-700">AquaWeb IoT — Reporte Técnico Acuícola</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">
            {overview?.estanque?.nombre || "Estanque Camaronero #1"}
          </h1>
          <p className="mt-1 text-xs text-slate-600">
            Ubicación: {overview?.estanque?.ubicacion || "Panamá"} · Especie: {overview?.estanque?.especie || "Litopenaeus vannamei"} ·
            Generado el {new Date().toLocaleString("es-PA")} · Periodo: Últimos {range}
          </p>
        </div>

        {analytics && (
          <>
            <div className="my-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs text-slate-500">Índice de Salud</p>
                <p className="text-xl font-bold text-emerald-700">{analytics.indice_salud_pct}%</p>
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs text-slate-500">Disponibilidad (Uptime)</p>
                <p className="text-xl font-bold text-sky-700">{analytics.uptime_pct}%</p>
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs text-slate-500">Lecturas Analizadas</p>
                <p className="text-xl font-bold text-slate-900">{analytics.total_lecturas}</p>
              </div>
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs text-slate-500">Alertas Registradas</p>
                <p className="text-xl font-bold text-amber-700">{alerts.length}</p>
              </div>
            </div>

            <h2 className="mb-3 text-base font-bold text-slate-900">1. Resumen Estadístico de Calidad de Agua</h2>
            <table className="mb-6 w-full border-collapse border border-slate-300 text-xs">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="border border-slate-300 px-3 py-2">Parámetro</th>
                  <th className="border border-slate-300 px-3 py-2">Rango Óptimo</th>
                  <th className="border border-slate-300 px-3 py-2">Promedio</th>
                  <th className="border border-slate-300 px-3 py-2">Mediana</th>
                  <th className="border border-slate-300 px-3 py-2">Mín / Máx</th>
                  <th className="border border-slate-300 px-3 py-2">Desv. Est.</th>
                  <th className="border border-slate-300 px-3 py-2">Cumplimiento</th>
                </tr>
              </thead>
              <tbody>
                {analytics.parametros.map((p) => (
                  <tr key={p.parametro}>
                    <td className="border border-slate-300 px-3 py-1.5 font-semibold">
                      {PARAM_META[p.parametro].label} ({p.unidad})
                    </td>
                    <td className="border border-slate-300 px-3 py-1.5">
                      {p.min_optimo} – {p.max_optimo}
                    </td>
                    <td className="border border-slate-300 px-3 py-1.5">{p.promedio}</td>
                    <td className="border border-slate-300 px-3 py-1.5">{p.mediana}</td>
                    <td className="border border-slate-300 px-3 py-1.5">
                      {p.minimo} / {p.maximo}
                    </td>
                    <td className="border border-slate-300 px-3 py-1.5">{p.desviacion_std}</td>
                    <td className="border border-slate-300 px-3 py-1.5 font-semibold">{p.cumplimiento_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h2 className="mb-3 text-base font-bold text-slate-900">2. Resumen de Alertas del Periodo</h2>
            <table className="w-full border-collapse border border-slate-300 text-xs">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="border border-slate-300 px-3 py-2">Fecha</th>
                  <th className="border border-slate-300 px-3 py-2">Parámetro</th>
                  <th className="border border-slate-300 px-3 py-2">Severidad</th>
                  <th className="border border-slate-300 px-3 py-2">Estado</th>
                  <th className="border border-slate-300 px-3 py-2">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {alerts.slice(0, 15).map((a) => (
                  <tr key={a.id}>
                    <td className="border border-slate-300 px-3 py-1.5">
                      {new Date(a.creada_en).toLocaleString("es-PA")}
                    </td>
                    <td className="border border-slate-300 px-3 py-1.5 font-semibold">{a.parametro}</td>
                    <td className="border border-slate-300 px-3 py-1.5">{a.severidad}</td>
                    <td className="border border-slate-300 px-3 py-1.5">{a.estado}</td>
                    <td className="border border-slate-300 px-3 py-1.5">{a.mensaje}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
