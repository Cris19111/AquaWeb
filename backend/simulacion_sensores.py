#!/usr/bin/env python3
"""Módulo de simulación y procesamiento de datos para AquaWeb IoT (Avance 2).

Simula lecturas de calidad de agua en estanques camaroneros (pH y Temperatura),
valida e integra umbrales de clasificación (OPTIMO, ADVERTENCIA, CRITICO),
dispara eventos mediante callbacks ante condiciones críticas y persiste tanto el
estado más reciente (JSON) como el historial temporal (CSV).
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable

# Rutas de persistencia relativas a este archivo
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ESTADO_JSON_PATH = DATA_DIR / "estado_actual.json"
HISTORIAL_CSV_PATH = DATA_DIR / "historial_sensores.csv"

# Límites físicos absolutos para detección de fallas de sensor
PH_MIN_FISICO = 0.0
PH_MAX_FISICO = 14.0
TEMP_MIN_FISICO = -10.0
TEMP_MAX_FISICO = 60.0

# Rangos de simulación requeridos para el avance
PH_SIM_MIN = 5.0
PH_SIM_MAX = 11.0
TEMP_SIM_MIN = 17.0
TEMP_SIM_MAX = 36.0

# Umbrales acuícolas para cultivo de camarón
PH_OPTIMO_MIN = 6.5
PH_OPTIMO_MAX = 9.5
PH_ADVERTENCIA_MIN = 6.0
PH_ADVERTENCIA_MAX = 10.0

TEMP_OPTIMA_MIN = 20.0
TEMP_OPTIMA_MAX = 30.0
TEMP_ADVERTENCIA_MIN = 18.5
TEMP_ADVERTENCIA_MAX = 32.0

# Niveles de clasificación
ESTADO_OPTIMO = "OPTIMO"
ESTADO_ADVERTENCIA = "ADVERTENCIA"
ESTADO_CRITICO = "CRITICO"

# Encabezados del archivo histórico CSV
CSV_HEADERS = [
    "timestamp",
    "ciclo",
    "ph",
    "estado_ph",
    "temperatura_c",
    "estado_temperatura",
    "estado_general",
    "bomba_aireacion",
    "eventos",
]

# Escenarios representativos para los primeros 10 ciclos (incluye casos límite)
ESCENARIOS_INICIALES: tuple[tuple[float, float], ...] = (
    (7.8, 26.5),   # Ciclo 1: Ambos en rango óptimo
    (6.5, 20.0),   # Ciclo 2: Caso límite inferior óptimo exacto
    (9.5, 30.0),   # Ciclo 3: Caso límite superior óptimo exacto
    (6.2, 27.0),   # Ciclo 4: pH en advertencia baja
    (8.1, 31.4),   # Ciclo 5: Temperatura en advertencia alta
    (5.4, 28.0),   # Ciclo 6: pH crítico ácido -> dispara alerta/aireación
    (10.6, 25.0),  # Ciclo 7: pH crítico alcalino -> dispara alerta/aireación
    (7.5, 17.5),   # Ciclo 8: Temperatura crítica baja -> dispara alerta
    (9.8, 34.5),   # Ciclo 9: pH advertencia + Temperatura crítica alta
    (7.9, 27.2),   # Ciclo 10: Retorno a operación óptima estable
)

CallbackEvento = Callable[[dict[str, Any]], None]


class GestorEventos:
    """Administra suscripciones y despacho de eventos mediante callbacks."""

    def __init__(self) -> None:
        self._callbacks: dict[str, list[CallbackEvento]] = {}

    def registrar_callback(self, tipo_evento: str, callback: CallbackEvento) -> None:
        """Asocia una función callback a un tipo de evento específico."""
        if not callable(callback):
            raise TypeError(f"El callback para '{tipo_evento}' debe ser invocable.")
        self._callbacks.setdefault(tipo_evento, []).append(callback)

    def disparar_evento(self, tipo_evento: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Ejecuta los callbacks registrados para el evento y retorna el registro."""
        registro = {
            "tipo": tipo_evento,
            "timestamp": payload.get("timestamp", obtener_timestamp_iso()),
            "detalle": payload,
        }
        for callback in self._callbacks.get(tipo_evento, []):
            callback(registro)
        return [registro]


