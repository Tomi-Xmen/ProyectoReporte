"""
Cuadros de mensaje con los botones en castellano.

Los QMessageBox estándar traen "Yes/No/OK" salvo que se cargue la traducción
de Qt, y esa traducción no siempre viaja dentro del .exe. Armar los botones a
mano evita depender de ella.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def _caja(padre, icono, titulo, texto, detalle=None, al_frente=False):
    caja = QMessageBox(padre)
    if al_frente:
        caja.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    caja.setIcon(icono)
    caja.setWindowTitle(titulo)
    caja.setText(texto)
    caja.setTextFormat(Qt.TextFormat.PlainText)
    if detalle:
        caja.setDetailedText(detalle)
    return caja


def _mostrar(padre, icono, titulo, texto, detalle=None, al_frente=False):
    caja = _caja(padre, icono, titulo, texto, detalle, al_frente)
    caja.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
    caja.exec()


def info(padre, titulo, texto, detalle=None, al_frente=False):
    _mostrar(padre, QMessageBox.Icon.Information, titulo, texto, detalle, al_frente)


def aviso(padre, titulo, texto, detalle=None, al_frente=False):
    _mostrar(padre, QMessageBox.Icon.Warning, titulo, texto, detalle, al_frente)


def error(padre, titulo, texto, detalle=None, al_frente=False):
    _mostrar(padre, QMessageBox.Icon.Critical, titulo, texto, detalle, al_frente)


def confirmar(padre, titulo, texto, si="Sí", no="No"):
    """Pregunta sí/no. Devuelve True solo si se elige 'si'."""
    caja = _caja(padre, QMessageBox.Icon.Question, titulo, texto)
    btn_si = caja.addButton(si, QMessageBox.ButtonRole.YesRole)
    btn_no = caja.addButton(no, QMessageBox.ButtonRole.NoRole)
    caja.setDefaultButton(btn_si)
    caja.setEscapeButton(btn_no)
    caja.exec()
    return caja.clickedButton() is btn_si
