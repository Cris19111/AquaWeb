#!/usr/bin/env python3
"""Generador automático del informe técnico en DOCX para AquaWeb IoT (Avance 3).

Aplica formato académico estricto:
- Fuente: Arial 12 pt en todo el documento (párrafos, encabezados y tablas)
- Alineación: Texto justificado (WD_ALIGN_PARAGRAPH.JUSTIFY)
- Márgenes: 2.54 cm en los cuatro lados
- Límite objetivo: <= 5 páginas al exportar a PDF
"""

from __future__ import annotations

from pathlib import Path
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
SALIDA_DOCX = BASE_DIR / "Informe_Avance3_AquaWeb_IoT.docx"


def aplicar_fuente_arial_12(run, negrita: bool = False, color: RGBColor | None = None) -> None:
    """Configura estrictamente Arial 12 pt en un run XML de Word."""
    run.font.name = "Arial"
    run.font.size = Pt(12)
    run.bold = negrita
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(attr), "Arial")


def configurar_estilo_base(doc: Document) -> None:
    """Fija márgenes de 2.54 cm y estilo Normal en Arial 12 justificado."""
    for sec in doc.sections:
        sec.page_width = Cm(21.59)   # Carta (Letter) estándar UTP
        sec.page_height = Cm(27.94)
        sec.top_margin = Cm(2.54)
        sec.bottom_margin = Cm(2.54)
        sec.left_margin = Cm(2.54)
        sec.right_margin = Cm(2.54)

    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(12)
    estilo.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    estilo.paragraph_format.space_before = Pt(0)
    estilo.paragraph_format.space_after = Pt(2)
    estilo.paragraph_format.line_spacing = 1.0


def agregar_parrafo(
    doc: Document,
    texto: str,
    negrita: bool = False,
    space_before: float = 0,
    space_after: float = 2,
    keep_with_next: bool = False,
    color: RGBColor | None = None,
):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = 1.0
    pf.keep_with_next = keep_with_next
    run = p.add_run(texto)
    aplicar_fuente_arial_12(run, negrita=negrita, color=color)
    return p


def agregar_encabezado_seccion(doc: Document, titulo: str) -> None:
    agregar_parrafo(
        doc,
        titulo,
        negrita=True,
        space_before=5,
        space_after=2,
        keep_with_next=True,
        color=RGBColor(0x1B, 0x4F, 0x72),
    )


def agregar_campo_etiqueta(doc: Document, etiqueta: str, valor: str, space_after: float = 2) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.02
    r1 = p.add_run(etiqueta)
    aplicar_fuente_arial_12(r1, negrita=True)
    r2 = p.add_run(valor)
    aplicar_fuente_arial_12(r2, negrita=False)


def estilizar_celda(cell, texto: str, negrita: bool = False, fondo_hex: str | None = None) -> None:
    if fondo_hex:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fondo_hex)
        tcPr.append(shd)

    # Márgenes internos compactos para mantener <= 5 páginas con Arial 12
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for lado, dxa in (("top", "28"), ("bottom", "28"), ("left", "55"), ("right", "55")):
        node = OxmlElement(f"w:{lado}")
        node.set(qn("w:w"), dxa)
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)

    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(texto)
    aplicar_fuente_arial_12(r, negrita=negrita)


def agregar_tabla(doc: Document, encabezados: list[str], filas: list[list[str]], anchos_cm: list[float]) -> None:
    tabla = doc.add_table(rows=1 + len(filas), cols=len(encabezados))
    tabla.style = "Table Grid"
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabla.autofit = False

    # Encabezado
    for idx, titulo in enumerate(encabezados):
        celda = tabla.rows[0].cells[idx]
        celda.width = Cm(anchos_cm[idx])
        estilizar_celda(celda, titulo, negrita=True, fondo_hex="D9E2F3")

    # Filas de datos
    for r_idx, fila in enumerate(filas, start=1):
        trPr = tabla.rows[r_idx]._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        for c_idx, val in enumerate(fila):
            celda = tabla.rows[r_idx].cells[c_idx]
            celda.width = Cm(anchos_cm[c_idx])
            estilizar_celda(celda, val, negrita=False, fondo_hex="F9FAFB" if r_idx % 2 == 0 else None)


