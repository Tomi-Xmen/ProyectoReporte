"""
Licencias de Office: importar la planilla de cajas, ver cuáles quedan
disponibles y a qué equipo está cada una, liberar y exportar.
"""

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QVBoxLayout,
)

from ...nucleo import licencias_office as lic_office
from ...nucleo.fichas import VERSIONES_OFFICE
from .. import avisos
from ..widgets import agregar_fila, boton, etiqueta, fila_botones, tabla

_SIN_VERSION = "Sin versión"


class DialogoLicencias(QDialog):
    def __init__(self, padre):
        super().__init__(padre)
        self.setWindowTitle("Licencias de Office")
        self.resize(1120, 640)
        self._filas = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        layout.addWidget(etiqueta("🔑 Licencias de Office", "titulo-dialogo"))
        self.lbl_resumen = etiqueta("", "campo", ajustar=True)
        layout.addWidget(self.lbl_resumen)

        self.entry_filtro = QLineEdit()
        self.entry_filtro.setPlaceholderText(
            "Buscar por código de caja, serial, cliente, OT o versión"
        )
        self.entry_filtro.textChanged.connect(self.refrescar)
        layout.addWidget(self.entry_filtro)

        self.tabla = tabla(
            [
                ("Código de caja", 150),
                ("Versión", 75),
                ("Estado", 120),
                ("Equipo", 125),
                ("Cliente", None),
                ("OT / Guía", 100),
                ("Asignada", 95),
                ("Caja", 50),
                ("Activación", 105),
            ],
            estirar=4,
        )
        self.tabla.doubleClicked.connect(self._ver_historial)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(
            etiqueta(
                "Doble clic en una caja muestra su historial. Las keys no se muestran "
                "acá: salen en el reporte del equipo y en la exportación.",
                "ayuda",
                ajustar=True,
            )
        )

        layout.addLayout(
            fila_botones(
                boton("📂 Importar Excel / CSV", self._importar_archivo, variante="primario"),
                boton("📋 Pegar desde Excel", self._pegar),
                boton("↩️ Liberar caja", self._liberar),
                boton("💾 Exportar", self._exportar),
                boton("Cerrar", self.accept),
            )
        )
        self.refrescar()

    # ── Vista ──────────────────────────────────────────────
    def refrescar(self, *_):
        try:
            self._filas = lic_office.listar(self.entry_filtro.text())
            resumen = lic_office.resumen()
        except sqlite3.Error as e:
            self._filas, resumen = [], {}
            avisos.error(self, "Base de licencias", f"No se pudo leer la base:\n{e}")

        if not resumen:
            self.lbl_resumen.setText(
                "Todavía no hay licencias. Importá la planilla de Office "
                "(guardada como .xlsx o .csv)."
            )
        else:
            partes = [
                f"Office {v or '?'}: {n[lic_office.DISPONIBLE]} disponible(s)"
                f" de {sum(n.values())}"
                for v, n in sorted(resumen.items())
            ]
            self.lbl_resumen.setText("  ·  ".join(partes))

        self.tabla.setRowCount(0)
        for lic in self._filas:
            agregar_fila(
                self.tabla,
                (
                    lic["caja"],
                    lic["version"],
                    lic["estado"].capitalize(),
                    lic["serial"],
                    lic["cliente"].replace("_", " "),
                    lic["documento"],
                    lic["asignada"][:10],
                    lic["ubicacion"],
                    lic["activacion"],
                ),
                centradas=(1, 7),
            )

    def _seleccionada(self):
        fila = self.tabla.currentRow()
        if fila < 0 or fila >= len(self._filas):
            avisos.aviso(self, "Elegí una caja", "Seleccioná una fila de la lista.")
            return None
        return self._filas[fila]

    def _ver_historial(self, *_):
        lic = self._seleccionada()
        if not lic:
            return
        eventos = lic_office.historial(lic["caja"])
        texto = "\n".join(
            f"{e['fecha'][:16].replace('T', ' ')}  {e['evento']}  {e['detalle']}".rstrip()
            for e in eventos
        )
        if lic["nota"]:
            texto = f"📝 {lic['nota']}\n\n{texto}"
        avisos.info(
            self,
            f"Caja {lic['caja']}",
            f"{lic['producto'] or 'Office ' + lic['version']}\n"
            f"Estado: {lic['estado']}"
            + (f" · {lic_office.describir_asignacion(lic)}" if lic["estado"] == "asignada" else ""),
            detalle=texto or "Sin eventos.",
        )

    # ── Importar ───────────────────────────────────────────
    def _importar_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Importar licencias de Office",
            "",
            "Planillas (*.xlsx *.csv *.txt *.xls);;Todos los archivos (*)",
        )
        if not ruta:
            return
        try:
            filas = lic_office.leer_planilla(ruta)
        except lic_office.ErrorLicencia as e:
            avisos.error(self, "No se pudo importar", e.mensaje)
            return
        self.importar_filas(filas)

    def _pegar(self):
        filas = lic_office.filas_de_texto(QApplication.clipboard().text())
        if not filas:
            avisos.aviso(
                self,
                "Portapapeles vacío",
                "Copiá en Excel las filas de las cajas (código de caja y key) y volvé a pegar.",
            )
            return
        self.importar_filas(filas)

    def importar_filas(self, filas):
        licencias, invalidas = lic_office.interpretar_filas(filas)
        if not licencias:
            avisos.aviso(
                self,
                "Nada que importar",
                "No se encontró ninguna fila con código de caja y key válida.",
                detalle="\n".join(f"Fila {n}: {m}" for n, m in invalidas[:50]) or None,
            )
            return

        # Una lista suelta (sin la columna PRODUCTO) no dice la versión.
        sin_version = [l for l in licencias if not l["version"]]
        if sin_version:
            version, ok = QInputDialog.getItem(
                self,
                "Versión de Office",
                f"{len(sin_version)} licencia(s) no dicen de qué versión son.\n¿Cuál es?",
                [*VERSIONES_OFFICE, _SIN_VERSION],
                1,
                False,
            )
            if not ok:
                return
            for l in sin_version:
                l["version"] = "" if version == _SIN_VERSION else version

        por_estado = {}
        for l in licencias:
            por_estado[l["estado"]] = por_estado.get(l["estado"], 0) + 1
        detalle_estado = ", ".join(f"{n} {e}" for e, n in sorted(por_estado.items()))
        texto = f"Se van a importar {len(licencias)} licencia(s): {detalle_estado}."
        if invalidas:
            texto += f"\n\n{len(invalidas)} fila(s) no se pueden leer y quedan afuera."
        texto += "\n\nLas cajas que ya están en la base no se tocan.\n\n¿Importar?"
        if not avisos.confirmar(self, "Importar licencias", texto):
            return

        try:
            resultado = lic_office.importar(licencias)
        except sqlite3.Error as e:
            avisos.error(self, "No se pudo importar", f"Error en la base de licencias:\n{e}")
            return
        self.refrescar()

        lineas = [f"✅ {resultado['nuevas']} licencia(s) nueva(s)."]
        if resultado["repetidas"]:
            lineas.append(f"{resultado['repetidas']} ya estaban en la base (sin cambios).")
        problemas = [f"Caja {c}: {m}" for c, m in resultado["conflictos"]]
        problemas += [f"Fila {n}: {m}" for n, m in invalidas]
        if problemas:
            lineas.append(f"⚠️ {len(problemas)} no entraron (ver detalle).")
        avisos.info(
            self,
            "Importación terminada",
            "\n".join(lineas),
            detalle="\n".join(problemas) or None,
        )

    # ── Acciones ───────────────────────────────────────────
    def _liberar(self):
        lic = self._seleccionada()
        if not lic:
            return
        if lic["estado"] == lic_office.DISPONIBLE:
            avisos.info(self, "Ya está libre", f"La caja {lic['caja']} ya está disponible.")
            return
        donde = (
            lic_office.describir_asignacion(lic)
            if lic["estado"] == lic_office.ASIGNADA
            else "deshabilitada"
        )
        if not avisos.confirmar(
            self,
            "Liberar caja",
            f"¿Liberar la caja {lic['caja']}?\n\nAhora: {donde}.\n\n"
            "Queda disponible para otro equipo. Si la key sigue cargada en el "
            "equipo anterior, hay que quitarla allá.",
        ):
            return
        try:
            lic_office.liberar(lic["caja"], "liberada a mano")
        except (lic_office.ErrorLicencia, sqlite3.Error) as e:
            avisos.error(self, "No se pudo liberar", str(e))
            return
        self.refrescar()

    def _exportar(self):
        nombre = f"licencias_office_{datetime.now():%Y%m%d}.csv"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar licencias", nombre, "CSV para Excel (*.csv)"
        )
        if not ruta:
            return
        try:
            n = lic_office.exportar_csv(ruta)
        except (OSError, sqlite3.Error) as e:
            avisos.error(self, "No se pudo exportar", str(e))
            return
        avisos.info(
            self,
            "Exportado",
            f"{n} licencia(s) exportadas a:\n{ruta}\n\n"
            "El archivo lleva las keys completas: guardalo en un lugar seguro.",
        )


def abrir(ventana):
    DialogoLicencias(ventana).exec()
    return False
