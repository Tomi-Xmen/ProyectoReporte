"""
Bloques de formulario que se repiten en varias pantallas: la revisión de
componentes (retiros, etiqueta manual, modo clonación) y el registro de
Office.
"""

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .widgets import boton, etiqueta

COMPONENTES = [
    "Carcaza",
    "Pantalla",
    "Teclado",
    "Touchpad",
    "Puertos USB",
    "Puertos Video",
    "Ethernet/Wi-Fi",
    "Placa base",
    "Memoria",
    "Disco duro",
    "Batería",
]
ESTADOS = ["OK", "OBS", "MALO"]
VERSIONES_OFFICE = ["2013", "2016", "2019", "2021", "2024", "365"]
URL_TEST_TECLADO = "https://keytest.ru/old.html"


class RevisionComponentes(QWidget):
    """
    Grilla componente / estado / observación. La observación se habilita solo
    cuando el estado deja de ser OK, y se vacía al volver a OK.
    """

    def __init__(self, texto_obs="Observación (si es OBS/MALO)", test_teclado=False):
        super().__init__()
        grilla = QGridLayout(self)
        grilla.setContentsMargins(0, 0, 0, 0)
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(6)
        grilla.addWidget(etiqueta("Componente", "campo"), 0, 0)
        grilla.addWidget(etiqueta("Estado", "campo"), 0, 1)
        grilla.addWidget(etiqueta(texto_obs, "campo"), 0, 2)
        grilla.setColumnStretch(2, 1)

        self._filas = []
        for i, nombre in enumerate(COMPONENTES, start=1):
            lbl = etiqueta(nombre)
            combo = QComboBox()
            combo.addItems(ESTADOS)
            combo.setMinimumWidth(86)
            obs = QLineEdit()
            obs.setEnabled(False)
            combo.currentTextChanged.connect(
                lambda estado, o=obs: self._al_cambiar_estado(estado, o)
            )
            grilla.addWidget(lbl, i, 0)
            grilla.addWidget(combo, i, 1)
            grilla.addWidget(obs, i, 2)

            # El teclado es el único componente con una herramienta externa de
            # prueba a mano: keytest.ru muestra en pantalla qué tecla se
            # apretó. El rótulo queda marcado como recordatorio de "ya lo
            # probé"; el Estado lo sigue eligiendo el operador.
            if test_teclado and nombre == "Teclado":
                def _probar(_=False, lbl=lbl):
                    webbrowser.open(URL_TEST_TECLADO)
                    lbl.setText("Teclado ✔ probado")
                    lbl.setProperty("rol", "ruta")
                    lbl.style().unpolish(lbl)
                    lbl.style().polish(lbl)

                self._btn_teclado = boton(
                    "⌨️ Probar el teclado en keytest.ru", _probar, variante="fantasma"
                )

            self._filas.append((nombre, combo, obs))

        if test_teclado:
            grilla.addWidget(
                self._btn_teclado, len(COMPONENTES) + 1, 0, 1, 3, Qt.AlignmentFlag.AlignLeft
            )

    @staticmethod
    def _al_cambiar_estado(estado, obs):
        if estado != "OK":
            obs.setEnabled(True)
            obs.setFocus()
        else:
            obs.clear()
            obs.setEnabled(False)

    def detalle(self):
        """[{'nombre', 'estado', 'obs'}] en el formato que guarda el JSON."""
        return [
            {"nombre": n, "estado": c.currentText(), "obs": o.text().strip()}
            for n, c, o in self._filas
        ]

    def reiniciar(self):
        for _n, combo, obs in self._filas:
            combo.setCurrentText("OK")
            obs.clear()
            obs.setEnabled(False)


class SeccionOffice(QWidget):
    """Casilla 'Registrar Office' + versión + key (habilitadas solo si se marca)."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        fila = QHBoxLayout()
        self.chk = QCheckBox("📦 Registrar Office")
        self.chk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_version = QComboBox()
        self.combo_version.addItems(VERSIONES_OFFICE)
        self.combo_version.setCurrentText("2016")
        self.combo_version.setEnabled(False)
        fila.addWidget(self.chk)
        fila.addWidget(self.combo_version)
        fila.addStretch(1)
        layout.addLayout(fila)

        self.entry_key = QLineEdit()
        self.entry_key.setProperty("rol", "clave")
        self.entry_key.setPlaceholderText("Key de Office")
        self.entry_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.entry_key.setEnabled(False)
        layout.addWidget(self.entry_key)

        self.chk.toggled.connect(self._al_marcar)

    def _al_marcar(self, marcado):
        self.entry_key.setEnabled(marcado)
        self.combo_version.setEnabled(marcado)
        if not marcado:
            self.entry_key.clear()

    def valores(self):
        """(tiene_office, office_key, version_office)."""
        return (
            self.chk.isChecked(),
            self.entry_key.text().strip(),
            self.combo_version.currentText(),
        )
