"""
Trabajo en segundo plano sin congelar la ventana.

El escaneo, el SCP y la API de FOG tardan segundos: si corren en el hilo de
la interfaz, la ventana deja de responder ("No responde" en Windows). Acá se
mandan a un hilo del pool de Qt y el resultado vuelve por señales, que Qt
entrega en el hilo de la interfaz. Ningún widget se toca desde el hilo de
trabajo.
"""

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

# Señales vivas. Si Python recolecta el QObject antes de que el hilo termine,
# la señal se emite al vacío y el resultado se pierde.
_vivas = set()


class _Senales(QObject):
    terminado = Signal(object)
    fallado = Signal(object)
    progreso = Signal(str)


class _Tarea(QRunnable):
    def __init__(self, fn, args, senales, con_progreso):
        super().__init__()
        self.fn, self.args, self.senales = fn, args, senales
        self.con_progreso = con_progreso

    def run(self):
        try:
            if self.con_progreso:
                resultado = self.fn(*self.args, progreso=self.senales.progreso.emit)
            else:
                resultado = self.fn(*self.args)
        except Exception as e:  # se entrega a la UI, que decide cómo mostrarlo
            self.senales.fallado.emit(e)
        else:
            self.senales.terminado.emit(resultado)


def en_segundo_plano(
    fn, *args, al_terminar=None, al_fallar=None, al_progresar=None, con_progreso=False
):
    """
    Corre fn(*args) en otro hilo. Con con_progreso=True, fn recibe además
    progreso=<función> para informar avance con un texto.
    """
    senales = _Senales()
    _vivas.add(senales)

    def _liberar(*_):
        _vivas.discard(senales)

    if al_terminar:
        senales.terminado.connect(al_terminar)
    if al_fallar:
        senales.fallado.connect(al_fallar)
    if al_progresar:
        senales.progreso.connect(al_progresar)
    senales.terminado.connect(_liberar)
    senales.fallado.connect(_liberar)
    QThreadPool.globalInstance().start(_Tarea(fn, args, senales, con_progreso))


class DialogoEspera(QDialog):
    """Modal con barra indeterminada. No se puede cerrar mientras trabaja."""

    def __init__(self, padre, titulo, texto, detalle=""):
        super().__init__(padre)
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self._terminado = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        lbl = QLabel(texto)
        lbl.setProperty("rol", "titulo-dialogo")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        self.lbl_progreso = QLabel(detalle)
        self.lbl_progreso.setProperty("rol", "subtitulo")
        self.lbl_progreso.setWordWrap(True)
        layout.addWidget(self.lbl_progreso)
        barra = QProgressBar()
        barra.setRange(0, 0)
        barra.setTextVisible(False)
        layout.addWidget(barra)

    def fijar_progreso(self, texto):
        self.lbl_progreso.setText(texto)

    def terminar(self):
        self._terminado = True
        self.accept()

    def reject(self):  # Esc no corta el trabajo a medias
        if self._terminado:
            super().reject()

    def closeEvent(self, evento):
        if self._terminado:
            super().closeEvent(evento)
        else:
            evento.ignore()


def con_espera(padre, titulo, texto, fn, *args, detalle="", con_progreso=False):
    """
    Corre fn(*args) en segundo plano mostrando un modal de espera, y devuelve
    su resultado como si fuera una llamada normal (o relanza su excepción).
    La ventana sigue pintándose y respondiendo mientras tanto.
    """
    dlg = DialogoEspera(padre, titulo, texto, detalle)
    salida = {}

    def ok(resultado):
        salida["resultado"] = resultado
        dlg.terminar()

    def mal(exc):
        salida["error"] = exc
        dlg.terminar()

    en_segundo_plano(
        fn,
        *args,
        al_terminar=ok,
        al_fallar=mal,
        al_progresar=dlg.fijar_progreso,
        con_progreso=con_progreso,
    )
    if not salida:  # pudo terminar antes de abrir el modal
        dlg.exec()
    if "error" in salida:
        raise salida["error"]
    return salida.get("resultado")
