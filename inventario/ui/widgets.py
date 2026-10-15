"""
Widgets reutilizables. Ninguno lleva colores propios: se marcan con las
propiedades 'rol', 'variante' y 'estado' que estiliza ui/tema.py.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import tema


def refrescar_estilo(widget):
    """Re-aplica la hoja de estilos tras cambiar una propiedad dinámica."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def etiqueta(texto="", rol=None, ajustar=False, alinear=None):
    lbl = QLabel(texto)
    if rol:
        lbl.setProperty("rol", rol)
    if ajustar:
        lbl.setWordWrap(True)
    if alinear is not None:
        lbl.setAlignment(alinear)
    return lbl


def boton(texto, al_click=None, variante=None, tamano=None):
    btn = QPushButton(texto)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variante:
        btn.setProperty("variante", variante)
    if tamano:
        btn.setProperty("tamano", tamano)
    if al_click:
        btn.clicked.connect(al_click)
    return btn


def fila_botones(*botones, alinear=Qt.AlignmentFlag.AlignCenter):
    """Layout horizontal con los botones dados, centrados por defecto."""
    fila = QHBoxLayout()
    fila.setSpacing(8)
    if alinear in (Qt.AlignmentFlag.AlignCenter, Qt.AlignmentFlag.AlignRight):
        fila.addStretch(1)
    for b in botones:
        fila.addWidget(b)
    if alinear in (Qt.AlignmentFlag.AlignCenter, Qt.AlignmentFlag.AlignLeft):
        fila.addStretch(1)
    return fila


class Banner(QLabel):
    """Franja de estado (ok / aviso / error / info) con texto centrado."""

    def __init__(self, texto="", estado="info"):
        super().__init__(texto)
        self.setProperty("rol", "banner")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fijar(texto, estado)

    def fijar(self, texto, estado):
        self.setText(texto)
        self.setProperty("estado", estado)
        refrescar_estilo(self)


class Tarjeta(QFrame):
    """Panel con fondo de superficie, borde suave y esquinas redondeadas."""

    def __init__(self, estado=None, margen=16, espacio=8):
        super().__init__()
        self.setProperty("rol", "tarjeta")
        if estado:
            self.setProperty("estado", estado)
        self.cuerpo = QVBoxLayout(self)
        self.cuerpo.setContentsMargins(margen, margen, margen, margen)
        self.cuerpo.setSpacing(espacio)

    def fijar_estado(self, estado):
        self.setProperty("estado", estado)
        refrescar_estilo(self)


class TarjetaAccion(QPushButton):
    """
    Acción del menú: ícono con el color de su grupo, título y una línea de
    descripción. Es un QPushButton para heredar foco, teclado y accesibilidad.
    """

    def __init__(self, icono, titulo, descripcion, acento, al_click):
        super().__init__()
        self.setProperty("rol", "tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(titulo)
        self.setMinimumHeight(68)
        self.clicked.connect(al_click)

        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 10, 12, 10)
        fila.setSpacing(12)

        lbl_icono = QLabel(icono)
        lbl_icono.setFixedSize(40, 40)
        lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icono.setStyleSheet(
            f"background: {tema.rgba(acento, 0.16)}; border-radius: 10px;"
            "font-size: 18px;"
        )
        fila.addWidget(lbl_icono, 0, Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.lbl_titulo = etiqueta(titulo, "tile-titulo")
        self.lbl_desc = etiqueta(descripcion, "tile-desc", ajustar=True)
        textos.addWidget(self.lbl_titulo)
        textos.addWidget(self.lbl_desc)
        fila.addLayout(textos, 1)

        for w in (lbl_icono, self.lbl_titulo, self.lbl_desc):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def fijar_titulo(self, titulo):
        self.lbl_titulo.setText(titulo)
        self.setAccessibleName(titulo)


def area_scroll(contenido):
    """Envuelve 'contenido' en un área con scroll vertical sin marco."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(contenido)
    return area


def tabla(columnas, seleccion_multiple=False, estirar=None):
    """
    Tabla de solo lectura, selección por fila. 'columnas' es una lista de
    (encabezado, ancho); ancho None = se estira. 'estirar' fuerza qué columna
    ocupa el espacio sobrante (por defecto, la última sin ancho).
    """
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels([c[0] for c in columnas])
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
        if seleccion_multiple
        else QAbstractItemView.SelectionMode.SingleSelection
    )
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(30)
    t.setWordWrap(False)
    cabecera = t.horizontalHeader()
    cabecera.setHighlightSections(False)
    cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for i, (_txt, ancho) in enumerate(columnas):
        if ancho:
            cabecera.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            t.setColumnWidth(i, ancho)
        else:
            cabecera.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
    if estirar is not None:
        cabecera.setSectionResizeMode(estirar, QHeaderView.ResizeMode.Stretch)
    return t


def agregar_fila(t, valores, centradas=()):
    """Agrega una fila de textos y devuelve su índice."""
    fila = t.rowCount()
    t.insertRow(fila)
    for col, valor in enumerate(valores):
        item = QTableWidgetItem(str(valor))
        if col in centradas:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(fila, col, item)
    return fila


def filas_seleccionadas(t):
    return sorted({i.row() for i in t.selectionModel().selectedRows()})
