import type {
  AlertItem,
  AnalyticsSummary,
  CommEvent,
  ControlCommand,
  OverviewResponse,
  ParameterKey,
  RejectedMessage,
  ServerConfig,
  TelemetryReading,
  Threshold,
} from "../types";
import { demoStore } from "./demoData";

const STORAGE_KEY = "aquaweb_server_config_v1";

export function loadServerConfig(): ServerConfig {
  const defaultUrl = (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000";
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ServerConfig>;
      return {
        apiUrl: parsed.apiUrl || defaultUrl,
        apiKey: parsed.apiKey || "aquaweb-dev-key-2026",
        demoMode: Boolean(parsed.demoMode),
      };
    }
  } catch {
    // ignorar errores de localStorage
  }
  return {
    apiUrl: defaultUrl,
    apiKey: "aquaweb-dev-key-2026",
    demoMode: false,
  };
}

export function saveServerConfig(cfg: ServerConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

export function buildWsUrl(apiUrl: string): string {
  const clean = apiUrl.replace(/\/+$/, "");
  if (clean.startsWith("https://")) return clean.replace("https://", "wss://") + "/ws/live";
  if (clean.startsWith("http://")) return clean.replace("http://", "ws://") + "/ws/live";
  return `ws://${clean}/ws/live`;
}

async function fetchJson<T>(
  cfg: ServerConfig,
  path: string,
  options?: RequestInit
): Promise<T> {
  const base = cfg.apiUrl.replace(/\/+$/, "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3500);
  try {
    const res = await fetch(`${base}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(cfg.apiKey ? { "X-API-Key": cfg.apiKey } : {}),
        ...(options?.headers || {}),
      },
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        if (errBody?.detail) detail = typeof errBody.detail === "string" ? errBody.detail : JSON.stringify(errBody.detail);
      } catch {
        // sin detalle JSON
      }
      throw new Error(detail);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export interface ApiResult<T> {
  data: T;
  usedDemo: boolean;
}

export async function fetchOverview(cfg: ServerConfig): Promise<ApiResult<OverviewResponse>> {
  if (cfg.demoMode) return { data: demoStore.getOverview(), usedDemo: true };
  try {
    const data = await fetchJson<OverviewResponse>(cfg, "/api/overview");
    return { data, usedDemo: false };
  } catch {
    return { data: demoStore.getOverview(), usedDemo: true };
  }
}

export async function fetchTelemetry(
  cfg: ServerConfig,
  range: string,
  aggregation: "raw" | "minute" | "hour",
  start?: string,
  end?: string
): Promise<ApiResult<TelemetryReading[]>> {
  if (cfg.demoMode) {
    return { data: demoStore.getFilteredReadings(range, aggregation, start, end), usedDemo: true };
  }
  const params = new URLSearchParams({ range, aggregation });
  if (start) params.set("start", new Date(start).toISOString());
  if (end) params.set("end", new Date(end).toISOString());
  try {
    const res = await fetchJson<{ items: TelemetryReading[] }>(cfg, `/api/telemetry?${params.toString()}`);
    return { data: res.items, usedDemo: false };
  } catch {
    return { data: demoStore.getFilteredReadings(range, aggregation, start, end), usedDemo: true };
  }
}

export async function fetchAnalytics(
  cfg: ServerConfig,
  range: string,
  start?: string,
  end?: string
): Promise<ApiResult<AnalyticsSummary>> {
  if (cfg.demoMode) {
    return { data: demoStore.getAnalytics(range, start, end), usedDemo: true };
  }
  const params = new URLSearchParams({ range });
  if (start) params.set("start", new Date(start).toISOString());
  if (end) params.set("end", new Date(end).toISOString());
  try {
    const data = await fetchJson<AnalyticsSummary>(cfg, `/api/analytics?${params.toString()}`);
    return { data, usedDemo: false };
  } catch {
    return { data: demoStore.getAnalytics(range, start, end), usedDemo: true };
  }
}

export async function fetchAlerts(cfg: ServerConfig): Promise<ApiResult<AlertItem[]>> {
  if (cfg.demoMode) return { data: [...demoStore.alerts], usedDemo: true };
  try {
    const data = await fetchJson<AlertItem[]>(cfg, "/api/alerts");
    return { data, usedDemo: false };
  } catch {
    return { data: [...demoStore.alerts], usedDemo: true };
  }
}

export async function patchAlertStatus(
  cfg: ServerConfig,
  alertId: number,
  estado: "RECONOCIDA" | "RESUELTA"
): Promise<AlertItem> {
  if (cfg.demoMode) {
    const item = demoStore.alerts.find((a) => a.id === alertId);
    if (!item) throw new Error("Alerta no encontrada.");
    item.estado = estado;
    if (estado === "RESUELTA") item.resuelta_en = new Date().toISOString();
    return { ...item };
  }
  try {
    return await fetchJson<AlertItem>(cfg, `/api/alerts/${alertId}`, {
      method: "PATCH",
      body: JSON.stringify({ estado }),
    });
  } catch {
    const item = demoStore.alerts.find((a) => a.id === alertId);
    if (!item) throw new Error("No se pudo actualizar la alerta.");
    item.estado = estado;
    if (estado === "RESUELTA") item.resuelta_en = new Date().toISOString();
    return { ...item };
  }
}

export async function fetchConnectivity(
  cfg: ServerConfig
): Promise<ApiResult<{ estado_actual: string; uptime_pct: number; events: CommEvent[] }>> {
  if (cfg.demoMode) {
    return {
      data: { estado_actual: demoStore.estadoConexion, uptime_pct: 98.81, events: [...demoStore.events] },
      usedDemo: true,
    };
  }
  try {
    const data = await fetchJson<{ estado_actual: string; uptime_pct: number; events: CommEvent[] }>(
      cfg,
      "/api/connectivity/events"
    );
    return { data, usedDemo: false };
  } catch {
    return {
      data: { estado_actual: demoStore.estadoConexion, uptime_pct: 98.81, events: [...demoStore.events] },
      usedDemo: true,
    };
  }
}

export async function fetchDataQuality(
  cfg: ServerConfig
): Promise<ApiResult<{ lecturas_sospechosas: TelemetryReading[]; mensajes_rechazados: RejectedMessage[] }>> {
  const demoRes = () => ({
    lecturas_sospechosas: demoStore.readings.filter((r) => r.calidad_dato === "SOSPECHOSA"),
    mensajes_rechazados: [...demoStore.rejectedMessages],
  });
  if (cfg.demoMode) return { data: demoRes(), usedDemo: true };
  try {
    const data = await fetchJson<{
      lecturas_sospechosas: TelemetryReading[];
      mensajes_rechazados: RejectedMessage[];
    }>(cfg, "/api/data-quality");
    return { data, usedDemo: false };
  } catch {
    return { data: demoRes(), usedDemo: true };
  }
}

export async function fetchThresholds(cfg: ServerConfig): Promise<ApiResult<Threshold[]>> {
  if (cfg.demoMode) return { data: [...demoStore.thresholds], usedDemo: true };
  try {
    const data = await fetchJson<Threshold[]>(cfg, "/api/thresholds");
    return { data, usedDemo: false };
  } catch {
    return { data: [...demoStore.thresholds], usedDemo: true };
  }
}

export async function updateThresholdApi(
  cfg: ServerConfig,
  payload: { parametro: ParameterKey; min_optimo: number; max_optimo: number }
): Promise<Threshold> {
  if (payload.min_optimo >= payload.max_optimo) {
    throw new Error("El umbral mínimo debe ser estrictamente menor que el máximo.");
  }
  if (cfg.demoMode) {
    const item = demoStore.thresholds.find((t) => t.parametro === payload.parametro);
    if (!item) throw new Error("Parámetro no encontrado.");
    if (payload.min_optimo < item.min_fisico || payload.max_optimo > item.max_fisico) {
      throw new Error(`Rango físico permitido: [${item.min_fisico}, ${item.max_fisico}].`);
    }
    item.min_optimo = payload.min_optimo;
    item.max_optimo = payload.max_optimo;
    item.actualizado_en = new Date().toISOString();
    demoStore.commands.unshift({
      id: Date.now(),
      dispositivo_id: 1,
      command_id: crypto.randomUUID(),
      tipo_orden: "ACTUALIZAR_UMBRALES",
      payload_json: payload,
      estado: "APLICADA",
      detalle_respuesta: "Umbral actualizado en Modo Demo.",
      creada_en: new Date().toISOString(),
      actualizada_en: new Date().toISOString(),
    });
    return { ...item };
  }
  return await fetchJson<Threshold>(cfg, "/api/thresholds", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function fetchCommands(cfg: ServerConfig): Promise<ApiResult<ControlCommand[]>> {
  if (cfg.demoMode) return { data: [...demoStore.commands], usedDemo: true };
  try {
    const data = await fetchJson<ControlCommand[]>(cfg, "/api/commands");
    return { data, usedDemo: false };
  } catch {
    return { data: [...demoStore.commands], usedDemo: true };
  }
}

export async function sendControlCommandApi(
  cfg: ServerConfig,
  payload: { modo?: "AUTO" | "MANUAL"; actuador?: boolean }
): Promise<ControlCommand> {
  if (cfg.demoMode) {
    if (payload.modo) demoStore.modo = payload.modo;
    if (payload.actuador !== undefined) demoStore.actuador = payload.actuador;
    const cmd: ControlCommand = {
      id: Date.now(),
      dispositivo_id: 1,
      command_id: crypto.randomUUID(),
      tipo_orden: payload.actuador !== undefined ? "CONTROL_ACTUADOR" : "CAMBIO_MODO",
      payload_json: payload,
      estado: "APLICADA",
      detalle_respuesta: "Orden confirmada localmente (Modo Demo).",
      creada_en: new Date().toISOString(),
      actualizada_en: new Date().toISOString(),
    };
    demoStore.commands.unshift(cmd);
    return cmd;
  }
  return await fetchJson<ControlCommand>(cfg, "/api/commands", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
