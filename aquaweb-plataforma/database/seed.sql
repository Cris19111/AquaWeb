-- ============================================================================
-- AquaWeb IoT — Script de Datos Semilla Realistas (Últimos 7 días)
-- Idempotente: seguro para re-ejecutar sin duplicar registros base.
-- ============================================================================

BEGIN;

-- 1. Estanque piloto camaronero (Panamá)
INSERT INTO estanques (nombre, ubicacion, especie, volumen_m3, activo)
VALUES (
    'Estanque Camaronero #1 - Aguadulce',
    'Aguadulce, Coclé, Panamá (Sector Salinero Norte)',
    'Litopenaeus vannamei',
    4500.00,
    TRUE
)
ON CONFLICT (nombre) DO NOTHING;

-- 2. Dispositivo ESP32 principal
INSERT INTO dispositivos (
    estanque_id,
    client_id_mqtt,
    nombre,
    estado_conexion,
    modo_operacion,
    actuador_activo,
    intervalo_pub_seg,
    ultimo_latido
)
SELECT
    e.id,
    'estanque-01',
    'Nodo ESP32 Estanque #1',
    'ONLINE',
    'AUTO',
    FALSE,
    5,
    NOW() - INTERVAL '3 seconds'
FROM estanques e
WHERE e.nombre = 'Estanque Camaronero #1 - Aguadulce'
ON CONFLICT (client_id_mqtt) DO NOTHING;

-- 3. Umbrales óptimos y físicos de referencia para las 5 variables acuícolas
INSERT INTO umbrales_parametros (estanque_id, parametro, min_optimo, max_optimo, min_fisico, max_fisico, unidad)
SELECT e.id, v.parametro, v.min_opt, v.max_opt, v.min_fis, v.max_fis, v.unidad
FROM estanques e
CROSS JOIN (
    VALUES
        ('ph',          6.50,     9.50,    0.00,    14.00, 'pH'),
        ('temperatura', 20.00,   30.00,   -5.00,    60.00, '°C'),
        ('tds',         4000.00, 15000.00, 0.00, 50000.00, 'ppm'),
        ('ec',         10000.00, 35000.00, 0.00, 80000.00, 'ppm'),
        ('salinidad',   5000.00, 23000.00, 0.00, 50000.00, 'ppm')
) AS v(parametro, min_opt, max_opt, min_fis, max_fis, unidad)
WHERE e.nombre = 'Estanque Camaronero #1 - Aguadulce'
ON CONFLICT (estanque_id, parametro) DO NOTHING;

-- 4. Telemetría realista de los últimos 7 días (cada 30 min = 337 lecturas)
--    Incluye ciclos diurnos térmicos/fotosintéticos y episodios puntuales fuera de rango
DO $$
DECLARE
    v_dev_id INTEGER;
    v_count  BIGINT;