def obtener_timestamp_iso() -> str:
    """Retorna la marca de tiempo actual en formato ISO-8601 con zona UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validar_lectura(nombre: str, valor: Any, min_fisico: float, max_fisico: float) -> float:
    """Valida tipo numérico y rango físico de una lectura de sensor.

    Lanza TypeError si el dato no es numérico (incluyendo bool o None) y
    ValueError si es NaN/Inf o excede los límites físicos del transductor.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise TypeError(
            f"Lectura inválida para '{nombre}': se esperaba int/float y se recibió {type(valor).__name__}."
        )

    valor_float = float(valor)
    if not math.isfinite(valor_float):
        raise ValueError(f"Lectura no finita detectada en '{nombre}': {valor!r}.")

    if not (min_fisico <= valor_float <= max_fisico):
        raise ValueError(
            f"Lectura fuera de rango físico para '{nombre}': {valor_float} "
            f"(permitido [{min_fisico}, {max_fisico}])."
        )

    return round(valor_float, 2)


def clasificar_parametro(
    valor: float,
    optimo_min: float,
    optimo_max: float,
    adv_min: float,
    adv_max: float,
) -> str:
    """Clasifica una lectura numérica en OPTIMO, ADVERTENCIA o CRITICO."""
    if optimo_min <= valor <= optimo_max:
        return ESTADO_OPTIMO
    if adv_min <= valor <= adv_max:
        return ESTADO_ADVERTENCIA
    return ESTADO_CRITICO


def clasificar_ph(ph: float) -> str:
    """Clasifica el nivel de pH del estanque."""
    return clasificar_parametro(
        ph, PH_OPTIMO_MIN, PH_OPTIMO_MAX, PH_ADVERTENCIA_MIN, PH_ADVERTENCIA_MAX
    )


def clasificar_temperatura(temperatura: float) -> str:
    """Clasifica la temperatura del agua en grados Celsius."""
    return clasificar_parametro(
        temperatura,
        TEMP_OPTIMA_MIN,
        TEMP_OPTIMA_MAX,
        TEMP_ADVERTENCIA_MIN,
        TEMP_ADVERTENCIA_MAX,
    )


def calcular_estado_general(estados: list[str]) -> str:
    """Determina la severidad global combinando las clasificaciones activas."""
    if ESTADO_CRITICO in estados:
        return ESTADO_CRITICO
    if ESTADO_ADVERTENCIA in estados:
        return ESTADO_ADVERTENCIA
    return ESTADO_OPTIMO


def generar_lecturas(ciclo: int, rng: random.Random) -> dict[str, float]:
    """Genera lecturas de pH y temperatura dentro de los rangos simulados."""
    if 1 <= ciclo <= len(ESCENARIOS_INICIALES):
        ph_bruto, temp_bruta = ESCENARIOS_INICIALES[ciclo - 1]
    else:
        # En ciclos continuos se alterna entre operación estable y perturbaciones
        if rng.random() < 0.65:
            ph_bruto = rng.uniform(PH_OPTIMO_MIN, PH_OPTIMO_MAX)
            temp_bruta = rng.uniform(TEMP_OPTIMA_MIN, TEMP_OPTIMA_MAX)
        else:
            ph_bruto = rng.uniform(PH_SIM_MIN, PH_SIM_MAX)
            temp_bruta = rng.uniform(TEMP_SIM_MIN, TEMP_SIM_MAX)

    return {
        "ph": round(ph_bruto, 2),
        "temperatura_c": round(temp_bruta, 2),
    }


def callback_activar_aireacion(evento: dict[str, Any]) -> None:
    """Callback ejecutado cuando se requiere encender la aireación de emergencia."""
    detalle = evento["detalle"]
    print(
        f"  [EVENTO -> {evento['tipo']}] Bomba de aireación ACTIVADA "
        f"(ciclo {detalle['ciclo']}, motivo: {', '.join(detalle['parametros_criticos'])})."
    )


