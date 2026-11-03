"""
Bloques de formulario que se repiten en varias pantallas: la revisión de
componentes (retiros, etiqueta manual, modo clonación) y el registro de
Office.
"""

import sqlite3
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

from ..nucleo import activacion_office, licencias_office
from ..nucleo.fichas import COMPONENTES, ESTADOS, VERSIONES_OFFICE  # noqa: F401 (los reexporta)
from .widgets import boton, etiqueta

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
    """
    Casilla 'Registrar Office' + versión + key (habilitadas solo si se marca).

    Con 'serial' suma el código de caja: al escanear la caja (o su código de
    barras) la key y la versión salen de la base de licencias y quedan fijas.
    Es solo una vista previa: la caja se asigna de verdad al guardar, con
    licencias_office.asignar(), que es quien decide si sigue libre.

    Con 'version_ot' (la OT va con Office) la casilla viene marcada y la
    versión fija. Si no se escanea la caja acá, el equipo queda pendiente y
    se le elige después en "Asignar Office".
    """

    def __init__(self, serial=None, version_ot=""):
        super().__init__()
        self.serial = serial
        self.version_ot = version_ot if serial is not None else ""
        self.licencia = None
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

        self.entry_caja = self.lbl_caja = self.chk_activar = None
        if serial is not None:
            self.entry_caja = QLineEdit()
            self.entry_caja.setPlaceholderText(
                "Código de caja: escaneá la caja o su código de barras"
            )
            self.entry_caja.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.entry_caja)
            self.lbl_caja = etiqueta("", "ayuda", ajustar=True)
            self.lbl_caja.hide()
            layout.addWidget(self.lbl_caja)

        self.entry_key = QLineEdit()
        self.entry_key.setProperty("rol", "clave")
        self.entry_key.setPlaceholderText("Key de Office")
        self.entry_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.entry_key.setEnabled(False)
        layout.addWidget(self.entry_key)

        if serial is not None:
            self.chk_activar = QCheckBox("⚡ Cargar la key y activar Office en este equipo")
            self.chk_activar.setCursor(Qt.CursorShape.PointingHandCursor)
            self.chk_activar.setChecked(True)
            self.chk_activar.hide()
            layout.addWidget(self.chk_activar)
            # La pistola manda Enter al final; tipeando a mano, salir del campo.
            self.entry_caja.returnPressed.connect(self._buscar_caja)
            self.entry_caja.editingFinished.connect(self._buscar_caja)

        self.chk.toggled.connect(self._al_marcar)
        if self.version_ot:
            self.chk.setChecked(True)
            if self.version_ot in VERSIONES_OFFICE:
                self.combo_version.setCurrentText(self.version_ot)
            self._soltar_licencia()
            self._aviso_caja(self._texto_ot())

        # Re-escaneo: si el equipo ya tiene caja, se muestra en vez de pedirla.
        if serial:
            try:
                previa = licencias_office.caja_de_equipo(serial)
            except sqlite3.Error:
                previa = None
            if previa:
                self.entry_caja.setText(previa["caja"])
                self._buscar_caja()

    def _texto_ot(self):
        return (
            f"🔑 Esta OT va con Office {self.version_ot}: escaneá la caja de este equipo, "
            "o asignala después desde 🔑 Asignar Office."
        )

    def _al_marcar(self, marcado):
        self.entry_key.setEnabled(marcado)
        self.combo_version.setEnabled(marcado and self.licencia is None and not self.version_ot)
        if not marcado:
            self.entry_key.clear()
        if self.entry_caja is not None:
            if not marcado:
                self.entry_caja.clear()
            if not self.entry_caja.text():
                self._buscar_caja()

    def _aviso_caja(self, texto):
        self.lbl_caja.setText(texto)
        self.lbl_caja.setVisible(bool(texto))

    def _soltar_licencia(self):
        """Vuelve a la carga manual: la key deja de estar fija."""
        if self.licencia is not None:
            self.entry_key.clear()
        self.licencia = None
        # En una OT con Office la key sale de la base: no se tipea.
        self.entry_key.setReadOnly(bool(self.version_ot))
        self.entry_key.setPlaceholderText(
            "Sale de la caja" if self.version_ot else "Key de Office"
        )
        self.combo_version.setEnabled(self.chk.isChecked() and not self.version_ot)
        self.chk_activar.setVisible(
            bool(self.version_ot) and activacion_office.aplica(self.version_ot)
        )

    def _buscar_caja(self):
        texto = self.entry_caja.text().strip()
        if self.licencia is not None and texto == self.licencia["caja"]:
            return
        self._soltar_licencia()
        if not texto:
            self._aviso_caja(self._texto_ot() if self.version_ot and self.chk.isChecked() else "")
            return
        try:
            lic = licencias_office.buscar(texto)
        except sqlite3.Error as e:
            self._aviso_caja(f"❌ No se pudo leer la base de licencias: {e}")
            return
        if not lic:
            self._aviso_caja(
                "❌ Ese código no está en la base de licencias."
                if licencias_office.existe_base()
                else "❌ No hay base de licencias: cargala desde 🔑 Licencias de Office."
            )
            return

        nombre = lic["producto"] or f"Office {lic['version']}"
        if lic["estado"] == licencias_office.DESHABILITADA:
            self._aviso_caja(f"⛔ Caja {lic['caja']} deshabilitada. {lic['nota']}".strip())
            return
        if lic["estado"] == licencias_office.ASIGNADA and lic["serial"] != self.serial:
            self._aviso_caja(
                f"⛔ Caja {lic['caja']} ya asignada a otro equipo: "
                f"{licencias_office.describir_asignacion(lic)}"
            )
            return

        self.licencia = lic
        self.chk.setChecked(True)
        if lic["version"] in VERSIONES_OFFICE:
            self.combo_version.setCurrentText(lic["version"])
        self.combo_version.setEnabled(False)
        self.entry_key.setText(lic["clave"])
        self.entry_key.setReadOnly(True)
        self.chk_activar.setVisible(activacion_office.aplica(lic["version"]))
        if lic["estado"] == licencias_office.ASIGNADA:
            estado = "ya asignada a este equipo"
        else:
            estado = "disponible"
            if lic["ubicacion"]:
                estado += f" · guardada en la caja {lic['ubicacion']}"
        if lic["cuenta"]:
            estado += f" · cuenta {lic['cuenta']}"
        texto = f"✅ Caja {lic['caja']} · {nombre} · {estado}"
        # Sin ese Office en el equipo, cargar la key fallaría al guardar.
        if activacion_office.aplica(lic["version"]) and not activacion_office.office_instalado(
            lic["version"]
        ):
            texto += (
                f"\n⚠️ Office {lic['version']} no está instalado en este equipo: "
                "instalalo antes de activarlo."
            )
        self._aviso_caja(texto)

    def valores(self):
        """(tiene_office, office_key, version_office)."""
        return (
            self.chk.isChecked(),
            self.entry_key.text().strip(),
            self.combo_version.currentText(),
        )

    def caja(self):
        """Código de caja escrito ('' si no hay o la sección no lo usa)."""
        if self.entry_caja is None or not self.chk.isChecked():
            return ""
        return self.entry_caja.text().strip()

    def activar(self):
        """True si hay que cargar la key en este equipo al guardar."""
        return bool(
            self.chk_activar
            and self.chk_activar.isVisibleTo(self)
            and self.chk_activar.isChecked()
        )
