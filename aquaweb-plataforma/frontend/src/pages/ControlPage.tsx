import { useEffect, useState } from "react";
import { Lock, Power, Save, SlidersHorizontal } from "lucide-react";
import {
  fetchCommands,
  fetchThresholds,
  sendControlCommandApi,
  updateThresholdApi,
} from "../lib/api";
import { PARAM_META } from "../lib/demoData";
import type { ControlCommand, OverviewResponse, ParameterKey, ServerConfig, Threshold } from "../types";

interface Props {
  config: ServerConfig;
  overview: OverviewResponse | null;
  onRefresh: () => void;
  onDemoFallback: (used: boolean) => void;
}

export function ControlPage({ config, overview, onRefresh, onDemoFallback }: Props) {
  const [thresholds, setThresholds] = useState<Threshold[]>([]);
  const [edits, setEdits] = useState<Record<string, { min: string; max: string }>>({});
  const [commands, setCommands] = useState<ControlCommand[]>([]);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    detail: string;
    run: () => Promise<void>;
  } | null>(null);

  const load = () => {
    Promise.all([fetchThresholds(config), fetchCommands(config)]).then(([tRes, cRes]) => {
      setThresholds(tRes.data);
      const map: Record<string, { min: string; max: string }> = {};
      tRes.data.forEach((u) => {
        map[u.parametro] = { min: String(u.min_optimo), max: String(u.max_optimo) };
      });
      setEdits(map);
      setCommands(cRes.data);
      onDemoFallback(tRes.usedDemo || cRes.usedDemo);
    });
  };

  useEffect(() => {
    load();
  }, [config]);

  const askAndRun = (title: string, detail: string, run: () => Promise<void>) => {
    setConfirmAction({ title, detail, run });
  };

  const executeConfirmed = async () => {
    if (!confirmAction) return;
    const fn = confirmAction.run;
    setConfirmAction(null);
    setFeedback(null);
    try {
      await fn();
      load();
      onRefresh();
    } catch (err) {
      setFeedback({ type: "err", text: err instanceof Error ? err.message : "Error ejecutando orden." });
    }
  };

  const modoActual = overview?.dispositivo.modo_operacion || "AUTO";
  const actuadorActual = Boolean(overview?.dispositivo.actuador_activo);

  return (
    <div className="space-y-6">
      {feedback && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm font-medium ${
            feedback.type === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          {feedback.text}
        </div>
      )}

      {/* Control de Modo y Actuador */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Power className="h-5 w-5 text-sky-600" />
              <h3 className="text-base font-bold text-slate-900">Control Remoto del Actuador (MQTT)</h3>
            </div>
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              <Lock className="h-3 w-3" /> Protegido X-API-Key
            </span>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <button
              onClick={() =>
                askAndRun(
                  "Cambiar a modo AUTO",
                  "El ESP32 retomará el control determinístico automático por umbrales.",
                  async () => {
                    await sendControlCommandApi(config, { modo: "AUTO" });
                    setFeedback({ type: "ok", text: "Orden de modo AUTO enviada al broker MQTT." });
                  }
                )
              }
              className={`rounded-xl border px-4 py-3 text-sm font-bold transition ${
                modoActual === "AUTO"
                  ? "border-sky-600 bg-sky-600 text-white"
                  : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
              }`}
            >
              Modo AUTO
            </button>
            <button
              onClick={() =>
                askAndRun(
                  "Cambiar a modo MANUAL",
                  "Permite encender o apagar la bomba/aireador manualmente desde el dashboard.",
                  async () => {
                    await sendControlCommandApi(config, { modo: "MANUAL" });
                    setFeedback({ type: "ok", text: "Orden de modo MANUAL enviada al broker MQTT." });
                  }
                )
              }
              className={`rounded-xl border px-4 py-3 text-sm font-bold transition ${
                modoActual === "MANUAL"
                  ? "border-amber-500 bg-amber-500 text-white"
                  : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
              }`}
            >
              Modo MANUAL
            </button>
          </div>

          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase text-slate-500">Acción Directa Bomba / Aireador</p>
            <div className="mt-3 flex gap-3">
              <button
                onClick={() =>
                  askAndRun(
                    "Encender Actuador (ON)",
                    "Se enviará modo=MANUAL y actuador=ON al dispositivo ESP32.",
                    async () => {
                      await sendControlCommandApi(config, { modo: "MANUAL", actuador: true });
                      setFeedback({ type: "ok", text: "Orden ENCENDER actuador enviada." });
                    }
                  )
                }
                className={`flex-1 rounded-xl px-4 py-2.5 text-sm font-bold text-white transition ${
                  actuadorActual ? "bg-emerald-700" : "bg-emerald-600 hover:bg-emerald-700"
                }`}
              >
                Encender Bomba (ON)
              </button>
              <button
                onClick={() =>
                  askAndRun(
                    "Apagar Actuador (OFF)",
                    "Se enviará modo=MANUAL y actuador=OFF al dispositivo ESP32.",
                    async () => {
                      await sendControlCommandApi(config, { modo: "MANUAL", actuador: false });
                      setFeedback({ type: "ok", text: "Orden APAGAR actuador enviada." });
                    }
                  )
                }
                className="flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-rose-700"
              >
                Apagar Bomba (OFF)
              </button>
            </div>
          </div>
        </div>

        {/* Editor de Umbrales */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-sky-600" />
            <h3 className="text-base font-bold text-slate-900">Umbrales Óptimos del Estanque</h3>
          </div>
          <div className="space-y-3">
            {thresholds.map((t) => (
              <div key={t.parametro} className="grid grid-cols-12 items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 p-2.5 text-xs">
                <div className="col-span-4 font-semibold text-slate-800">
                  {PARAM_META[t.parametro].label} ({t.unidad})
                </div>
                <input
                  type="number"
                  step="any"
                  value={edits[t.parametro]?.min ?? t.min_optimo}
                  onChange={(e) =>
                    setEdits((prev) => ({
                      ...prev,
                      [t.parametro]: { min: e.target.value, max: prev[t.parametro]?.max ?? String(t.max_optimo) },
                    }))
                  }
                  className="col-span-3 rounded-lg border border-slate-300 bg-white px-2 py-1"
                  aria-label={`Min ${t.parametro}`}
                />
                <input
                  type="number"
                  step="any"
                  value={edits[t.parametro]?.max ?? t.max_optimo}
                  onChange={(e) =>
                    setEdits((prev) => ({
                      ...prev,
                      [t.parametro]: { min: prev[t.parametro]?.min ?? String(t.min_optimo), max: e.target.value },
                    }))
                  }
                  className="col-span-3 rounded-lg border border-slate-300 bg-white px-2 py-1"
                  aria-label={`Max ${t.parametro}`}
                />
                <button
                  onClick={() => {
                    const minVal = Number(edits[t.parametro]?.min);
                    const maxVal = Number(edits[t.parametro]?.max);
                    askAndRun(
                      `Actualizar umbral de ${PARAM_META[t.parametro].label}`,
                      `Nuevo rango óptimo: ${minVal} a ${maxVal} ${t.unidad}. Se actualizará PostgreSQL y se enviará al ESP32.`,
                      async () => {
                        await updateThresholdApi(config, {
                          parametro: t.parametro as ParameterKey,
                          min_optimo: minVal,
                          max_optimo: maxVal,
                        });
                        setFeedback({ type: "ok", text: `Umbral de ${t.parametro} guardado y sincronizado.` });
                      }
                    );
                  }}
                  className="col-span-2 inline-flex items-center justify-center rounded-lg bg-sky-600 p-1.5 text-white hover:bg-sky-700"
                  title="Guardar umbral"
                >
                  <Save className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Historial de Órdenes */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-3 text-base font-bold text-slate-900">Historial en Vivo de Órdenes Remotas</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-left uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Fecha</th>
                <th className="px-3 py-2">Command ID</th>
                <th className="px-3 py-2">Tipo</th>
                <th className="px-3 py-2">Payload</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2">Respuesta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {commands.map((c) => (
                <tr key={c.id}>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">
                    {new Date(c.creada_en).toLocaleString("es-PA")}
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-600">{c.command_id.slice(0, 8)}...</td>
                  <td className="px-3 py-2 font-semibold text-slate-800">{c.tipo_orden}</td>
                  <td className="px-3 py-2 font-mono text-slate-600">{JSON.stringify(c.payload_json)}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 font-bold ${
                        c.estado === "APLICADA"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.estado === "ENVIADA"
                          ? "bg-sky-100 text-sky-700"
                          : c.estado === "EXPIRADA"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-rose-100 text-rose-700"
                      }`}
                    >
                      {c.estado}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{c.detalle_respuesta || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal de confirmación */}
      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h4 className="text-base font-bold text-slate-900">{confirmAction.title}</h4>
            <p className="mt-2 text-sm text-slate-600">{confirmAction.detail}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setConfirmAction(null)}
                className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
              >
                Cancelar
              </button>
              <button
                onClick={executeConfirmed}
                className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700"
              >
                Confirmar Envío
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
