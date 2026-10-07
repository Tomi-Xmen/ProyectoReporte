"""
Asignar transformadores a los equipos de la OT activa: pegando la columna
desde Excel o escaneando con la pistola (Enter salta a la fila siguiente).
"""

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout

from ...nucleo.lotes import cargar_lote_activo, etiqueta_lote
from ...nucleo.reporte_html import TRANSF_PENDIENTE
from ...nucleo.transformadores import (
    calcular_cambios,
    equipos_en_orden_de_escaneo,
    guardar_transformadores,
    normalizar_sn_transf,
    seriales_del_portapapeles,
    transformador_actual,
)
from .. import avisos
from ..widgets import agregar_fila, boton, etiqueta, fila_botones, tabla

_COL_TRANSF = 3


class DialogoTransformadores(QDialog):
    def __init__(self, padre, lote, registros):
        super().__init__(padre)
        self.setWindowTitle("Asignar transformadores")
        self.resize(820, 660)
        self.lote = lote
        self._registros = registros  # [(ruta, jdata)] en orden de escaneo

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        layout.addWidget(etiqueta("🔌 Asignar transformadores", "titulo-dialogo"))
        layout.addWidget(
            etiqueta(f"{etiqueta_lote(lote)}  ·  {len(registros)} equipo(s)", "campo")
        )
        layout.addWidget(
            etiqueta(
                "Los equipos están en orden de escaneo. Pegá la columna de seriales "
                "o escaneá con la pistola (Enter salta a la fila siguiente).",
                "ayuda",
                ajustar=True,
            )
        )

        # Una OT puede traer 50+ equipos: la tabla scrollea sola.
        self.tabla = tabla(
            [("#", 44), ("Modelo", None), ("Serial equipo", 180), ("Serie transformador", 230)]
        )
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        self.entradas = []
        for i, (_ruta, jdata) in enumerate(registros, start=1):
            data = jdata.get("DATA", {})
            fila = agregar_fila(
                self.tabla,
                (
                    i,
                    data.get("model", jdata.get("MODELO", "Desconocido")),
                    jdata.get("SERIAL", "?"),
                    "",
                ),
                centradas=(0,),
            )
            entrada = QLineEdit()
            # Lo ya cargado se muestra: este módulo se usa varias veces sobre
            # la misma OT, a medida que van llegando los cargadores.
            actual = transformador_actual(jdata)
            if actual != TRANSF_PENDIENTE:
                entrada.setText(actual)
            entrada.textChanged.connect(self._refrescar_estado)
            entrada.returnPressed.connect(lambda f=fila: self._saltar(f))
            self.tabla.setCellWidget(fila, _COL_TRANSF, entrada)
            self.entradas.append(entrada)
        self.tabla.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.tabla, 1)

        self.lbl_estado = etiqueta("", "ruta")
        layout.addWidget(self.lbl_estado)

        btn_guardar = boton("💾 Guardar", self._guardar, variante="exito")
        layout.addLayout(
            fila_botones(
                boton("📋 Pegar del portapapeles", self._pegar, variante="primario"),
                boton("🧹 Limpiar", self._limpiar),
                btn_guardar,
                boton("Cancelar", self.reject),
            )
        )
        self._refrescar_estado()
        if self.entradas:
            self.entradas[0].setFocus()

    def _refrescar_estado(self, *_):
        cargados = sum(1 for e in self.entradas if normalizar_sn_transf(e.text()))
        self.lbl_estado.setText(
            f"{cargados} de {len(self.entradas)} equipo(s) con transformador"
        )

    def _saltar(self, fila):
        """Enter = siguiente fila: la pistola manda Enter al final de cada lectura."""
        if fila + 1 < len(self.entradas):
            self.entradas[fila + 1].setFocus()
            self.tabla.scrollToItem(self.tabla.item(fila + 1, 0))

    def _pegar(self):
        crudo = QApplication.clipboard().text()
        if not crudo:
            avisos.aviso(
                self,
                "Portapapeles vacío",
                "No hay texto para pegar. Copiá primero la columna de seriales.",
            )
            return

        seriales = seriales_del_portapapeles(crudo)
        if not seriales:
            avisos.aviso(
                self, "Nada que pegar", "El portapapeles no trae ningún serial reconocible."
            )
            return

        # El pegado es posicional y sobrescribe desde la primera fila: si ya
        # había datos cargados a mano, se avisa antes de taparlos.
        if any(normalizar_sn_transf(e.text()) for e in self.entradas):
            if not avisos.confirmar(
                self,
                "Sobrescribir",
                "Ya hay transformadores cargados en la lista.\n\n"
                f"Pegar reemplaza las primeras {min(len(seriales), len(self.entradas))} "
                "fila(s) en orden. ¿Continuar?",
            ):
                return

        # zip corta por el más corto: si sobran seriales o sobran filas, no
        # revienta ni desalinea, simplemente llega hasta donde alcanza.
        for entrada, sn in zip(self.entradas, seriales):
            entrada.setText(sn)

        if len(seriales) > len(self.entradas):
            avisos.aviso(
                self,
                "Sobran seriales",
                f"Pegaste {len(seriales)} seriales pero la OT tiene "
                f"{len(self.entradas)} equipos.\n\n"
                f"Se usaron los primeros {len(self.entradas)} y se descartó el resto.",
            )

    def _limpiar(self):
        if not avisos.confirmar(
            self,
            "Limpiar",
            "¿Vaciar la columna de transformadores?\n\n"
            "Todavía no se guarda nada: los JSON quedan como están hasta que "
            "aprietes GUARDAR.",
        ):
            return
        for entrada in self.entradas:
            entrada.clear()

    def _guardar(self):
        filas = [
            (ruta, jdata, entrada.text())
            for (ruta, jdata), entrada in zip(self._registros, self.entradas)
        ]
        cambios, duplicados = calcular_cambios(filas)

        # Un transformador no puede estar en dos equipos: casi siempre es una
        # columna pegada corrida una fila, así que conviene frenar y mirar.
        if duplicados and not avisos.confirmar(
            self,
            "Transformadores repetidos",
            "Estos seriales quedaron en más de un equipo:\n\n"
            + "\n".join(duplicados[:8])
            + "\n\n¿Guardar igual?",
        ):
            return

        if not cambios:
            avisos.info(self, "Sin cambios", "No hay nada nuevo para guardar.")
            return

        errores = guardar_transformadores(self.lote, cambios)
        if errores:
            avisos.error(
                self,
                "Guardado parcial",
                f"Se guardaron {len(cambios) - len(errores)} de {len(cambios)} "
                "equipo(s).\n\nFallaron:\n" + "\n".join(errores[:8]),
            )
            return

        avisos.info(
            self,
            "✅ Transformadores guardados",
            f"{len(cambios)} equipo(s) actualizado(s) en {etiqueta_lote(self.lote)}.\n\n"
            "El HTML y el JSON FUSIONADO ya se regeneraron: los seriales salen "
            "en 'Copiar Filas' y en el CSV de Valida.",
        )
        self.accept()


def abrir(ventana):
    # Los chequeos van ANTES de crear la ventana: abrir un modal para cerrarlo
    # de inmediato hace parpadear la pantalla y roba el foco por un instante.
    lote = cargar_lote_activo()
    if not lote:
        avisos.aviso(
            ventana,
            "Sin OT activa",
            "Los transformadores se asignan a los equipos de una OT.\n\n"
            "Abrí o creá una OT antes de cargarlos.",
        )
        return False

    registros = equipos_en_orden_de_escaneo(lote)
    if not registros:
        avisos.aviso(
            ventana,
            "OT sin equipos",
            f"{etiqueta_lote(lote)} todavía no tiene equipos escaneados.",
        )
        return False

    return DialogoTransformadores(ventana, lote, registros).exec() == QDialog.DialogCode.Accepted
