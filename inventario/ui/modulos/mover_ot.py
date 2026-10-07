"""Mover equipos de la OT activa a otra OT abierta."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from ...nucleo.lotes import (
    cargar_lote_activo,
    etiqueta_lote,
    leer_equipos_lote,
    mover_equipos_a_lote,
    son_el_mismo_lote,
)
from .. import avisos
from ..dialogos import elegir_lote
from ..widgets import agregar_fila, boton, etiqueta, fila_botones, filas_seleccionadas, tabla


class DialogoMoverOT(QDialog):
    def __init__(self, padre, origen, registros):
        super().__init__(padre)
        self.setWindowTitle("Mover equipos a otra OT")
        self.resize(660, 560)
        self.origen, self.registros = origen, registros
        self.movidos = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("↔️ Mover equipos a otra OT", "titulo-dialogo"))
        layout.addWidget(
            etiqueta(
                f"Origen: {etiqueta_lote(origen)}  ·  {len(registros)} equipo(s)\n"
                "Marcá los equipos y elegí la OT destino (Ctrl/Shift para varios).",
                "subtitulo",
                ajustar=True,
            )
        )

        self.tabla = tabla([("Modelo", None), ("Serial", 200)], seleccion_multiple=True)
        for jdata in registros:
            agregar_fila(self.tabla, (jdata.get("MODELO", "?"), jdata.get("SERIAL", "?")))
        layout.addWidget(self.tabla, 1)

        layout.addLayout(
            fila_botones(
                boton("↔️ Mover seleccionados", self._mover, variante="ot"),
                boton("Cancelar", self.reject),
            )
        )

    def _mover(self):
        seriales = [
            self.registros[f].get("SERIAL", "") for f in filas_seleccionadas(self.tabla)
        ]
        if not seriales:
            avisos.info(self, "Sin selección", "Marcá al menos un equipo.")
            return

        destino = elegir_lote(self, "Mover a esta OT", "↔️ Mover aquí")
        if not destino:
            return
        if son_el_mismo_lote(self.origen, destino):
            avisos.aviso(self, "Misma OT", "El destino es la misma OT de origen.")
            return

        self.movidos = mover_equipos_a_lote(self.origen, seriales, destino)
        self.destino = destino
        self.accept()


def abrir(ventana):
    """Devuelve True si se movió algo (el menú tiene que refrescarse)."""
    origen = cargar_lote_activo()
    if not origen:
        avisos.aviso(
            ventana, "Sin OT activa", "Activá una OT para poder mover sus equipos."
        )
        return False

    registros = leer_equipos_lote(origen)
    if not registros:
        avisos.aviso(
            ventana,
            "OT sin equipos",
            f"{etiqueta_lote(origen)} no tiene equipos para mover.",
        )
        return False

    dlg = DialogoMoverOT(ventana, origen, registros)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    avisos.info(
        ventana,
        "✅ Movidos",
        f"{dlg.movidos} equipo(s) pasaron a {etiqueta_lote(dlg.destino)}.\n\n"
        "Se regeneró el HTML y el JSON FUSIONADO de ambas OT.",
    )
    return True