def callback_alerta_calidad_agua(evento: dict[str, Any]) -> None:
    """Callback ejecutado para notificar una anomalía crítica de calidad de agua."""
    detalle = evento["detalle"]
    print(
        f"  [EVENTO -> {evento['tipo']}] Severidad {detalle['severidad']} | "
        f"pH={detalle['ph']} ({detalle['estado_ph']}), "
        f"Temp={detalle['temperatura_c']} °C ({detalle['estado_temperatura']}) | "
        f"Acción: {detalle['accion_recomendada']}"
    )


def construir_gestor_eventos() -> GestorEventos:
    """Crea e inicializa el gestor de eventos con los callbacks del sistema."""
    gestor = GestorEventos()
    gestor.registrar_callback("ACTIVAR_AIREACION", callback_activar_aireacion)
    gestor.registrar_callback("ALERTA_CALIDAD_AGUA", callback_alerta_calidad_agua)
    return gestor


def evaluar_y_despachar_eventos(
    gestor: GestorEventos,
    ciclo: int,
    timestamp: str,
    ph: float,
    estado_ph: str,
    temperatura_c: float,
    estado_temp: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Evalúa umbrales críticos, dispara eventos y retorna estado de bomba."""
    parametros_criticos: list[str] = []
    if estado_ph == ESTADO_CRITICO:
        parametros_criticos.append(f"pH={ph}")
    if estado_temp == ESTADO_CRITICO:
        parametros_criticos.append(f"Temperatura={temperatura_c}°C")

    if not parametros_criticos:
        return False, []

    eventos_disparados: list[dict[str, Any]] = []
    payload_aireacion = {
        "ciclo": ciclo,
        "timestamp": timestamp,
        "bomba_aireacion": True,
        "parametros_criticos": parametros_criticos,
    }
    payload_alerta = {
        "ciclo": ciclo,
        "timestamp": timestamp,
        "severidad": ESTADO_CRITICO,
        "ph": ph,
        "estado_ph": estado_ph,
        "temperatura_c": temperatura_c,
        "estado_temperatura": estado_temp,
        "accion_recomendada": "Encender aireadores y verificar recambio de agua en estanque.",
    }

    eventos_disparados.extend(gestor.disparar_evento("ACTIVAR_AIREACION", payload_aireacion))
    eventos_disparados.extend(gestor.disparar_evento("ALERTA_CALIDAD_AGUA", payload_alerta))
    return True, eventos_disparados


def asegurar_directorio_datos(directorio: Path) -> None:
    """Garantiza que exista la carpeta de persistencia manejando errores de E/S."""
    try:
        directorio.mkdir(parents=True, exist_ok=True)
    except PermissionError as err:
        raise PermissionError(
            f"Sin permisos para crear el directorio de datos '{directorio}': {err}"
        ) from err
    except OSError as err:
        raise OSError(
            f"Error del sistema operativo al preparar '{directorio}': {err}"
        ) from err


def guardar_estado_actual(ruta_json: Path, estado: dict[str, Any]) -> None:
    """Sobrescribe de forma atómica el último estado del sistema en JSON."""
    asegurar_directorio_datos(ruta_json.parent)
    ruta_temporal = ruta_json.with_suffix(".json.tmp")
    try:
        with ruta_temporal.open("w", encoding="utf-8") as archivo:
            json.dump(estado, archivo, indent=2, ensure_ascii=False)
            archivo.write("\n")
        os.replace(ruta_temporal, ruta_json)
    except FileNotFoundError as err:
        raise FileNotFoundError(
            f"No se encontró la ruta destino para guardar JSON '{ruta_json}': {err}"
        ) from err
    except PermissionError as err:
        raise PermissionError(
            f"Permiso denegado al escribir '{ruta_json}': {err}"
        ) from err
    except OSError as err:
        raise OSError(
            f"Error de E/S al persistir el estado actual en '{ruta_json}': {err}"
        ) from err


def registrar_historial_csv(ruta_csv: Path, estado: dict[str, Any]) -> None:
    """Anexa la lectura procesada y eventos al archivo CSV histórico."""
    asegurar_directorio_datos(ruta_csv.parent)
    nombres_eventos = ";".join(ev["tipo"] for ev in estado["eventos_disparados"]) or "NINGUNO"
    fila = {
        "timestamp": estado["timestamp"],
        "ciclo": estado["ciclo"],
        "ph": f"{estado['sensores']['ph']['valor']:.2f}",
        "estado_ph": estado["sensores"]["ph"]["estado"],
        "temperatura_c": f"{estado['sensores']['temperatura_c']['valor']:.2f}",
        "estado_temperatura": estado["sensores"]["temperatura_c"]["estado"],
        "estado_general": estado["estado_general"],
        "bomba_aireacion": "ON" if estado["actuadores"]["bomba_aireacion"] else "OFF",
        "eventos": nombres_eventos,
    }

    try:
        escribir_encabezado = (not ruta_csv.exists()) or (ruta_csv.stat().st_size == 0)
        with ruta_csv.open("a", encoding="utf-8", newline="") as archivo:
            writer = csv.DictWriter(archivo, fieldnames=CSV_HEADERS)
            if escribir_encabezado:
                writer.writeheader()
            writer.writerow(fila)
    except FileNotFoundError as err:
        raise FileNotFoundError(
            f"No se encontró el archivo o directorio CSV '{ruta_csv}': {err}"
        ) from err
    except PermissionError as err:
        raise PermissionError(
            f"Permiso denegado al anexar datos en '{ruta_csv}': {err}"
        ) from err
    except OSError as err:
        raise OSError(
            f"Error de E/S al escribir el historial CSV '{ruta_csv}': {err}"
        ) from err


def construir_registro_estado(
    ciclo: int,
    timestamp: str,
    ph: float,
    estado_ph: str,
    temperatura_c: float,
    estado_temp: str,
    estado_general: str,
    bomba_aireacion: bool,
    eventos_disparados: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estructura el diccionario completo que se persiste y reporta por ciclo."""
    return {
        "proyecto": "AquaWeb IoT",
        "avance": "Avance 2 - Procesamiento de Datos",
        "ciclo": ciclo,
        "timestamp": timestamp,
        "sensores": {
            "ph": {
                "valor": ph,
                "unidad": "pH",
                "rango_optimo": [PH_OPTIMO_MIN, PH_OPTIMO_MAX],
                "estado": estado_ph,
            },
            "temperatura_c": {
                "valor": temperatura_c,
                "unidad": "°C",
                "rango_optimo": [TEMP_OPTIMA_MIN, TEMP_OPTIMA_MAX],
                "estado": estado_temp,
            },
        },
        "estado_general": estado_general,
        "actuadores": {
            "bomba_aireacion": bomba_aireacion,
        },
        "eventos_disparados": eventos_disparados,
    }


def procesar_ciclo(
    ciclo: int,
    rng: random.Random,
    gestor_eventos: GestorEventos,
    ruta_json: Path,
    ruta_csv: Path,
) -> dict[str, Any]:
    """Ejecuta un ciclo completo: lectura, validación, clasificación, eventos y persistencia."""
    lecturas_crudas = generar_lecturas(ciclo, rng)
    ph = validar_lectura("ph", lecturas_crudas["ph"], PH_MIN_FISICO, PH_MAX_FISICO)
    temperatura_c = validar_lectura(
        "temperatura_c",
        lecturas_crudas["temperatura_c"],
        TEMP_MIN_FISICO,
        TEMP_MAX_FISICO,
    )

    estado_ph = clasificar_ph(ph)
    estado_temp = clasificar_temperatura(temperatura_c)
    estado_general = calcular_estado_general([estado_ph, estado_temp])
    timestamp = obtener_timestamp_iso()

    print(
        f"[Ciclo {ciclo:03d}] {timestamp} | "
        f"pH: {ph:5.2f} ({estado_ph:11s}) | "
        f"Temp: {temperatura_c:5.2f} °C ({estado_temp:11s}) | "
        f"Global: {estado_general}"
    )

    bomba_aireacion, eventos_disparados = evaluar_y_despachar_eventos(
        gestor_eventos,
        ciclo,
        timestamp,
        ph,
        estado_ph,
        temperatura_c,
        estado_temp,
    )

    estado = construir_registro_estado(
        ciclo=ciclo,
        timestamp=timestamp,
        ph=ph,
        estado_ph=estado_ph,
        temperatura_c=temperatura_c,
        estado_temp=estado_temp,
        estado_general=estado_general,
        bomba_aireacion=bomba_aireacion,
        eventos_disparados=eventos_disparados,
    )

    guardar_estado_actual(ruta_json, estado)
    registrar_historial_csv(ruta_csv, estado)
    return estado


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    """Configura y valida los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Simulación y procesamiento de sensores acuícolas para AquaWeb IoT."
    )
    parser.add_argument(
        "--ciclos",
        type=int,
        default=0,
        help="Número de ciclos a ejecutar (0 para ejecución continua hasta Ctrl+C).",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=2.0,
        help="Tiempo de espera en segundos entre lecturas consecutivas (por defecto 2.0).",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=42,
        help="Semilla para el generador aleatorio después de los escenarios iniciales.",
    )
    args = parser.parse_args(argv)

    if args.ciclos < 0:
        raise ValueError("El argumento '--ciclos' debe ser mayor o igual a 0.")
    if not math.isfinite(args.intervalo) or args.intervalo <= 0:
        raise ValueError("El argumento '--intervalo' debe ser un número mayor que 0.")

    return args


def ejecutar_simulacion(
    ciclos: int,
    intervalo: float,
    semilla: int = 42,
    ruta_json: Path = ESTADO_JSON_PATH,
    ruta_csv: Path = HISTORIAL_CSV_PATH,
) -> int:
    """Orquesta el bucle principal de simulación con manejo robusto de excepciones."""
    rng = random.Random(semilla)
    gestor_eventos = construir_gestor_eventos()
    ciclo_actual = 0
    modo_texto = "continuo (Ctrl+C para detener)" if ciclos == 0 else f"{ciclos} ciclos"

    print("=== AquaWeb IoT | Backend de Monitoreo Acuícola ===")
    print(f"Modo: {modo_texto} | Intervalo: {intervalo:.2f} s")
    print(f"JSON estado actual : {ruta_json}")
    print(f"CSV historial      : {ruta_csv}")
    print("-" * 78)

    try:
        while ciclos == 0 or ciclo_actual < ciclos:
            ciclo_actual += 1
            try:
                procesar_ciclo(ciclo_actual, rng, gestor_eventos, ruta_json, ruta_csv)
            except (ValueError, TypeError) as err:
                print(f"[ERROR VALIDACION][Ciclo {ciclo_actual:03d}] {err}", file=sys.stderr)
            except (FileNotFoundError, PermissionError, OSError) as err:
                print(f"[ERROR PERSISTENCIA][Ciclo {ciclo_actual:03d}] {err}", file=sys.stderr)

            if ciclos == 0 or ciclo_actual < ciclos:
                time.sleep(intervalo)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupción recibida (KeyboardInterrupt). Cerrando simulación...")

    print("-" * 78)
    print(f"Simulación finalizada. Ciclos procesados: {ciclo_actual}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI del script de simulación."""
    try:
        args = parsear_argumentos(argv)
    except ValueError as err:
        print(f"[ERROR ARGUMENTOS] {err}", file=sys.stderr)
        return 2

    return ejecutar_simulacion(
        ciclos=args.ciclos,
        intervalo=args.intervalo,
        semilla=args.semilla,
    )


if __name__ == "__main__":
    sys.exit(main())
