import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchAnalytics } from "../lib/api";
import { PARAM_META } from "../lib/demoData";
import type { AnalyticsSummary, ParameterKey, ServerConfig } from "../types";

interface Props {
  config: ServerConfig;
  onDemoFallback: (used: boolean) => void;
}

export function AnalyticsPage({ config, onDemoFallback }: Props) {
  const [range, setRange] = useState("7d");
  const [histParam, setHistParam] = useState<ParameterKey>("ph");
  const [data, setData] = useState<AnalyticsSummary | null>(null);

  useEffect(() => {
    let active = true;
    fetchAnalytics(config, range).then((res) => {
      if (!active) return;
      setData(res.data);
      onDemoFallback(res.usedDemo);
    });
    return () => {
      active = false;
    };
  }, [config, range, onDemoFallback]);

  if (!data) {
    return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-500">Calculando analítica descriptiva...</div>;
  }

  const slotChart = [
    { franja: "Mañana (06–12h)", violaciones: data.violaciones_por_franja.manana },
    { franja: "Tarde (12–18h)", violaciones: data.violaciones_por_franja.tarde },
    { franja: "Noche (18–06h)", violaciones: data.violaciones_por_franja.noche },
  ];

  const selectedHist = data.parametros.find((p) => p.parametro === histParam);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Analítica Descriptiva y Estadística (Sin IA)</h2>
          <p className="text-xs text-slate-500">
            Estadísticos reales del periodo seleccionado: cumplimiento de umbrales, dispersión y distribución de frecuencias.
          </p>
        </div>
        <div className="flex gap-1.5">
          {["24h", "7d", "30d"].map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                range === r ? "bg-sky-600 text-white" : "bg-white text-slate-600 border border-slate-200"
              }`}
            >
              Últimos {r}
            </button>
          ))}
        </div>
      </div>

      {/* KPIs de Cumplimiento e Índice de Salud */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase text-slate-500">Índice de Salud del Estanque</p>
          <p className="mt-2 text-3xl font-bold text-emerald-600">{data.indice_salud_pct}%</p>
          <p className="text-xs text-slate-500">Promedio de tiempo en rango óptimo</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase text-slate-500">Disponibilidad (Uptime)</p>
          <p className="mt-2 text-3xl font-bold text-sky-600">{data.uptime_pct}%</p>
          <p className="text-xs text-slate-500">Tiempo en estado ONLINE</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase text-slate-500">Lecturas Válidas</p>
          <p className="mt-2 text-3xl font-bold text-slate-900">{data.lecturas_validas}</p>
          <p className="text-xs text-slate-500">De {data.total_lecturas} totales</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase text-slate-500">Lecturas Sospechosas</p>
          <p className="mt-2 text-3xl font-bold text-amber-600">{data.lecturas_sospechosas}</p>
          <p className="text-xs text-slate-500">Sensor congelado o salto abrupto</p>
        </div>
      </div>

      {/* Tabla Estadística Completa */}
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Parámetro</th>
              <th className="px-4 py-3">Promedio</th>
              <th className="px-4 py-3">Mediana</th>
              <th className="px-4 py-3">Mínimo</th>
              <th className="px-4 py-3">Máximo</th>
              <th className="px-4 py-3">Desv. Est.</th>
              <th className="px-4 py-3">Variación %</th>
              <th className="px-4 py-3">Cumplimiento</th>
              <th className="px-4 py-3">Violaciones</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.parametros.map((p) => (
              <tr key={p.parametro} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-semibold text-slate-900">
                  {PARAM_META[p.parametro].label}{" "}
                  <span className="text-xs font-normal text-slate-500">({p.unidad})</span>
                </td>
                <td className="px-4 py-3">{p.promedio}</td>
                <td className="px-4 py-3">{p.mediana}</td>
                <td className="px-4 py-3">{p.minimo}</td>
                <td className="px-4 py-3">{p.maximo}</td>
                <td className="px-4 py-3">{p.desviacion_std}</td>
                <td className="px-4 py-3">{p.tasa_variacion > 0 ? `+${p.tasa_variacion}%` : `${p.tasa_variacion}%`}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-200">
                      <div
                        className={`h-full ${p.cumplimiento_pct >= 90 ? "bg-emerald-500" : p.cumplimiento_pct >= 75 ? "bg-amber-500" : "bg-rose-500"}`}
                        style={{ width: `${p.cumplimiento_pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold">{p.cumplimiento_pct}%</span>
                  </div>
                </td>
                <td className="px-4 py-3 font-medium text-slate-700">{p.violaciones}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Gráficas: Violaciones por Franja + Histograma */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-bold text-slate-900">Violaciones de Umbral por Franja Horaria</h3>
          <p className="mb-4 text-xs text-slate-500">Identifica momentos críticos del día (fotosíntesis / estrés térmico).</p>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={slotChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="franja" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="violaciones" name="Violaciones" fill="#f59e0b" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-base font-bold text-slate-900">Distribución de Frecuencia (Histograma)</h3>
              <p className="text-xs text-slate-500">Concentración de lecturas por rangos de valor.</p>
            </div>
            <select
              value={histParam}
              onChange={(e) => setHistParam(e.target.value as ParameterKey)}
              className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs font-semibold"
            >
              {(Object.keys(PARAM_META) as ParameterKey[]).map((k) => (
                <option key={k} value={k}>
                  {PARAM_META[k].label}
                </option>
              ))}
            </select>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={selectedHist?.histograma || []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="rango" tick={{ fontSize: 10 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="conteo" name="Lecturas" fill={PARAM_META[histParam].color} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