BEGIN
    SELECT id INTO v_dev_id FROM dispositivos WHERE client_id_mqtt = 'estanque-01' LIMIT 1;
    SELECT COUNT(*) INTO v_count FROM lecturas_telemetria WHERE dispositivo_id = v_dev_id;

    IF v_dev_id IS NOT NULL AND v_count = 0 THEN
        INSERT INTO lecturas_telemetria (
            dispositivo_id,
            ph,
            temperatura_c,
            tds_ppm,
            ec_ppm,
            salinidad_ppm,
            actuador_estado,
            modo_operacion,
            calidad_dato,
            timestamp_dispositivo,
            recibido_en
        )
        SELECT
            v_dev_id,
            -- pH oscila con ciclo diurno fotosintético + pico puntual en el día 2 y caída leve en día 5
            ROUND((
                7.85
                + 0.55 * SIN(EXTRACT(EPOCH FROM ts) / 86400.0 * 2.0 * PI() - 1.1)
                + CASE WHEN idx BETWEEN 92 AND 96 THEN 1.35 ELSE 0.0 END
                + CASE WHEN idx BETWEEN 240 AND 244 THEN -1.55 ELSE 0.0 END
                + ((idx % 7) - 3) * 0.04
            )::NUMERIC, 2) AS ph_val,
            -- Temperatura tropical en Panamá (25.5 - 30.8 °C con pico en tardes soleadas)
            ROUND((
                27.40
                + 2.10 * SIN(EXTRACT(EPOCH FROM ts) / 86400.0 * 2.0 * PI() - 1.8)
                + CASE WHEN idx BETWEEN 148 AND 152 THEN 1.65 ELSE 0.0 END
                + ((idx % 5) - 2) * 0.08
            )::NUMERIC, 2) AS temp_val,
            -- TDS correlacionado con EC (~0.48 * EC)
            ROUND((
                10400.0
                + 1600.0 * SIN(EXTRACT(EPOCH FROM ts) / (86400.0 * 3.0) * 2.0 * PI())
                + ((idx % 11) - 5) * 95.0
            )::NUMERIC, 2) AS tds_val,
            -- EC base (~21500 ppm, rango óptimo 10000 - 35000 ppm)
            ROUND((
                21800.0
                + 3300.0 * SIN(EXTRACT(EPOCH FROM ts) / (86400.0 * 3.0) * 2.0 * PI())
                + ((idx % 11) - 5) * 195.0
            )::NUMERIC, 2) AS ec_val,
            -- Salinidad correlacionada (~0.64 * EC, rango óptimo 5000 - 23000 ppm)
            ROUND((
                14200.0
                + 2150.0 * SIN(EXTRACT(EPOCH FROM ts) / (86400.0 * 3.0) * 2.0 * PI())
                + ((idx % 11) - 5) * 130.0
            )::NUMERIC, 2) AS sal_val,
            -- Actuador encendido cuando hay estrés térmico o de pH
            (idx BETWEEN 92 AND 96 OR idx BETWEEN 148 AND 152 OR idx BETWEEN 240 AND 244) AS act_val,
            'AUTO',
            CASE WHEN idx IN (180, 181) THEN 'SOSPECHOSA' ELSE 'VALIDA' END,
            ts,
            ts + INTERVAL '1 second'
        FROM (
            SELECT
                ROW_NUMBER() OVER () AS idx,
                gs AS ts
            FROM generate_series(
                NOW() - INTERVAL '7 days',
                NOW() - INTERVAL '5 minutes',
                INTERVAL '30 minutes'
            ) AS gs
        ) series;

        -- 5. Alertas históricas + 1 alerta activa de ejemplo
        INSERT INTO alertas (
            dispositivo_id, lectura_id, parametro, valor_detectado,
            umbral_infringido, severidad, mensaje, estado, creada_en, resuelta_en
        )
        VALUES
            (
                v_dev_id, NULL, 'ph', 9.72, '> 9.50 pH', 'ADVERTENCIA',
                'pH elevado por alta fotosíntesis vespertina; aireador activado automáticamente.',
                'RESUELTA', NOW() - INTERVAL '5 days', NOW() - INTERVAL '4 days 21 hours'
            ),
            (
                v_dev_id, NULL, 'temperatura', 31.25, '> 30.00 °C', 'CRITICA',
                'Temperatura superficial excedió el límite óptimo de 30.0 °C durante pico solar.',
                'RESUELTA', NOW() - INTERVAL '3 days 18 hours', NOW() - INTERVAL '3 days 15 hours'
            ),
            (
                v_dev_id, NULL, 'ph', 6.18, '< 6.50 pH', 'ADVERTENCIA',
                'Descenso de pH en madrugada por respiración del cultivo; recambio parcial activado.',
                'RECONOCIDA', NOW() - INTERVAL '1 day 10 hours', NULL
            ),
            (
                v_dev_id, NULL, 'sensor_ph', 7.85, 'sensor_congelado', 'ADVERTENCIA',
                'Posible sensor congelado detectado en dos ciclos consecutivos (revisión de sonda recomendada).',
                'ACTIVA', NOW() - INTERVAL '6 hours', NULL
            );

        -- 6. Eventos de comunicación (transiciones reales de conectividad)
        INSERT INTO eventos_comunicacion (
            dispositivo_id, estado_anterior, estado_nuevo, gravedad, detalle, registrado_en
        )
        VALUES
            (v_dev_id, 'INICIAL', 'ONLINE', 'INFO', 'Nodo ESP32 conectado al broker MQTT (ONLINE retenido).', NOW() - INTERVAL '7 days'),
            (v_dev_id, 'ONLINE', 'SIN_DATOS', 'WARNING', 'Sin telemetría durante 21.4 s (umbral 15 s).', NOW() - INTERVAL '4 days 6 hours'),
            (v_dev_id, 'SIN_DATOS', 'ONLINE', 'INFO', 'Telemetría restablecida tras reconexión Wi-Fi.', NOW() - INTERVAL '4 days 5 hours 58 minutes'),
            (v_dev_id, 'ONLINE', 'OFFLINE', 'CRITICAL', 'Desconexión abrupta detectada vía Testamento LWT del broker.', NOW() - INTERVAL '2 days 3 hours'),
            (v_dev_id, 'OFFLINE', 'ONLINE', 'INFO', 'Nodo ESP32 recuperado tras backoff exponencial.', NOW() - INTERVAL '2 days 2 hours 55 minutes');

        -- 7. Historial de órdenes remotas de ejemplo
        INSERT INTO ordenes_control (
            dispositivo_id, command_id, tipo_orden, payload_json, estado, detalle_respuesta, creada_en, actualizada_en
        )
        VALUES
            (
                v_dev_id, '11111111-1111-4111-8111-111111111111', 'CONTROL_ACTUADOR',
                '{"modo": "MANUAL", "actuador": 1}'::JSONB, 'APLICADA',
                'Actuador encendido en modo MANUAL por orden remota.',
                NOW() - INTERVAL '3 days 17 hours', NOW() - INTERVAL '3 days 17 hours' + INTERVAL '2 seconds'
            ),
            (
                v_dev_id, '22222222-2222-4222-8222-222222222222', 'CAMBIO_MODO',
                '{"modo": "AUTO"}'::JSONB, 'APLICADA',
                'Modo AUTO restaurado correctamente.',
                NOW() - INTERVAL '3 days 15 hours', NOW() - INTERVAL '3 days 15 hours' + INTERVAL '1 second'
            ),
            (
                v_dev_id, '33333333-3333-4333-8333-333333333333', 'ACTUALIZAR_UMBRALES',
                '{"parametro": "ph", "min_optimo": 6.5, "max_optimo": 9.5}'::JSONB, 'APLICADA',
                'Umbrales de pH sincronizados con el nodo.',
                NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '2 seconds'
            ),
            (
                v_dev_id, '44444444-4444-4444-8444-444444444444', 'CONTROL_ACTUADOR',
                '{"modo": "MANUAL", "actuador": 1}'::JSONB, 'EXPIRADA',
                'Sin acuse de recibo (ordenes_ack) tras 15 s durante microcorte de red.',
                NOW() - INTERVAL '2 days 3 hours', NOW() - INTERVAL '2 days 3 hours' + INTERVAL '15 seconds'
            );

        -- 8. Mensajes rechazados (auditoría forense de ejemplo)
        INSERT INTO mensajes_rechazados (topico, payload_crudo, motivo_rechazo, recibido_en)
        VALUES
            (
                'utp/ds8/grupo/aquaweb/estanque-01/telemetria',
                '{"ph": 19.8, "temperatura_c": 27.1, "tds_ppm": 10000, "ec_ppm": 21000, "salinidad_ppm": 13500}',
                'Valor fuera de rango físico: ph=19.8 fuera de [0.0, 14.0].',
                NOW() - INTERVAL '2 days 11 hours'
            ),
            (
                'utp/ds8/grupo/aquaweb/estanque-01/telemetria',
                '{ph: 7.6, temperatura_c: NaN',
                'JSON malformado o no decodificable.',
                NOW() - INTERVAL '1 day 4 hours'
            );
    END IF;
END $$;

COMMIT;
