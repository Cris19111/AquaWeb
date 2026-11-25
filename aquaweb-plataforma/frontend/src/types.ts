export type ParameterKey = "ph" | "temperatura" | "tds" | "ec" | "salinidad";

export interface Estanque {
  id: number;
  nombre: string;
  ubicacion: string;
  especie: string;
  volumen_m3: number;
}

export interface DeviceInfo {
  id: number;
  estanque_id: number;
  client_id_mqtt: string;
  nombre: string;
  estado_conexion: "ONLINE" | "SIN_DATOS" | "OFFLINE";
  modo_operacion: "AUTO" | "MANUAL";
  actuador_activo: boolean;
  intervalo_pub_seg: number;
  ultimo_latido: string | null;
}

export interface TelemetryReading {
  id: number;
  dispositivo_id?: number;
  ph: number;
  temperatura_c: number;
  tds_ppm: number;
  ec_ppm: number;
  salinidad_ppm: number;
  actuador_estado: boolean;
  modo_operacion: "AUTO" | "MANUAL";
  calidad_dato: "VALIDA" | "SOSPECHOSA";
  recibido_en: string;
  muestras?: number;
}

export interface Threshold {
  id: number;
  estanque_id: number;
  parametro: ParameterKey;
  min_optimo: number;
  max_optimo: number;
  min_fisico: number;
  max_fisico: number;
  unidad: string;
  actualizado_en: string;
}

export interface OverviewResponse {
  estanque: Estanque | null;
  dispositivo: DeviceInfo;
  ultima_lectura: TelemetryReading | null;
  lectura_anterior: TelemetryReading | null;
  sparkline: TelemetryReading[];
  umbrales: Threshold[];
  alertas_activas: number;
  buffer_pendiente: number;
  mqtt_conectado: boolean;
}

export interface ParameterStats {
  parametro: ParameterKey;
  unidad: string;
  count: number;
  promedio: number;
  mediana: number;
  minimo: number;
  maximo: number;
  desviacion_std: number;
  tasa_variacion: number;
  cumplimiento_pct: number;
  violaciones: number;
  min_optimo: number;
  max_optimo: number;
  histograma: Array<{ rango: string; desde: number; hasta: number; conteo: number }>;
}

export interface AnalyticsSummary {
  rango_inicio: string | null;
  rango_fin: string | null;
  total_lecturas: number;
  lecturas_validas: number;
  lecturas_sospechosas: number;
  indice_salud_pct: number;
  uptime_pct: number;
  parametros: ParameterStats[];
  violaciones_por_franja: { manana: number; tarde: number; noche: number };
}

export interface AlertItem {
  id: number;
  dispositivo_id: number;
  lectura_id: number | null;
  parametro: string;
  valor_detectado: number | null;
  umbral_infringido: string;
  severidad: "ADVERTENCIA" | "CRITICA";
  mensaje: string;
  estado: "ACTIVA" | "RECONOCIDA" | "RESUELTA";
  creada_en: string;
  resuelta_en: string | null;
}

export interface CommEvent {
  id: number;
  dispositivo_id: number;
  estado_anterior: string;
  estado_nuevo: "ONLINE" | "SIN_DATOS" | "OFFLINE";
  gravedad: "INFO" | "WARNING" | "CRITICAL";
  detalle: string;
  registrado_en: string;
}

export interface ControlCommand {
  id: number;
  dispositivo_id: number;
  command_id: string;
  tipo_orden: string;
  payload_json: Record<string, unknown>;
  estado: "ENVIADA" | "APLICADA" | "RECHAZADA" | "EXPIRADA";
  detalle_respuesta: string | null;
  creada_en: string;
  actualizada_en: string;
}

export interface RejectedMessage {
  id: number;
  topico: string;
  payload_crudo: string;
  motivo_rechazo: string;
  recibido_en: string;
}

export interface ServerConfig {
  apiUrl: string;
  apiKey: string;
  demoMode: boolean;
}
