"""Generador manual de etiquetas para equipos defectuosos."""

import webbrowser
from pathlib import Path

from PySide6.QtWidgets import QDialog, QGridLayout, QLineEdit, QVBoxLayout, QWidget

from ...nucleo.etiquetas import generar_etiqueta_manual
from ..componentes import RevisionComponentes
from ..widgets import Tarjeta, area_scroll, boton, etiqueta, fila_botones


class DialogoEtiquetaManual(QDialog):
    def __init__(self, padre):
        super().__init__(padre)
        self.setWindowTitle("Generador manual de etiquetas (equipos defectuosos)")
        self.resize(780, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("🏷️ Generador manual de etiquetas", "titulo-dialogo"))
        layout.addWidget(
            etiqueta(
                "Crea e imprime una etiqueta de diagnóstico sin alterar los reportes "
                "de inventario.",
                "subtitulo",
                ajustar=True,
            )
        )

        contenido = QWidget()
        cuerpo = QVBoxLayout(contenido)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(12)

        datos = Tarjeta()
        datos.cuerpo.addWidget(etiqueta("Datos del equipo", "seccion"))
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(8)
        self.campos = {}
        for i, (clave, texto) in enumerate(
            (
                ("serial", "N° de serie:"),
                ("modelo", "Modelo:"),
                ("cpu", "Procesador (CPU):"),
                ("guia", "N° de guía:"),
                ("ot", "N° de OT:"),
            )
        ):
            entrada = QLineEdit()
            self.campos[clave] = entrada
            fila, col = divmod(i, 2)
            grilla.addWidget(etiqueta(texto, "campo"), fila, col * 2)
            grilla.addWidget(entrada, fila, col * 2 + 1)
        grilla.setColumnStretch(1, 1)
        grilla.setColumnStretch(3, 1)
        datos.cuerpo.addLayout(grilla)
        cuerpo.addWidget(datos)

        revision = Tarjeta()
        revision.cuerpo.addWidget(etiqueta("Revisión de componentes", "seccion"))
        self.revision = RevisionComponentes()
        revision.cuerpo.addWidget(self.revision)
        cuerpo.addWidget(revision)
        cuerpo.addStretch(1)

        layout.addWidget(area_scroll(contenido), 1)
        layout.addLayout(
            fila_botones(
                boton("🖨️ Generar e imprimir etiqueta", self._generar, variante="primario"),
                boton("Cerrar", self.reject),
            )
        )
        self.campos["serial"].setFocus()

    def _generar(self):
        ruta = generar_etiqueta_manual(
            self.campos["serial"].text(),
            self.campos["modelo"].text(),
            self.campos["cpu"].text(),
            self.campos["guia"].text(),
            self.campos["ot"].text(),
            self.revision.detalle(),
        )
        # as_uri() y no f"file://{ruta}": en Windows la ruta empieza con "C:\"
        # y el navegador tomaría "C:" como nombre de host.
        webbrowser.open(Path(ruta).as_uri())


def abrir(ventana):
    DialogoEtiquetaManual(ventana).exec()
    return False
