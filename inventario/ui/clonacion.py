"""
Ventanas del modo clonación (--clonacion sin --sin-ui): la única ventana de
observaciones y los avisos finales. Se cargan solo en ese modo; con --sin-ui
el programa ni siquiera importa Qt.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..nucleo.lotes import etiqueta_lote
from . import avisos
from .componentes import RevisionComponentes, SeccionOffice
from .tema import aplicar_tema
from .widgets import Banner, Tarjeta, area_scroll, boton, etiqueta, fila_botones


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        aplicar_tema(app)
    return app


class VentanaObservaciones(QDialog):
    """
    Muestra lo escaneado y toma la misma revisión de componentes que el
    formulario manual —solo en retiros—, para que esa información quede lista
    al armar la etiqueta del equipo. La fila de Teclado trae un atajo a
    keytest.ru para probarlo sin salir del flujo.

    Cerrar con la X equivale a ENVIAR: el costo de perder el registro de un
    equipo ya clonado es mucho mayor que el de mandarlo sin observaciones. Solo
    'Cancelar' corta el envío. No hay envío automático por tiempo.
    """

    def __init__(self, data, lote):
        super().__init__()
        self.setWindowTitle(f"Registro de equipo — {etiqueta_lote(lote)}")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(720, 640)
        self.setMinimumSize(620, 420)
        self.enviar = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("🖥️ Equipo escaneado", "titulo"))
        layout.addWidget(Banner(etiqueta_lote(lote), "ok"))

        contenido = QWidget()
        cuerpo = QVBoxLayout(contenido)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(12)

        ficha = Tarjeta()
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        for texto, valor in (
            ("Modelo", data.get("model", "?")),
            ("N° de Serie", data.get("serial", "?")),
            ("Procesador", data.get("cpu", "?")),
            ("Licencia Windows", data.get("key", "N/A")),
        ):
            lbl = etiqueta(str(valor), "dato", ajustar=True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(etiqueta(f"{texto}:", "campo"), lbl)
        ficha.cuerpo.addLayout(form)
        cuerpo.addWidget(ficha)

        self.revision = RevisionComponentes(
            "Observación (obligatoria si es OBS/MALO)", test_teclado=True
        )
        if lote.get("mov") == "Retiro":
            tarjeta = Tarjeta()
            tarjeta.cuerpo.addWidget(etiqueta("⚠️ REVISIÓN DE COMPONENTES", "seccion"))
            tarjeta.cuerpo.addWidget(self.revision)
            cuerpo.addWidget(tarjeta)

        extra = Tarjeta()
        extra.cuerpo.addWidget(etiqueta("Observación general (opcional)", "campo"))
        self.txt_obs = QPlainTextEdit()
        self.txt_obs.setFixedHeight(76)
        self.txt_obs.setTabChangesFocus(True)
        extra.cuerpo.addWidget(self.txt_obs)
        self.office = SeccionOffice()
        extra.cuerpo.addWidget(self.office)
        cuerpo.addWidget(extra)
        cuerpo.addStretch(1)
        layout.addWidget(area_scroll(contenido), 1)

        layout.addLayout(
            fila_botones(
                boton("✅ Enviar al servidor", self._enviar, variante="exito", tamano="grande"),
                boton("Cancelar", self._cancelar),
            )
        )
        self.txt_obs.setFocus()

    def _enviar(self):
        self.enviar = True
        self.accept()

    def _cancelar(self):
        self.enviar = False
        self.accept()

    def reject(self):  # Esc o la X: se manda igual
        self.enviar = True
        super().reject()

    def resultado(self):
        tiene_office, office_key, version_office = self.office.valores()
        return (
            self.txt_obs.toPlainText().strip().upper(),
            self.revision.detalle(),
            self.enviar,
            tiene_office,
            office_key,
            version_office,
        )


def pedir_observaciones(data, lote):
    """Misma tupla que nucleo.clonacion._observaciones_consola."""
    _app()
    ventana = VentanaObservaciones(data, lote)
    ventana.exec()
    return ventana.resultado()


# Los avisos van siempre al frente: en el equipo clonado nadie mira la
# consola, así que el resultado tiene que verse sí o sí.
def avisar_error(titulo, detalle):
    _app()
    avisos.error(None, f"❌ {titulo}", detalle, al_frente=True)


def avisar_ok(data, lote):
    _app()
    avisos.info(
        None,
        "✅ Equipo registrado",
        f"{data.get('model')}\nS/N: {data.get('serial')}\n\nEnviado a {etiqueta_lote(lote)}.",
        al_frente=True,
    )
