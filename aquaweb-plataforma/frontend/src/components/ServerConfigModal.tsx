import { useState } from "react";
import { Server, X } from "lucide-react";
import type { ServerConfig } from "../types";

interface Props {
  config: ServerConfig;
  onClose: () => void;
  onSave: (cfg: ServerConfig) => void;
}

export function ServerConfigModal({ config, onClose, onSave }: Props) {
  const [apiUrl, setApiUrl] = useState(config.apiUrl);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [demoMode, setDemoMode] = useState(config.demoMode);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({ apiUrl: apiUrl.trim() || "http://localhost:8000", apiKey: apiKey.trim(), demoMode });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-sky-600" />
            <h2 className="text-lg font-bold text-slate-900">Configuración de Servidor</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-600">
              URL del Backend FastAPI (HTTPS o Local)
            </label>
            <input
              type="url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="https://api-aquaweb.tu-dominio.com"
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200"
            />
            <p className="mt-1 text-xs text-slate-500">
              Se guarda en <code>localStorage</code> para uso directo desde GitHub Pages.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase text-slate-600">
              Cabecera X-API-Key (Control Remoto y Umbrales)
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="aquaweb-dev-key-2026"
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200"
            />
          </div>

          <label className="flex cursor-pointer items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div>
              <p className="text-sm font-semibold text-slate-800">Modo Demo Offline</p>
              <p className="text-xs text-slate-500">
                Usa datos acuícolas simulados locales sin requerir backend activo.
              </p>
            </div>
            <input
              type="checkbox"
              checked={demoMode}
              onChange={(e) => setDemoMode(e.target.checked)}
              className="h-5 w-5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            />
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700"
            >
              Guardar y Reconectar
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
