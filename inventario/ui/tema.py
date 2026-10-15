"""
Tema visual de la app (Qt): paleta, tipografía y hoja de estilos.

Todo color de la interfaz sale de acá. Los widgets no llevan colores fijos:
se marcan con propiedades ('rol', 'variante', 'estado') y la hoja de estilos
decide cómo se ven. Así el modo oscuro, o un cambio de marca, se resuelve en
este archivo y en ningún otro.

NO afecta al REPORTE HTML: ese tiene sus propios colores en
nucleo/reporte_html.py.
"""

import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap

CLARO = {
    "fondo": "#f1f5f9",          # fondo general (slate-100)
    "superficie": "#ffffff",     # tarjetas, tablas, campos
    "superficie_alt": "#f8fafc",  # filas alternas, hover suave
    "borde": "#e2e8f0",
    "borde_fuerte": "#cbd5e1",
    "texto": "#0f172a",
    "texto_sec": "#475569",
    "texto_tenue": "#64748b",
    "marca": "#1e3a8a",          # azul de marca (títulos)
    "primario": "#2563eb",
    "primario_hover": "#1d4ed8",
    "sobre_color": "#ffffff",    # texto sobre botones de color
    "deshabilitado": "#e2e8f0",
    "texto_deshabilitado": "#94a3b8",
    "ok_fondo": "#dcfce7",
    "ok_texto": "#166534",
    "aviso_fondo": "#fef3c7",
    "aviso_texto": "#92400e",
    "error_fondo": "#fee2e2",
    "error_texto": "#b91c1c",
    "info_fondo": "#dbeafe",
    "info_texto": "#1d4ed8",
    # Acentos: el color agrupa, no decora. Dos acciones del mismo color hacen
    # cosas del mismo tipo.
    "celeste": "#0284c7",        # manejo de la OT
    "verde": "#16a34a",          # cerrar / confirmar
    "naranja": "#d97706",        # sale de esta máquina
    "morado": "#7c3aed",         # reparación
    "esmeralda": "#059669",      # clonación
    "pizarra": "#475569",        # utilitarios sueltos
}

OSCURO = {
    "fondo": "#0b1220",
    "superficie": "#111a2e",
    "superficie_alt": "#16213a",
    "borde": "#1e293b",
    "borde_fuerte": "#334155",
    "texto": "#e2e8f0",
    "texto_sec": "#94a3b8",
    "texto_tenue": "#7c8aa3",
    "marca": "#93c5fd",
    "primario": "#3b82f6",
    "primario_hover": "#60a5fa",
    "sobre_color": "#ffffff",
    "deshabilitado": "#1e293b",
    "texto_deshabilitado": "#64748b",
    "ok_fondo": "#0b3a22",
    "ok_texto": "#86efac",
    "aviso_fondo": "#3d2c06",
    "aviso_texto": "#fcd34d",
    "error_fondo": "#3f1212",
    "error_texto": "#fca5a5",
    "info_fondo": "#13284d",
    "info_texto": "#93c5fd",
    "celeste": "#38bdf8",
    "verde": "#22c55e",
    "naranja": "#f59e0b",
    "morado": "#a78bfa",
    "esmeralda": "#34d399",
    "pizarra": "#94a3b8",
}

# Tokens en uso. aplicar_tema() los fija según el esquema del sistema.
COLORES = dict(CLARO)


def color(nombre):
    return COLORES[nombre]


def rgba(nombre, alfa):
    """Color del tema con transparencia, en formato QSS (alfa 0..1)."""
    c = QColor(COLORES[nombre])
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alfa})"


def es_oscuro():
    return COLORES["fondo"] == OSCURO["fondo"]


def _ajustar(hex_color, factor):
    """Aclara (factor > 0) u oscurece (factor < 0) un color hex."""
    c = QColor(hex_color)
    r, g, b = c.red(), c.green(), c.blue()
    if factor >= 0:
        r, g, b = (int(v + (255 - v) * factor) for v in (r, g, b))
    else:
        r, g, b = (int(v * (1 + factor)) for v in (r, g, b))
    return QColor(r, g, b).name()


