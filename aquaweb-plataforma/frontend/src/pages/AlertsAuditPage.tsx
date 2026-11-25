import { useEffect, useState } from "react";
import { CheckCircle2, Eye, ShieldAlert, Wifi } from "lucide-react";
import { fetchAlerts, fetchConnectivity, fetchDataQuality, patchAlertStatus } from "../lib/api";
import type { AlertItem, CommEvent, RejectedMessage, ServerConfig, TelemetryReading } from "../types";

interface Props {
  config: ServerConfig;
  onDemoFallback: (used: boolean) => void;
}

export function AlertsAuditPage({ config, onDemoFallback }: Props) {
  const [tab, setTab] = useState<"alertas" | "conectividad" | "calidad">("alertas");
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [filterEstado, setFilterEstado] = useState<string>("TODOS");
  const [filterSev, setFilterSev] = useState<string>("TODOS");
  const [filterParam, setFilterParam] = useState<string>("TODOS");

  const [connData, setConnData] = useState<{ estado_actual: string; uptime_pct: number; events: CommEvent[] }>({
    estado_actual: "ONLINE",
    uptime_pct: 100,
    events: [],
  });
  const [quality, setQuality] = useState<{
    lecturas_sospechosas: TelemetryReading[];
    mensajes_rechazados: RejectedMessage[];
  }>({ lecturas_sospechosas: [], mensajes_rechazados: [] });

  const loadAll = () => {
    Promise.all([fetchAlerts(config), fetchConnectivity(config), fetchDataQuality(config)]).then(
      ([aRes, cRes, qRes]) => {
        setAlerts(aRes.data);
        setConnData(cRes.data);
        setQuality(qRes.data);
        onDemoFallback(aRes.usedDemo || cRes.usedDemo || qRes.usedDemo);
      }
    );
  };

  useEffect(() => {
    loadAll();
  }, [config]);

  const handleAction = async (id: number, estado: "RECONOCIDA" | "RESUELTA") => {
    await patchAlertStatus(config, id, estado);
    loadAll();
  };

  const filteredAlerts = alerts.filter((a) => {
    if (filterEstado !== "TODOS" && a.estado !== filterEstado) return false;
    if (filterSev !== "TODOS" && a.severidad !== filterSev) return false;
    if (filterParam !== "TODOS" && a.parametro !== filterParam) return false;
    return true;
  });

  const uniqueParams = Array.from(new Set(alerts.map((a) => a.parametro)));

  return (
    <div className="space-y-5">
      {/* Selector de pestañas */}
      <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        <button
          onClick={() => setTab("alertas")}
          className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold ${
            tab === "alertas" ? "bg-sky-600 text-white" : "bg-white text-slate-600 border border-slate-200"
          }`}
        >
          <ShieldAlert className="h-4 w-4" /> Alertas ({alerts.filter((a) => a.estado !== "RESUELTA").length} activas)
        </button>
        <button
          onClick={() => setTab("conectividad")}
          className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold ${
            tab === "conectividad" ? "bg-sky-600 text-white" : "bg-white text-slate-600 border border-slate-200"
          }`}
        >
          <Wifi className="h-4 w-4" /> Conectividad ({connData.uptime_pct}% Uptime)
        </button>
        <button
          onClick={() => setTab("calidad")}
          className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold ${
            tab === "calidad" ? "bg-sky-600 text-white" : "bg-white text-slate-600 border border-slate-200"
          }`}
        >
          Calidad de Datos / Rechazados ({quality.mensajes_rechazados.length})
        </button>
      </div>

      {/* Pestaña 1: Alertas */}
      {tab === "alertas" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3">
            <select value={filterEstado} onChange={(e) => setFilterEstado(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs">
              <option value="TODOS">Estado: Todos</option>
              <option value="ACTIVA">ACTIVA</option>
              <option value="RECONOCIDA">RECONOCIDA</option>
              <option value="RESUELTA">RESUELTA</option>
            </select>
            <select value={filterSev} onChange={(e) => setFilterSev(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs">
              <option value="TODOS">Severidad: Todas</option>
              <option value="CRITICA">CRÍTICA</option>
              <option value="ADVERTENCIA">ADVERTENCIA</option>
            </select>
            <select value={filterParam} onChange={(e) => setFilterParam(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs">
              <option value="TODOS">Parámetro: Todos</option>
              {uniqueParams.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div className="space-y-3">
            {filteredAlerts.map((a) => (
              <div key={a.id} className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${a.severidad === "CRITICA" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                      {a.severidad}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                      {a.parametro}
                    </span>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      a.estado === "ACTIVA" ? "bg-rose-50 text-rose-600" : a.estado === "RECONOCIDA" ? "bg-sky-50 text-sky-700" : "bg-emerald-50 text-emerald-700"
                    }`}>
                      {a.estado}
                    </span>
                    <span className="text-xs text-slate-400">
                      {new Date(a.creada_en).toLocaleString("es-PA")}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-slate-800">{a.mensaje}</p>
                  <p className="text-xs text-slate-500">
                    Valor detectado: {a.valor_detectado ?? "—"} · Regla: {a.umbral_infringido}
                  </p>
                </div>

                {a.estado !== "RESUELTA" && (
                  <div className="flex gap-2">
                    {a.estado === "ACTIVA" && (
                      <button
                        onClick={() => handleAction(a.id, "RECONOCIDA")}
                        className="inline-flex items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100"
                      >
                        <Eye className="h-3.5 w-3.5" /> Reconocer
                      </button>
                    )}
                    <button
                      onClick={() => handleAction(a.id, "RESUELTA")}
                      className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" /> Resolver
                    </button>
                  </div>
                )}
              </div>
            ))}
            {filteredAlerts.length === 0 && (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
                No hay alertas para los filtros seleccionados.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Pestaña 2: Conectividad */}
      {tab === "conectividad" && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase text-slate-500">Estado Actual</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{connData.estado_actual}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase text-slate-500">Disponibilidad (Últimos 7 días)</p>
              <p className="mt-1 text-2xl font-bold text-emerald-600">{connData.uptime_pct}%</p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-4 text-sm font-bold uppercase text-slate-600">Línea de Tiempo de Transiciones</h3>
            <ol className="relative space-y-4 border-l-2 border-slate-200 pl-5">
              {connData.events.map((ev) => (
                <li key={ev.id} className="relative">
                  <span
                    className={`absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-white ${
                      ev.estado_nuevo === "ONLINE"
                        ? "bg-emerald-500"
                        : ev.estado_nuevo === "SIN_DATOS"
                        ? "bg-amber-500"
                        : "bg-rose-500"
                    }`}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold text-slate-900">
                      {ev.estado_anterior} → {ev.estado_nuevo}
                    </span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                      {ev.gravedad}
                    </span>
                    <span className="text-xs text-slate-400">
                      {new Date(ev.registrado_en).toLocaleString("es-PA")}
                    </span>
                  </div>
                  <p className="mt-0.5 text-sm text-slate-600">{ev.detalle}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {/* Pestaña 3: Calidad de datos y auditoría forense */}
      {tab === "calidad" && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-base font-bold text-slate-900">
              Mensajes MQTT Descartados (Auditoría Forense — <code>mensajes_rechazados</code>)
            </h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-left uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Fecha</th>
                    <th className="px-3 py-2">Tópico</th>
                    <th className="px-3 py-2">Motivo de Rechazo</th>
                    <th className="px-3 py-2">Payload Crudo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {quality.mensajes_rechazados.map((m) => (
                    <tr key={m.id}>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-500">
                        {new Date(m.recibido_en).toLocaleString("es-PA")}
                      </td>
                      <td className="px-3 py-2 font-mono text-slate-700">{m.topico}</td>
                      <td className="px-3 py-2 font-semibold text-rose-700">{m.motivo_rechazo}</td>
                      <td className="max-w-xs truncate px-3 py-2 font-mono text-slate-600">{m.payload_crudo}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-base font-bold text-slate-900">
              Lecturas Marcadas como <code>SOSPECHOSA</code> (Diagnóstico de Sensores)
            </h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-left uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Fecha</th>
                    <th className="px-3 py-2">pH</th>
                    <th className="px-3 py-2">Temp (°C)</th>
                    <th className="px-3 py-2">TDS (ppm)</th>
                    <th className="px-3 py-2">EC (ppm)</th>
                    <th className="px-3 py-2">Salinidad (ppm)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {quality.lecturas_sospechosas.map((r) => (
                    <tr key={r.id}>
                      <td className="px-3 py-2">{new Date(r.recibido_en).toLocaleString("es-PA")}</td>
                      <td className="px-3 py-2">{r.ph}</td>
                      <td className="px-3 py-2">{r.temperatura_c}</td>
                      <td className="px-3 py-2">{r.tds_ppm}</td>
                      <td className="px-3 py-2">{r.ec_ppm}</td>
                      <td className="px-3 py-2">{r.salinidad_ppm}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