def agregar_imagen_con_pie(doc: Document, ruta_img: Path, ancho_cm: float, pie: str) -> None:
    if ruta_img.exists():
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.paragraph_format.space_before = Pt(2)
        p_img.paragraph_format.space_after = Pt(1)
        p_img.paragraph_format.keep_with_next = True
        p_img.add_run().add_picture(str(ruta_img), width=Cm(ancho_cm))
        agregar_parrafo(doc, pie, negrita=True, space_before=0, space_after=3)


def construir_documento() -> Path:
    doc = Document()
    configurar_estilo_base(doc)

    # ------------------------------------------------------------------
    # 1. HOJA DE PRESENTACIÓN (Página 1)
    # ------------------------------------------------------------------
    agregar_parrafo(doc, "UNIVERSIDAD TECNOLÓGICA DE PANAMÁ", negrita=True, space_before=12, space_after=4)
    agregar_parrafo(
        doc,
        "FACULTAD DE INGENIERÍA DE SISTEMAS COMPUTACIONALES",
        negrita=True,
        space_after=4,
    )
    agregar_parrafo(
        doc,
        "LICENCIATURA EN DESARROLLO Y GESTIÓN DE SOFTWARE",
        negrita=False,
        space_after=18,
    )
    agregar_parrafo(
        doc,
        "AquaWeb IoT – Avance 3: Módulo de Comunicación MQTT",
        negrita=True,
        space_before=10,
        space_after=16,
        color=RGBColor(0x1B, 0x4F, 0x72),
    )

    agregar_campo_etiqueta(doc, "Asignatura: ", "Desarrollo de Software VIII", space_after=6)
    agregar_campo_etiqueta(doc, "Docente: ", "Prof. José Collado", space_after=6)
    agregar_campo_etiqueta(doc, "Grupo MQTT: ", "grupo (DS8 — utp/ds8/grupo/aquaweb/#)", space_after=6)
    agregar_campo_etiqueta(doc, "Fecha de entrega: ", "25 de noviembre de 2026", space_after=12)

    agregar_parrafo(doc, "Integrante y Cédula:", negrita=True, space_after=4)
    agregar_parrafo(doc, "1. Cristian Joel Pinto Ortega — Cédula: 8-1015-1885", space_after=14)

    agregar_campo_etiqueta(
        doc,
        "Repositorio GitHub: ",
        "https://github.com/Cris19111/AquaWeb",
        space_after=6,
    )
    agregar_campo_etiqueta(
        doc,
        "Simulación Wokwi (ESP32): ",
        "Archivos wokwi/diagram.json, wokwi/main.py y wokwi/umqtt_simple.py.",
        space_after=12,
    )

    agregar_parrafo(
        doc,
        "Resumen ejecutivo: Este entregable documenta la implementación y verificación del "
        "módulo de comunicación bidireccional MQTT para AquaWeb IoT (monitoreo y control "
        "determinístico de estanques camaroneros en Panamá, sin IA/ML), conectando el nodo "
        "ESP32 en MicroPython con el receptor de telemetría y el monitor de estado en Python 3.",
        space_before=6,
        space_after=4,
    )

    doc.add_page_break()

    # ------------------------------------------------------------------
    # 2. DESCRIPCIÓN BREVE DEL MÓDULO DE COMUNICACIÓN
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "2. Descripción del Módulo de Comunicación en AquaWeb IoT")
    agregar_parrafo(
        doc,
        "El módulo enlaza el nodo ESP32 (Wokwi, MicroPython v1.20+) con el backend Python 3 "
        "mediante broker.hivemq.com:1883 bajo el prefijo utp/ds8/grupo/aquaweb/. El nodo mide "
        "pH (GPIO 34, ADC.ATTN_11DB) y temperatura (DHT22 en GPIO 15), acciona la bomba (LED "
        "rojo GPIO 2), indica conectividad (LED azul GPIO 5) y atiende un botón de bypass manual "
        "(GPIO 4 con IRQ_RISING y debounce de 250 ms). Registra Last Will (OFFLINE, QoS 1, "
        "retenido) antes de connect(), publica telemetría cada 5 s con ticks_ms(), mantiene "
        "ping() en silencio y aplica backoff exponencial (2 a 60 s) conservando control local.",
        space_after=3,
    )
    agregar_parrafo(
        doc,
        "En Python (paho-mqtt >= 2.1.0, CallbackAPIVersion.VERSION2), receptor_mqtt.py se "
        "suscribe a utp/ds8/grupo/aquaweb/# (QoS 0), valida JSON, tipos y rangos físicos y "
        "guarda lecturas válidas en telemetria_valida.csv. De forma independiente, "
        "monitor_estado.py evalúa cada 1 s el silencio máximo (20 s) y registra únicamente "
        "transiciones entre ONLINE, SIN_DATOS y OFFLINE en eventos_comunicacion.csv.",
        space_after=3,
    )

    # ------------------------------------------------------------------
    # 3. ESQUEMA DE TEMAS MQTT Y EJEMPLOS DE MENSAJES JSON
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "3. Esquema de Temas MQTT (QoS Verificado en Código)")
    agregar_tabla(
        doc,
        ["Tema MQTT", "Dirección", "QoS", "Retenido", "Contenido / Formato"],
        [
            [
                "utp/ds8/grupo/aquaweb/telemetria",
                "Dispositivo → Broker",
                "0 (pub ESP32 / sub backend)",
                "No",
                "JSON: ph, temperatura, actuador, modo, umbrales",
            ],
            [
                "utp/ds8/grupo/aquaweb/estado",
                "Dispositivo → Broker",
                "1 (ONLINE, LWT y sub monitor)",
                "Sí",
                "\"ONLINE\" al conectar / \"OFFLINE\" por LWT del broker",
            ],
            [
                "utp/ds8/grupo/aquaweb/ordenes",
                "Broker → Dispositivo",
                "1 (CLI) / 0 (sub ESP32)",
                "No",
                "JSON: modo, actuador, umbrales o simular_silencio",
            ],
        ],
        [4.9, 2.7, 2.7, 1.5, 4.7],
    )
    agregar_campo_etiqueta(
        doc,
        "Telemetría (QoS 0): ",
        '{"ph": 7.85, "temperatura": 26.4, "actuador": 0, "modo": "AUTO", "umbral_ph_min": 6.5, "umbral_ph_max": 9.5}',
        space_after=1,
    )
    agregar_campo_etiqueta(
        doc,
        "Orden válida: ",
        '{"modo": "MANUAL", "actuador": 1}  |  {"umbral_ph_min": 7.0, "umbral_ph_max": 8.5}',
        space_after=1,
    )
    agregar_campo_etiqueta(
        doc,
        "Estado (QoS 1, retenido): ",
        '"ONLINE" (al conectar) / "OFFLINE" (disparado por LWT del broker al vencer keepalive=15s).',
        space_after=3,
    )

    # ------------------------------------------------------------------
    # 4. DIAGRAMA DE FLUJO DE DATOS
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "4. Diagrama de Flujo de Datos")
    agregar_imagen_con_pie(
        doc,
        ASSETS_DIR / "diagrama_flujo.png",
        ancho_cm=9.4,
        pie="Figura 1. Flujo de datos MQTT del Avance 3 (ESP32, broker, receptor, monitor y emisor CLI).",
    )

    # ------------------------------------------------------------------
    # 5. TABLA DE PRUEBAS (8 ESCENARIOS OBLIGATORIOS)
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "5. Pruebas del Módulo de Comunicación (8 Escenarios)")
    agregar_tabla(
        doc,
        ["Escenario", "Cómo se provocó", "Resultado esperado / observado", "Verificación"],
        [
            [
                "1. Normal",
                "Receptor y monitor en broker.hivemq.com con ráfaga desde emisor CLI.",
                "ONLINE retenido y 4 filas válidas guardadas en CSV sin duplicar estado.",
                "Ejecutado (CLI → Backend)",
            ],
            [
                "2. Orden válida",
                "Emisor CLI envía MANUAL/AUTO y umbrales 7.0–8.5 a .../ordenes.",
                "Tráfico en broker confirmado; validar_y_aplicar_orden() actualiza GPIO 2.",
                "CLI → Broker + Verificado en firmware",
            ],
            [
                "3. Orden inválida",
                "Emisor CLI envía JSON roto, modo TURBO, actuador 9 y min>max.",
                "4 órdenes rechazadas ([ORDEN RECHAZADA]) sin alterar estado_sistema.",
                "CLI → Broker + Verificado en firmware",
            ],
            [
                "4. Caída red / backoff",
                "Revisión de try/except OSError y backoff 2..60 s (provocable con host inválido).",
                "Progresión 2,4,8,16,32,60 s no bloqueante manteniendo muestreo e IRQ GPIO 4.",
                "Verificado en firmware / razonado",
            ],
            [
                "5. Dato inválido",
                "Emisor CLI inyecta 5 tramas corruptas (pH 19.5, Temp 95, sin campos).",
                "Receptor imprime 5 descartes, sigue activo y no contamina telemetria_valida.csv.",
                "Ejecutado (CLI → Backend)",
            ],
            [
                "6. Reinicio nodo",
                "Inspección de main() -> conectar_mqtt() en wokwi/main.py.",
                "Registra LWT QoS 1 antes de connect(), suscribe órdenes y publica ONLINE.",
                "Verificado en firmware / razonado",
            ],
            [
                "7. Silencio (SIN_DATOS)",
                "Pausa de 23 s (>20 s). En ESP32 equivale a simular_silencio con ping() cada 7 s.",
                "Monitor registra SIN_DATOS a los 20.6 s y vuelve a ONLINE al reanudar.",
                "Ejecutado (CLI → Backend) + firmware",
            ],
            [
                "8. Detención (OFFLINE)",
                "Recepción OFFLINE en .../estado. En Wokwi lo dispara el broker vía LWT al detener simulación.",
                "Transición #4 ONLINE -> OFFLINE (CRITICO); 4 filas totales en eventos CSV.",
                "Ejecutado (CLI → Backend) + LWT QoS 1",
            ],
        ],
        [2.7, 4.4, 5.8, 3.6],
    )

    # ------------------------------------------------------------------
    # 6. CAPTURAS DE EVIDENCIA
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "6. Evidencias de Ejecución")
    captura_wokwi_real = ASSETS_DIR / "captura_wokwi_telemetria_ordenes.png"
    if captura_wokwi_real.exists():
        agregar_imagen_con_pie(
            doc,
            captura_wokwi_real,
            ancho_cm=10.2,
            pie="Figura 2. Ejecución real en Wokwi: telemetría ESP32, orden válida aplicada (LED rojo) y orden inválida rechazada.",
        )
    else:
        agregar_parrafo(
            doc,
            "Nota de evidencia Wokwi: Para incrustar la captura real del simulador ESP32 "
            "(telemetría, orden válida aplicada y orden inválida rechazada), guardar el archivo "
            "docs/assets/captura_wokwi_telemetria_ordenes.png y re-ejecutar generar_informe_docx.py.",
            space_after=2,
        )

    agregar_imagen_con_pie(
        doc,
        ASSETS_DIR / "captura_receptor.png",
        ancho_cm=8.2,
        pie="Figura 2. Consola de receptor_mqtt.py: 4 lecturas válidas en CSV y 5 tramas inválidas descartadas del emisor CLI."
        if not captura_wokwi_real.exists()
        else "Figura 3. Consola de receptor_mqtt.py: lecturas válidas en CSV y tramas inválidas descartadas.",
    )
    agregar_imagen_con_pie(
        doc,
        ASSETS_DIR / "captura_monitor.png",
        ancho_cm=8.5,
        pie="Figura 3. Consola de monitor_estado.py y eventos_comunicacion.csv: transiciones ONLINE, SIN_DATOS y OFFLINE."
        if not captura_wokwi_real.exists()
        else "Figura 4. Consola de monitor_estado.py y eventos_comunicacion.csv: transiciones ONLINE, SIN_DATOS y OFFLINE (LWT real).",
    )

    # ------------------------------------------------------------------
    # 7. DIFICULTADES ENCONTRADAS Y CÓMO SE RESOLVIERON
    # ------------------------------------------------------------------
    agregar_encabezado_seccion(doc, "7. Dificultades Encontradas y Soluciones")
    dificultades = [
        "1. Atenuación ADC en MicroPython v1.20+: Se configuró explícitamente adc.atten(ADC.ATTN_11DB) (nunca ATTN_11V) y 12 bits para cubrir 0–3.3 V sin saturación.",
        "2. Migración a paho-mqtt v2: Se adoptó CallbackAPIVersion.VERSION2 y firmas actualizadas de on_connect/on_disconnect en los tres scripts Python.",
        "3. Red no bloqueante y sockets en umqtt: Se usaron temporizadores ticks_ms()/ticks_diff() con backoff 2–60 s para no bloquear sensores ni la IRQ GPIO 4.",
        "4. Validación estricta y rigor QoS: Se excluyeron booleanos y NaN/Inf en JSON y se alineó la documentación con el QoS real implementado (0 en telemetría, 1 en estado/LWT).",
    ]
    for item in dificultades:
        agregar_parrafo(doc, item, space_after=1)

    doc.save(SALIDA_DOCX)
    print(f"Documento generado exitosamente: {SALIDA_DOCX}")
    return SALIDA_DOCX


if __name__ == "__main__":
    construir_documento()