def familia_monoespaciada():
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def _flechas(c):
    """
    Flechas de combos y spinners como PNG temporales. La hoja de estilos solo
    acepta imágenes por ruta, y al estilizar el borde del combo Qt deja de
    dibujar la flecha nativa: sin esto el desplegable no parece desplegable.
    """
    carpeta = os.path.join(tempfile.gettempdir(), "inventario_tema")
    os.makedirs(carpeta, exist_ok=True)
    rutas = {}
    for nombre, puntos in (
        ("abajo", ((5, 9), (12, 16), (19, 9))),
        ("arriba", ((5, 15), (12, 8), (19, 15))),
    ):
        ruta = os.path.join(carpeta, f"{nombre}_{c['texto_sec'].lstrip('#')}.png")
        if not os.path.exists(ruta):
            img = QPixmap(24, 24)
            img.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(img)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            lapiz = QPen(QColor(c["texto_sec"]), 2.6)
            lapiz.setCapStyle(Qt.PenCapStyle.RoundCap)
            lapiz.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pintor.setPen(lapiz)
            pintor.drawPolyline([QPointF(x, y) for x, y in puntos])
            pintor.end()
            img.save(ruta, "PNG")
        rutas[nombre] = ruta.replace("\\", "/")
    return rutas


def _hoja_de_estilos(c):
    flechas = _flechas(c)
    # Los botones de color usan siempre los acentos del modo claro: llevan
    # texto blanco, y los acentos claros del modo oscuro (pensados para
    # íconos y texto sobre fondo oscuro) lo dejarían ilegible.
    variantes = {
        "primario": c["primario"],
        "exito": CLARO["verde"],
        "ot": CLARO["celeste"],
        "envio": CLARO["naranja"],
        "reparar": CLARO["morado"],
        "clonacion": CLARO["esmeralda"],
        "utilidad": CLARO["pizarra"],
        "marca": CLARO["marca"] if not es_oscuro() else c["primario"],
    }
    botones = ""
    for nombre, base in variantes.items():
        hover = _ajustar(base, 0.12 if es_oscuro() else -0.12)
        presionado = _ajustar(base, -0.2)
        botones += f"""
QPushButton[variante="{nombre}"] {{
    background: {base}; color: {c['sobre_color']}; border: 1px solid {base};
}}
QPushButton[variante="{nombre}"]:hover {{ background: {hover}; border-color: {hover}; }}
QPushButton[variante="{nombre}"]:pressed {{ background: {presionado}; }}
"""

    return f"""
* {{ outline: 0; }}
QWidget {{ color: {c['texto']}; }}
QMainWindow, QDialog, QWidget#pagina {{ background: {c['fondo']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLabel[rol="titulo"] {{ font-size: 20px; font-weight: 700; color: {c['marca']}; }}
QLabel[rol="titulo-dialogo"] {{ font-size: 16px; font-weight: 700; color: {c['marca']}; }}
QLabel[rol="subtitulo"] {{ color: {c['texto_tenue']}; }}
QLabel[rol="seccion"] {{
    color: {c['texto_tenue']}; font-size: 11px; font-weight: 700;
    letter-spacing: 1px; padding-top: 8px;
}}
QLabel[rol="campo"] {{ font-weight: 600; color: {c['texto_sec']}; }}
QLabel[rol="ayuda"] {{ color: {c['texto_tenue']}; font-size: 11px; }}
QLabel[rol="dato"] {{ color: {c['marca']}; }}
QLabel[rol="ruta"] {{ color: {c['marca']}; font-weight: 600; }}

QLabel[rol="banner"] {{ border-radius: 10px; padding: 10px 14px; font-weight: 600; }}
QLabel[rol="banner"][estado="ok"] {{ background: {c['ok_fondo']}; color: {c['ok_texto']}; }}
QLabel[rol="banner"][estado="aviso"] {{ background: {c['aviso_fondo']}; color: {c['aviso_texto']}; }}
QLabel[rol="banner"][estado="error"] {{ background: {c['error_fondo']}; color: {c['error_texto']}; }}
QLabel[rol="banner"][estado="info"] {{ background: {c['info_fondo']}; color: {c['info_texto']}; }}

QFrame[rol="tarjeta"] {{
    background: {c['superficie']}; border: 1px solid {c['borde']}; border-radius: 12px;
}}
QFrame[rol="tarjeta"][estado="ok"] {{ border-left: 4px solid {c['verde']}; }}
QFrame[rol="tarjeta"][estado="aviso"] {{ border-left: 4px solid {c['naranja']}; }}
QFrame[rol="tarjeta"] QLabel {{ background: transparent; }}

QPushButton {{
    background: {c['superficie']}; color: {c['texto']};
    border: 1px solid {c['borde_fuerte']}; border-radius: 8px;
    padding: 7px 16px; font-weight: 600;
}}
QPushButton:hover {{ background: {c['superficie_alt']}; border-color: {c['texto_tenue']}; }}
QPushButton:pressed {{ background: {c['borde']}; }}
QPushButton:disabled {{
    background: {c['deshabilitado']}; color: {c['texto_deshabilitado']};
    border-color: {c['deshabilitado']};
}}
QPushButton[tamano="grande"] {{ font-size: 15px; padding: 14px 20px; border-radius: 10px; }}
QPushButton[variante="fantasma"] {{ background: transparent; border-color: transparent; color: {c['texto_sec']}; }}
QPushButton[variante="fantasma"]:hover {{ background: {c['borde']}; }}
{botones}
QPushButton[rol="tile"] {{
    background: {c['superficie']}; border: 1px solid {c['borde']};
    border-radius: 12px; padding: 0; text-align: left;
}}
QPushButton[rol="tile"]:hover {{ border-color: {c['primario']}; background: {c['superficie_alt']}; }}
QPushButton[rol="tile"]:pressed {{ background: {c['borde']}; }}
QPushButton[rol="tile"] QLabel {{ background: transparent; }}
QLabel[rol="tile-titulo"] {{ font-weight: 700; }}
QLabel[rol="tile-desc"] {{ color: {c['texto_tenue']}; font-size: 11px; }}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background: {c['superficie']}; border: 1px solid {c['borde_fuerte']};
    border-radius: 7px; padding: 6px 8px;
    selection-background-color: {c['primario']}; selection-color: {c['sobre_color']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {c['primario']};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background: {c['fondo']}; color: {c['texto_deshabilitado']}; border-color: {c['borde']};
}}
QLineEdit[rol="clave"] {{ font-family: "{familia_monoespaciada()}"; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{flechas['abajo']}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: none; }}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: url("{flechas['arriba']}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{flechas['abajo']}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {c['superficie']}; border: 1px solid {c['borde_fuerte']};
    selection-background-color: {c['primario']}; selection-color: {c['sobre_color']};
}}

QCheckBox {{ font-weight: 600; spacing: 8px; }}

QTableWidget {{
    background: {c['superficie']}; alternate-background-color: {c['superficie_alt']};
    border: 1px solid {c['borde']}; border-radius: 10px; gridline-color: transparent;
    selection-background-color: {rgba('primario', 0.18)}; selection-color: {c['texto']};
}}
QTableWidget::item {{ padding: 4px 8px; }}
QHeaderView::section {{
    background: {c['superficie']}; color: {c['texto_sec']}; font-weight: 700;
    border: none; border-bottom: 1px solid {c['borde']}; padding: 8px;
}}
QTableCornerButton::section {{ background: {c['superficie']}; border: none; }}

QProgressBar {{
    background: {c['borde']}; border: none; border-radius: 4px; max-height: 8px;
}}
QProgressBar::chunk {{ background: {c['primario']}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['borde_fuerte']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['texto_tenue']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['borde_fuerte']}; border-radius: 4px; min-width: 30px; }}

QMessageBox {{ background: {c['fondo']}; }}
QToolTip {{
    background: {c['superficie']}; color: {c['texto']};
    border: 1px solid {c['borde_fuerte']}; padding: 4px;
}}
"""


