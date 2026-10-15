"""
Diálogos de OT: crear (o reabrir) una OT y elegir una de las abiertas.
"""

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QLineEdit, QVBoxLayout

from ..nucleo.lotes import (
    MOV_CFG,
    abrir_lote,
    carpeta_lote,
    cargar_lote_activo,
    clientes_existentes,
    esta_cerrado,
    hacer_lote,
    leer_cerrado,
    listar_lotes_abiertos,
    normalizar_cliente,
    normalizar_numero,
    reabrir_lote,
)
from . import avisos
from .widgets import agregar_fila, boton, etiqueta, fila_botones, tabla


def _encabezado(layout, titulo, subtitulo=None):
    layout.addWidget(etiqueta(titulo, "titulo-dialogo"))
    if subtitulo:
        layout.addWidget(etiqueta(subtitulo, "subtitulo", ajustar=True))


class DialogoNuevoLote(QDialog):
    """
    Crea (o reabre) un lote: cliente + movimiento + sus dos documentos, la OT
    y la guía. El que nombra la carpeta es obligatorio y depende del
    movimiento; el otro es opcional y se puede completar después.
    """

    def __init__(self, padre, mov_sugerido="Entrega"):
        super().__init__(padre)
        self.setWindowTitle("Nueva OT / Guía")
        self.setMinimumWidth(500)
        self.lote = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        _encabezado(
            layout,
            "🗂️ ¿A qué OT pertenece lo que vas a escanear?",
            "El movimiento y el número los define la OT, no cada equipo.",
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.combo_cli = QComboBox()
        self.combo_cli.setEditable(True)
        self.combo_cli.addItems(clientes_existentes())
        self.combo_cli.setCurrentText("")
        self.combo_cli.lineEdit().setPlaceholderText("Elegí o escribí un cliente")
        form.addRow(etiqueta("Cliente:", "campo"), self.combo_cli)

        self.combo_mov = QComboBox()
        self.combo_mov.addItems(list(MOV_CFG))
        self.combo_mov.setCurrentText(mov_sugerido)
        form.addRow(etiqueta("Movimiento:", "campo"), self.combo_mov)

        self.lbl_num = etiqueta("N° de OT:", "campo")
        self.entry_num = QLineEdit()
        form.addRow(self.lbl_num, self.entry_num)

        # El segundo documento del lote. Es opcional: muchas veces se conoce la
        # OT antes que la guía (o al revés) y no puede frenar la creación.
        self.lbl_sec = etiqueta("N° de Guía:", "campo")
        self.entry_sec = QLineEdit()
        self.entry_sec.setPlaceholderText("Opcional, se puede completar después")
        form.addRow(self.lbl_sec, self.entry_sec)
        layout.addLayout(form)

        self.lbl_prev = etiqueta("", "ruta", alinear=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_prev)

        btn_ok = boton("✅ Usar esta OT", self._confirmar, variante="exito")
        btn_ok.setDefault(True)
        layout.addLayout(fila_botones(btn_ok, boton("Cancelar", self.reject)))

        self.combo_mov.currentTextChanged.connect(self._refrescar)
        self.entry_num.textChanged.connect(self._refrescar)
        self.combo_cli.currentTextChanged.connect(self._refrescar)
        self.entry_num.returnPressed.connect(self._confirmar)
        self.entry_sec.returnPressed.connect(self._confirmar)
        self._refrescar()
        self.combo_cli.setFocus()

    def _refrescar(self, *_):
        mov = self.combo_mov.currentText()
        # El número que nombra la carpeta cambia con el movimiento: la entrega
        # se archiva por OT y el retiro por guía. El otro campo es el opuesto.
        es_entrega = mov == "Entrega"
        self.lbl_num.setText("N° de OT:" if es_entrega else "N° de Guía:")
        self.lbl_sec.setText("N° de Guía:" if es_entrega else "N° de OT:")
        numero = normalizar_numero(self.entry_num.text(), mov)
        texto_cli = self.combo_cli.currentText()
        cliente = normalizar_cliente(texto_cli) if texto_cli.strip() else ""
        if numero and cliente:
            self.lbl_prev.setText(
                f"📁 {MOV_CFG[mov]['grupo']} / {cliente} / {carpeta_lote(mov, numero)}"
            )
        else:
            self.lbl_prev.setText("")

    def _confirmar(self):
        if not self.combo_cli.currentText().strip():
            avisos.aviso(self, "Falta el cliente", "Elegí o escribí un cliente.")
            return
        mov = self.combo_mov.currentText()
        numero = normalizar_numero(self.entry_num.text(), mov)
        if not numero:
            avisos.aviso(
                self,
                "Número inválido",
                "Escribí el número de OT / guía.\n\nSolo letras, números, '-' y '_'.",
            )
            return

        lote = hacer_lote(
            mov,
            normalizar_cliente(self.combo_cli.currentText()),
            numero,
            numero_sec=normalizar_numero(self.entry_sec.text(), mov),
        )

        # Reabrir una OT ya cerrada es posible, pero nunca en silencio.
        if esta_cerrado(lote["ruta"]):
            meta = leer_cerrado(lote["ruta"])
            if not avisos.confirmar(
                self,
                "OT ya cerrada",
                f"La {carpeta_lote(mov, numero)} de {lote['cliente']} ya está "
                f"cerrada ({meta.get('equipos', '?')} equipo(s), "
                f"{str(meta.get('cerrado', ''))[:10]}).\n\n"
                "¿Reabrirla para agregar más equipos?",
            ):
                return
            reabrir_lote(lote)

        self.lote = abrir_lote(lote)
        self.accept()


def nuevo_lote(padre, mov_sugerido="Entrega"):
    """Lote listo para recibir equipos, o None si se cancela."""
    dlg = DialogoNuevoLote(padre, mov_sugerido)
    dlg.exec()
    return dlg.lote


class DialogoElegirLote(QDialog):
    """Lista las OT abiertas para elegir una (doble clic o botón)."""

    def __init__(self, padre, titulo, texto_boton, abiertos):
        super().__init__(padre)
        self.setWindowTitle(titulo)
        self.resize(620, 440)
        self.lote = None
        self._abiertos = abiertos

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        _encabezado(layout, titulo, f"{len(abiertos)} OT en curso")

        self.tabla = tabla(
            [("Cliente", None), ("OT / Guía", 130), ("Equipos", 80), ("Última actividad", 140)],
            estirar=0,
        )
        activo = cargar_lote_activo()
        fila_activa = 0
        for i, lote in enumerate(abiertos):
            agregar_fila(
                self.tabla,
                (
                    lote["cliente"].replace("_", " "),
                    carpeta_lote(lote["mov"], lote["numero"]),
                    lote["equipos"],
                    datetime.fromtimestamp(lote["modificado"]).strftime("%d-%m %H:%M"),
                ),
                centradas=(2,),
            )
            if activo and os.path.normcase(activo["ruta"]) == os.path.normcase(
                lote["ruta"]
            ):
                fila_activa = i
        self.tabla.selectRow(fila_activa)
        self.tabla.doubleClicked.connect(self._confirmar)
        layout.addWidget(self.tabla, 1)

        btn_ok = boton(texto_boton, self._confirmar, variante="exito")
        btn_ok.setDefault(True)
        layout.addLayout(fila_botones(btn_ok, boton("Cancelar", self.reject)))

    def _confirmar(self, *_):
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        self.lote = self._abiertos[fila]
        self.accept()


def elegir_lote(padre, titulo, texto_boton):
    """
    OT abierta elegida, o None. Solo mira carpetas sin '.cerrado': no abre
    archivos de las OT finalizadas.
    """
    abiertos = listar_lotes_abiertos()
    if not abiertos:
        avisos.info(
            padre,
            "Sin OT abiertas",
            "No hay ninguna OT en curso.\n\nCreá una con '➕ Nueva OT'.",
        )
        return None
    dlg = DialogoElegirLote(padre, titulo, texto_boton, abiertos)
    dlg.exec()
    return dlg.lote
