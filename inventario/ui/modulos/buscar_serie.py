"""
Buscar serie: dónde estuvo un equipo (todas las OT y guías de esta PC) y su
reporte HTML con las filas que se marquen.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QTableWidgetItem, QVBoxLayout

from ...nucleo import historial as H
from ...nucleo import lotes
from ...nucleo.reporte_html import TRANSF_PENDIENTE
from .. import avisos
from ..widgets import agregar_fila, boton, etiqueta, fila_botones, tabla

_COL_MARCA = 0


def _fecha(fecha):
    try:
        return datetime.fromisoformat(fecha).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return fecha or "—"


def _celdas(a):
    """Lo que muestra la fila de una aparición, desde su JSON."""
    j = a["jdata"]
    fallas = ", ".join(
        c.get("nombre", "?") for c in j.get("DETALLE_COMPONENTES", []) if c.get("estado", "OK") != "OK"
    )
    cargador = j.get("SN_Transf") or TRANSF_PENDIENTE
    office = j.get("OFFICE", "No")
    if office in ("No", "", None):
        office = "—"
    elif j.get("OFFICE_CAJA"):
        office = f"{office} · caja {j['OFFICE_CAJA']}"
    obs = j.get("OBS", "")
    return (
        "",
        _fecha(a["fecha"]),
        a["mov"],
        a["cliente"].replace("_", " "),
        j.get("OT_ID", "—"),
        j.get("GUIA_ID", "—"),
        a["estado"],
        fallas or "—",
        "—" if cargador == TRANSF_PENDIENTE else cargador,
        office,
        "" if obs == "Sin observaciones" else obs,
    )


def abrir_carpeta(ruta):
    """Abre la carpeta en el explorador de archivos del sistema."""
    if sys.platform == "win32":
        os.startfile(ruta)  # noqa: S606 (ruta propia, no del usuario)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", ruta])


class DialogoBuscarSerie(QDialog):
    def __init__(self, padre, texto=""):
        super().__init__(padre)
        self.setWindowTitle("Buscar serie")
        self.resize(1260, 720)
        self.series = []
        self.apariciones = []
        self.serial = ""
        self.activada = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("🔎 Buscar serie", "titulo-dialogo"))
        layout.addWidget(
            etiqueta(
                "En todas las OT y guías de esta PC: abiertas, cerradas y lo quitado. "
                f"Desde {H.MINIMO_PARCIAL} caracteres busca también una parte de la serie.",
                "ayuda",
                ajustar=True,
            )
        )

        fila = QHBoxLayout()
        self.entry = QLineEdit(texto)
        self.entry.setPlaceholderText("Escaneá o escribí la serie")
        self.entry.returnPressed.connect(self.buscar)
        fila.addWidget(self.entry, 1)
        fila.addWidget(boton("Buscar", self.buscar, variante="primario"))
        layout.addLayout(fila)

        # Varias series coinciden (búsqueda parcial): se elige una.
        self.lbl_series = etiqueta("", "campo")
        self.tabla_series = tabla(
            [("Serie", 200), ("Registros", 90), ("Último cliente", None), ("Última vez", 150)],
            estirar=2,
        )
        self.tabla_series.setMaximumHeight(170)
        self.tabla_series.itemSelectionChanged.connect(self._al_elegir_serie)
        layout.addWidget(self.lbl_series)
        layout.addWidget(self.tabla_series)

        self.lbl_serial = etiqueta("", "titulo-dialogo")
        self.lbl_resumen = etiqueta("", "campo", ajustar=True)
        self.lbl_office = etiqueta("", "ayuda", ajustar=True)
        for w in (self.lbl_serial, self.lbl_resumen, self.lbl_office):
            layout.addWidget(w)

        self.tabla = tabla(
            [
                ("✓", 36),
                ("Fecha", 172),
                ("Movimiento", 105),
                ("Cliente", 140),
                ("N° de OT", 80),
                ("N° de Guía", 90),
                ("Estado", 80),
                ("Fallas", 100),
                ("Cargador", 110),
                ("Office", 140),
                ("Observación", None),
            ],
            estirar=10,
        )
        self.tabla.itemSelectionChanged.connect(self._refrescar_botones)
        layout.addWidget(self.tabla, 1)

        self.lbl_estado = etiqueta("", "ruta", ajustar=True)
        layout.addWidget(self.lbl_estado)

        self.btn_marcar = boton("Marcar todas", self._marcar_todas)
        self.btn_html = boton("📄 Generar HTML", self._generar_html, variante="primario")
        self.btn_carpeta = boton("📂 Abrir carpeta", self._abrir_carpeta)
        self.btn_activar = boton("✅ Activar esta OT", self._activar, variante="exito")
        layout.addLayout(
            fila_botones(
                self.btn_marcar, self.btn_html, self.btn_carpeta, self.btn_activar,
                boton("Cerrar", self.accept),
            )
        )
        self._mostrar_series()
        if texto:
            self.buscar()
        self.entry.setFocus()

    # ── Búsqueda ───────────────────────────────────────────
    def buscar(self):
        texto = self.entry.text()
        if not H.clave_serial(texto):
            return
        self.series = H.buscar(texto)
        if not self.series:
            self.lbl_estado.setText(
                f"No se encontró ninguna serie con «{texto.strip()}» en las OT y guías de esta PC."
                if len(H.clave_serial(texto)) >= H.MINIMO_PARCIAL
                else f"No hay ninguna serie «{texto.strip()}». Con {H.MINIMO_PARCIAL} "
                "caracteres o más se busca también una parte."
            )
        else:
            self.lbl_estado.setText("")
        self._mostrar_series()
        if self.series:
            self.tabla_series.selectRow(0)
            self._al_elegir_serie()
        else:
            self._mostrar_historial("", [])
        # La pistola manda Enter al final: el campo queda listo para la próxima.
        self.entry.selectAll()

    def _mostrar_series(self):
        varias = len(self.series) > 1
        self.lbl_series.setText(f"{len(self.series)} series coinciden:" if varias else "")
        self.lbl_series.setVisible(varias)
        self.tabla_series.setVisible(varias)
        self.tabla_series.setRowCount(0)
        for s in self.series:
            agregar_fila(
                self.tabla_series,
                (s["serial"], s["registros"], s["cliente"], _fecha(s["ultima"])),
                centradas=(1,),
            )

    def _al_elegir_serie(self):
        fila = self.tabla_series.currentRow()
        if 0 <= fila < len(self.series):
            serial = self.series[fila]["serial"]
            self._mostrar_historial(serial, H.historial(serial))

    # ── Historial ──────────────────────────────────────────
    def _mostrar_historial(self, serial, apariciones):
        self.serial, self.apariciones = serial, apariciones
        self.lbl_serial.setText(serial)
        if apariciones:
            ultima = apariciones[0]
            self.lbl_resumen.setText(
                f"{len(apariciones)} registro(s) · último: {ultima['mov']} "
                f"{'a' if ultima['mov'] == 'Entrega' else 'de'} "
                f"{ultima['cliente'].replace('_', ' ')}"
                + (f" ({ultima['documento']}, {ultima['estado']})" if ultima["documento"] else "")
            )
        else:
            self.lbl_resumen.setText("")
        try:
            cajas = H.office_del_equipo(serial) if serial else []
        except Exception:
            cajas = []
        self.lbl_office.setText(
            "🔑 Office: "
            + " · ".join(
                f"caja {c['caja']} (Office {c['version'] or '?'}, {c['estado']} desde {c['desde']})"
                for c in cajas
            )
            if cajas
            else ""
        )
        self.lbl_office.setVisible(bool(cajas))

        self.tabla.setRowCount(0)
        for a in apariciones:
            fila = agregar_fila(self.tabla, _celdas(a))
            marca = QTableWidgetItem()
            marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            marca.setCheckState(Qt.CheckState.Checked)
            self.tabla.setItem(fila, _COL_MARCA, marca)
        if apariciones:
            self.tabla.selectRow(0)
        self._refrescar_botones()

    def marcadas(self):
        return [
            a
            for fila, a in enumerate(self.apariciones)
            if self.tabla.item(fila, _COL_MARCA).checkState() == Qt.CheckState.Checked
        ]

    def _actual(self):
        fila = self.tabla.currentRow()
        return self.apariciones[fila] if 0 <= fila < len(self.apariciones) else None

    def _refrescar_botones(self):
        hay = bool(self.apariciones)
        actual = self._actual()
        for b in (self.btn_marcar, self.btn_html):
            b.setEnabled(hay)
        self.btn_carpeta.setEnabled(actual is not None)
        self.btn_activar.setEnabled(bool(actual and actual["estado"] == H.ABIERTA))

    def _marcar_todas(self):
        todas = len(self.marcadas()) == len(self.apariciones)
        estado = Qt.CheckState.Unchecked if todas else Qt.CheckState.Checked
        for fila in range(self.tabla.rowCount()):
            self.tabla.item(fila, _COL_MARCA).setCheckState(estado)

    # ── Acciones ───────────────────────────────────────────
    def _generar_html(self):
        elegidas = self.marcadas()
        if not elegidas:
            avisos.aviso(self, "Nada marcado", "Marcá al menos una fila para el reporte.")
            return
        try:
            ruta = H.guardar_html(self.serial, elegidas)
        except OSError as e:
            avisos.error(self, "No se pudo guardar", str(e))
            return
        self.lbl_estado.setText(f"📄 Reporte de {len(elegidas)} registro(s) guardado en:\n{ruta}")
        webbrowser.open(Path(ruta).as_uri())

    def _abrir_carpeta(self):
        actual = self._actual()
        if actual:
            abrir_carpeta(actual["carpeta"])

    def _activar(self):
        actual = self._actual()
        if not actual or actual["estado"] != H.ABIERTA:
            return
        lotes.guardar_lote_activo(actual["lote"])
        self.activada = True
        self.lbl_estado.setText(f"✅ {lotes.etiqueta_lote(actual['lote'])} es ahora la OT activa.")


def abrir(ventana):
    dlg = DialogoBuscarSerie(ventana)
    dlg.exec()
    return dlg.activada