def _paleta(c):
    """Paleta base de Fusion: cubre lo que la hoja de estilos no toca."""
    p = QPalette()
    for rol, token in (
        (QPalette.ColorRole.Window, "fondo"),
        (QPalette.ColorRole.WindowText, "texto"),
        (QPalette.ColorRole.Base, "superficie"),
        (QPalette.ColorRole.AlternateBase, "superficie_alt"),
        (QPalette.ColorRole.Text, "texto"),
        (QPalette.ColorRole.Button, "superficie"),
        (QPalette.ColorRole.ButtonText, "texto"),
        (QPalette.ColorRole.Highlight, "primario"),
        (QPalette.ColorRole.HighlightedText, "sobre_color"),
        (QPalette.ColorRole.ToolTipBase, "superficie"),
        (QPalette.ColorRole.ToolTipText, "texto"),
        (QPalette.ColorRole.PlaceholderText, "texto_tenue"),
        (QPalette.ColorRole.Link, "primario"),
    ):
        p.setColor(rol, QColor(c[token]))
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(c["texto_deshabilitado"]),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(c["texto_deshabilitado"]),
    )
    return p


def aplicar_tema(app, oscuro=None):
    """
    Fija estilo, fuente, paleta y hoja de estilos. Sin 'oscuro' explícito se
    sigue el modo claro/oscuro del sistema operativo.
    """
    if oscuro is None:
        oscuro = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    COLORES.clear()
    COLORES.update(OSCURO if oscuro else CLARO)

    app.setStyle("Fusion")
    fuente = QFont(app.font())
    if "Segoe UI" in QFontDatabase.families():
        fuente.setFamily("Segoe UI")
    fuente.setPointSize(10)
    app.setFont(fuente)
    app.setPalette(_paleta(COLORES))
    app.setStyleSheet(_hoja_de_estilos(COLORES))
