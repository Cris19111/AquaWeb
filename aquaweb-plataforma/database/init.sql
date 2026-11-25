-- ============================================================================
-- AquaWeb IoT — Script DDL Idempotente (PostgreSQL 16)
-- Plataforma de Monitoreo, Control Remoto y Analítica Descriptiva Acuícola
-- ============================================================================

BEGIN;

-- 1. Estanques de cultivo de camarón
CREATE TABLE IF NOT EXISTS estanques (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(120) NOT NULL UNIQUE,
    ubicacion   VARCHAR(180) NOT NULL,
    especie     VARCHAR(120) NOT NULL DEFAULT 'Litopenaeus vannamei',
    volumen_m3  NUMERIC(10, 2) NOT NULL CHECK (volumen_m3 > 0),
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Dispositivos embebidos ESP32 vinculados a cada estanque
CREATE TABLE IF NOT EXISTS dispositivos (
    id                SERIAL PRIMARY KEY,
    estanque_id       INTEGER NOT NULL REFERENCES estanques(id) ON DELETE CASCADE,
    client_id_mqtt    VARCHAR(120) NOT NULL UNIQUE,
    nombre            VARCHAR(120) NOT NULL,
    estado_conexion   VARCHAR(20) NOT NULL DEFAULT 'OFFLINE'
                          CHECK (estado_conexion IN ('ONLINE', 'SIN_DATOS', 'OFFLINE')),
    modo_operacion    VARCHAR(10) NOT NULL DEFAULT 'AUTO'
                          CHECK (modo_operacion IN ('AUTO', 'MANUAL')),
    actuador_activo   BOOLEAN NOT NULL DEFAULT FALSE,
    intervalo_pub_seg INTEGER NOT NULL DEFAULT 5 CHECK (intervalo_pub_seg BETWEEN 1 AND 3600),
    ultimo_latido     TIMESTAMPTZ,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispositivos_estanque
    ON dispositivos (estanque_id);

-- 3. Umbrales óptimos y límites físicos por estanque y parámetro
CREATE TABLE IF NOT EXISTS umbrales_parametros (
    id             SERIAL PRIMARY KEY,
    estanque_id    INTEGER NOT NULL REFERENCES estanques(id) ON DELETE CASCADE,
    parametro      VARCHAR(20) NOT NULL
                       CHECK (parametro IN ('ph', 'temperatura', 'tds', 'ec', 'salinidad')),
    min_optimo     NUMERIC(10, 2) NOT NULL,
    max_optimo     NUMERIC(10, 2) NOT NULL,
    min_fisico     NUMERIC(10, 2) NOT NULL,
    max_fisico     NUMERIC(10, 2) NOT NULL,
    unidad         VARCHAR(20) NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_umbral_estanque_parametro UNIQUE (estanque_id, parametro),
    CONSTRAINT chk_umbrales_orden CHECK (
        min_fisico <= min_optimo
        AND min_optimo < max_optimo
        AND max_optimo <= max_fisico
    )
);

-- 4. Series de tiempo de telemetría (5 variables acuícolas)
CREATE TABLE IF NOT EXISTS lecturas_telemetria (
    id                    BIGSERIAL PRIMARY KEY,
    dispositivo_id        INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    ph                    NUMERIC(5, 2) NOT NULL CHECK (ph >= 0.0 AND ph <= 14.0),
    temperatura_c         NUMERIC(5, 2) NOT NULL CHECK (temperatura_c >= -5.0 AND temperatura_c <= 60.0),
    tds_ppm               NUMERIC(10, 2) NOT NULL CHECK (tds_ppm >= 0.0 AND tds_ppm <= 50000.0),
    ec_ppm                NUMERIC(10, 2) NOT NULL CHECK (ec_ppm >= 0.0 AND ec_ppm <= 80000.0),
    salinidad_ppm         NUMERIC(10, 2) NOT NULL CHECK (salinidad_ppm >= 0.0 AND salinidad_ppm <= 50000.0),
    actuador_estado       BOOLEAN NOT NULL,
    modo_operacion        VARCHAR(10) NOT NULL CHECK (modo_operacion IN ('AUTO', 'MANUAL')),
    calidad_dato          VARCHAR(15) NOT NULL DEFAULT 'VALIDA'
                              CHECK (calidad_dato IN ('VALIDA', 'SOSPECHOSA')),
    timestamp_dispositivo TIMESTAMPTZ,
    recibido_en           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índice compuesto obligatorio para consultas de series de tiempo
CREATE INDEX IF NOT EXISTS idx_lecturas_dispositivo_recibido
    ON lecturas_telemetria (dispositivo_id, recibido_en DESC);

CREATE INDEX IF NOT EXISTS idx_lecturas_calidad_recibido
    ON lecturas_telemetria (calidad_dato, recibido_en DESC);

-- 5. Alertas basadas en reglas determinísticas y diagnóstico de sensor
CREATE TABLE IF NOT EXISTS alertas (
    id                BIGSERIAL PRIMARY KEY,
    dispositivo_id    INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    lectura_id        BIGINT REFERENCES lecturas_telemetria(id) ON DELETE SET NULL,
    parametro         VARCHAR(30) NOT NULL,
    valor_detectado   NUMERIC(10, 2),
    umbral_infringido VARCHAR(60) NOT NULL,
    severidad         VARCHAR(20) NOT NULL CHECK (severidad IN ('ADVERTENCIA', 'CRITICA')),
    mensaje           TEXT NOT NULL,
    estado            VARCHAR(20) NOT NULL DEFAULT 'ACTIVA'
                          CHECK (estado IN ('ACTIVA', 'RECONOCIDA', 'RESUELTA')),
    creada_en         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resuelta_en       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alertas_dispositivo_estado
    ON alertas (dispositivo_id, estado, creada_en DESC);

-- 6. Historial de transiciones de estado de conectividad (solo cambios de estado)
CREATE TABLE IF NOT EXISTS eventos_comunicacion (
    id              BIGSERIAL PRIMARY KEY,
    dispositivo_id  INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    estado_anterior VARCHAR(20) NOT NULL,
    estado_nuevo    VARCHAR(20) NOT NULL CHECK (estado_nuevo IN ('ONLINE', 'SIN_DATOS', 'OFFLINE')),
    gravedad        VARCHAR(15) NOT NULL CHECK (gravedad IN ('INFO', 'WARNING', 'CRITICAL')),
    detalle         TEXT NOT NULL,
    registrado_en   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eventos_dispositivo_fecha
    ON eventos_comunicacion (dispositivo_id, registrado_en DESC);

-- 7. Trazabilidad de órdenes remotas MQTT hacia el ESP32
CREATE TABLE IF NOT EXISTS ordenes_control (
    id                BIGSERIAL PRIMARY KEY,
    dispositivo_id    INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    command_id        UUID NOT NULL UNIQUE,
    tipo_orden        VARCHAR(40) NOT NULL,
    payload_json      JSONB NOT NULL,
    estado            VARCHAR(20) NOT NULL DEFAULT 'ENVIADA'
                          CHECK (estado IN ('ENVIADA', 'APLICADA', 'RECHAZADA', 'EXPIRADA')),
    detalle_respuesta TEXT,
    creada_en         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizada_en    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ordenes_dispositivo_fecha
    ON ordenes_control (dispositivo_id, creada_en DESC);

-- 8. Auditoría forense de paquetes MQTT corruptos o fuera de rango físico
CREATE TABLE IF NOT EXISTS mensajes_rechazados (
    id             BIGSERIAL PRIMARY KEY,
    topico         VARCHAR(255) NOT NULL,
    payload_crudo  TEXT NOT NULL,
    motivo_rechazo TEXT NOT NULL,
    recibido_en    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rechazados_fecha
    ON mensajes_rechazados (recibido_en DESC);

COMMIT;
