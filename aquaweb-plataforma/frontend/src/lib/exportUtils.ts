import type { TelemetryReading } from "../types";

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function exportReadingsCSV(readings: TelemetryReading[], filename = "aquaweb_telemetria.csv"): void {
  const headers = [
    "recibido_en",
    "ph",
    "temperatura_c",
    "tds_ppm",
    "ec_ppm",
    "salinidad_ppm",
    "actuador_estado",
    "modo_operacion",
    "calidad_dato",
  ];
  const rows = readings.map((r) =>
    [
      r.recibido_en,
      r.ph,
      r.temperatura_c,
      r.tds_ppm,
      r.ec_ppm,
      r.salinidad_ppm,
      r.actuador_estado ? "ON" : "OFF",
      r.modo_operacion,
      r.calidad_dato,
    ].join(",")
  );
  const csv = [headers.join(","), ...rows].join("\n");
  triggerDownload(new Blob([csv], { type: "text/csv;charset=utf-8;" }), filename);
}

export function exportDataJSON(data: unknown, filename = "aquaweb_export.json"): void {
  const json = JSON.stringify(data, null, 2);
  triggerDownload(new Blob([json], { type: "application/json;charset=utf-8;" }), filename);
}
