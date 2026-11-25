"""Configuración centralizada del backend MQTT para AquaWeb IoT (Avance 3)."""

from pathlib import Path

# --- Configuración del Broker MQTT ---
BROKER_HOST = "broker.hivemq.com"
# BROKER_HOST = "test.mosquitto.org"  # Broker público alternativo
BROKER_PORT = 1883
KEEPALIVE_SEG = 15

# --- Identificador de grupo y esquema de temas MQTT ---
GRUPO = "grupo"
TOPIC_PREFIX = f"utp/ds8/{GRUPO}/aquaweb"
TOPIC_TELEMETRIA = f"{TOPIC_PREFIX}/telemetria"
TOPIC_ESTADO = f"{TOPIC_PREFIX}/estado"
TOPIC_ORDENES = f"{TOPIC_PREFIX}/ordenes"
TOPIC_WILDCARD = f"{TOPIC_PREFIX}/#"

# --- Temporización y detección de silencio ---
INTERVALO_PUB_SEG = 5
SILENCIO_MAX_SEG = 20  # Al menos 3x el intervalo de publicación (5 s)
EVALUACION_MONITOR_SEG = 1.0

# --- Rangos válidos de telemetría física y control ---
PH_MIN = 0.0
PH_MAX = 14.0
TEMP_MIN = 0.0
TEMP_MAX = 60.0
ACTUADOR_VALIDOS = (0, 1)
MODOS_VALIDOS = ("AUTO", "MANUAL")

# --- Rutas de persistencia CSV ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TELEMETRIA_CSV = DATA_DIR / "telemetria_valida.csv"
EVENTOS_CSV = DATA_DIR / "eventos_comunicacion.csv"

TELEMETRIA_HEADERS = ["fecha_hora", "ph", "temperatura", "actuador", "modo"]
EVENTOS_HEADERS = ["fecha", "tipo", "gravedad", "detalle"]
