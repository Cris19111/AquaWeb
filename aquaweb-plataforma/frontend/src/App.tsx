import { useCallback, useEffect, useState } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Clock,
  FileText,
  Radio,
  Settings,
  ShieldAlert,
  Sliders,
  Waves,
  Wifi,
  WifiOff,
} from "lucide-react";
import { ServerConfigModal } from "./components/ServerConfigModal";
import { buildWsUrl, fetchOverview, loadServerConfig, saveServerConfig } from "./lib/api";
import { AlertsAuditPage } from "./pages/AlertsAuditPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ControlPage } from "./pages/ControlPage";
import { HistoryPage } from "./pages/HistoryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReportPage } from "./pages/ReportPage";
import type { OverviewResponse, ServerConfig } from "./types";

export default function App() {
  const [config, setConfig] = useState<ServerConfig>(() => loadServerConfig());
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [demoFallback, setDemoFallback] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);

  const refreshOverview = useCallback(() => {
    fetchOverview(config).then((res) => {
      setOverview(res.data);
      setDemoFallback(res.usedDemo);
    });
  }, [config]);

  useEffect(() => {
    refreshOverview();
    const poll = setInterval(refreshOverview, 10000);
    return () => clearInterval(poll);
  }, [refreshOverview]);

  // Conexión WebSocket en tiempo real (/ws/live) cuando no está en Modo Demo
  useEffect(() => {
    if (config.demoMode) {
      setWsConnected(false);
      return;
    }
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(buildWsUrl(config.apiUrl));
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
      ws.onmessage = () => {
        refreshOverview();
      };
    } catch {
      setWsConnected(false);
    }
    return () => {
      ws?.close();
    };
  }, [config.apiUrl, config.demoMode, refreshOverview]);

  const handleSaveConfig = (next: ServerConfig) => {
    saveServerConfig(next);
    setConfig(next);
  };

  const toggleDemoQuick = () => {
    handleSaveConfig({ ...config, demoMode: !config.demoMode });
  };

  const deviceStatus = overview?.dispositivo.estado_conexion || "OFFLINE";
  const statusBadge = {
    ONLINE: "bg-emerald-500/15 text-emerald-700 ring-emerald-300",
    SIN_DATOS: "bg-amber-500/15 text-amber-700 ring-amber-300",
    OFFLINE: "bg-rose-500/15 text-rose-700 ring-rose-300",
  }[deviceStatus];

  const isDemoActive = config.demoMode || demoFallback;

  const navItems = [
    { to: "/", label: "Tiempo Real", icon: Activity },
    { to: "/historico", label: "Histórico", icon: Clock },
    { to: "/analitica", label: "Analítica", icon: BarChart3 },
    { to: "/alertas", label: "Alertas y Auditoría", icon: ShieldAlert },
    { to: "/control", label: "Control Remoto", icon: Sliders },
    { to: "/reporte", label: "Reporte PDF", icon: FileText },
  ];

  return (
    <HashRouter>
      <div className="min-h-screen bg-slate-50">
        {/* Banner discreto de Modo Demo */}
        {isDemoActive && (
          <div className="no-print flex flex-wrap items-center justify-between gap-2 bg-amber-500 px-4 py-1.5 text-xs font-semibold text-slate-950">
            <span>
              Modo Demostración Offline activo — mostrando datos acuícolas simulados locales
              {!config.demoMode ? " (backend no detectado en la URL configurada)." : "."}
            </span>
            <button
              onClick={() => setShowConfigModal(true)}
              className="rounded-md bg-slate-900 px-2.5 py-0.5 text-white hover:bg-slate-800"
            >
              Configurar Backend
            </button>
          </div>
        )}

        {/* Barra superior de estado en tiempo real */}
        <header className="no-print sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-600 text-white shadow-sm">
                <Waves className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-base font-bold leading-tight text-slate-900">AquaWeb IoT</h1>
                <p className="text-[11px] text-slate-500">Telemetría y Control Acuícola</p>
              </div>
            </div>

            {/* Indicadores en vivo */}
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-bold ring-1 ${statusBadge}`}>
                <Radio className="h-3.5 w-3.5" />
                {deviceStatus}
              </span>

              <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold text-slate-700">
                Modo: {overview?.dispositivo.modo_operacion || "AUTO"}
              </span>

              <span
                className={`rounded-full px-3 py-1 font-semibold ${
                  overview?.dispositivo.actuador_activo
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                Bomba: {overview?.dispositivo.actuador_activo ? "ON" : "OFF"}
              </span>

              <span
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium ${
                  wsConnected ? "bg-sky-50 text-sky-700" : "bg-slate-100 text-slate-500"
                }`}
                title="Estado de conexión WebSocket con el backend"
              >
                {wsConnected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
                {wsConnected ? "WS Live" : isDemoActive ? "Demo" : "HTTP"}
              </span>

              {overview?.ultima_lectura && (
                <span className="hidden text-slate-400 lg:inline">
                  Última: {new Date(overview.ultima_lectura.recibido_en).toLocaleTimeString("es-PA")}
                </span>
              )}

              <button
                onClick={toggleDemoQuick}
                className={`rounded-lg border px-2.5 py-1 font-semibold transition ${
                  config.demoMode
                    ? "border-amber-400 bg-amber-50 text-amber-800"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                {config.demoMode ? "Demo: ON" : "Modo Demo"}
              </button>

              <button
                onClick={() => setShowConfigModal(true)}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Settings className="h-3.5 w-3.5" /> Servidor
              </button>
            </div>
          </div>

          {/* Navegación principal */}
          <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `inline-flex shrink-0 items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition ${
                    isActive
                      ? "bg-sky-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6">
          <Routes>
            <Route path="/" element={<OverviewPage overview={overview} />} />
            <Route path="/historico" element={<HistoryPage config={config} onDemoFallback={setDemoFallback} />} />
            <Route path="/analitica" element={<AnalyticsPage config={config} onDemoFallback={setDemoFallback} />} />
            <Route path="/alertas" element={<AlertsAuditPage config={config} onDemoFallback={setDemoFallback} />} />
            <Route
              path="/control"
              element={
                <ControlPage
                  config={config}
                  overview={overview}
                  onRefresh={refreshOverview}
                  onDemoFallback={setDemoFallback}
                />
              }
            />
            <Route
              path="/reporte"
              element={<ReportPage config={config} overview={overview} onDemoFallback={setDemoFallback} />}
            />
          </Routes>
        </main>

        {showConfigModal && (
          <ServerConfigModal
            config={config}
            onClose={() => setShowConfigModal(false)}
            onSave={handleSaveConfig}
          />
        )}
      </div>
    </HashRouter>
  );
}
