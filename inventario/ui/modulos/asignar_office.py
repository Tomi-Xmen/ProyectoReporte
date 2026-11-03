"""
Asignar Office: elegir qué caja de Office va con cada notebook de la OT
activa y tener a mano su key para instalar y activar Office en el equipo.

A la izquierda, las cajas disponibles de la versión de la OT (en el orden en
que conviene sacarlas); a la derecha, los notebooks. La caja se escanea en la
fila del equipo con la pistola (Enter salta a la siguiente), se pega la
columna desde Excel, o se hace doble clic en una disponible. Guardar no
cierra: después de guardar cada fila muestra su key con un botón para
copiarla.
"""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...nucleo import licencias_office, office_ot
from ...nucleo.lotes import cargar_lote_activo, etiqueta_lote
from ...nucleo.transformadores import seriales_del_portapapeles
from .. import avisos
from ..widgets import agregar_fila, boton, etiqueta, fila_botones, tabla

_COL_CAJA = 3
_COL_ESTADO = 4
_COL_KEY = 5
_COL_COPIAR = 6
_ICONOS = {"ok": "✅", "aviso": "⚠️", "error": "⛔"}


def tabla_disponibles():
    return tabla([("Código de caja", None), ("Cod. barra", 145), ("Caja", 50)], estirar=0)


def llenar_disponibles(t, cajas):
    t.setRowCount(0)
    for lic in cajas:
        agregar_fila(t, (lic["caja"], lic["codigo_barra"], lic["ubicacion"]), centradas=(2,))


class DialogoAsignarOffice(QDialog):
    def __init__(self, padre, lote):
        super().__init__(padre)
        self.setWindowTitle("Asignar Office")
        self.resize(1500, 720)
        self.lote = lote
        self.version_ot = office_ot.version_de(lote)
        self._registros = office_ot.equipos(lote)  # [(ruta, jdata)] en orden de escaneo
        self._estados = [("", "")] * len(self._registros)
        self._libres = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        layout.addWidget(etiqueta("🔑 Asignar Office", "titulo-dialogo"))
        layout.addWidget(
            etiqueta(
                f"{etiqueta_lote(lote)}  ·  {len(self._registros)} notebook(s)"
                + (f"  ·  va con Office {self.version_ot}" if self.version_ot else ""),
                "campo",
            )
        )
        layout.addWidget(
            etiqueta(
                "Escaneá la caja de cada equipo en su fila (Enter salta a la siguiente; "
                "sirve el código de caja o el de barras), pegá la columna de códigos, o "
                "hacé doble clic en una caja disponible para ponerla en el primer equipo "
                "sin caja. Al guardar aparece la key de cada uno para copiarla."
                + (
                    ""
                    if self.version_ot
                    else "\n⚠️ Esta OT no dice con qué Office va: se puede asignar igual."
                ),
                "ayuda",
                ajustar=True,
            )
        )

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)

        izquierda = QWidget()
        col = QVBoxLayout(izquierda)
        col.setContentsMargins(0, 0, 0, 0)
        self.lbl_libres = etiqueta("", "seccion")
        col.addWidget(self.lbl_libres)
        self.tabla_libres = tabla_disponibles()
        self.tabla_libres.doubleClicked.connect(self._usar_libre)
        col.addWidget(self.tabla_libres, 1)
        izquierda.setFixedWidth(385)
        izquierda.setVisible(bool(self.version_ot))
        cuerpo.addWidget(izquierda)

        self.tabla = tabla(
            [
                ("#", 40),
                ("Modelo", 130),
                ("Serial", 135),
                ("Código de caja", 150),
                ("Estado", 190),
                ("Key", None),
                ("", 100),
            ],
            estirar=_COL_KEY,
        )
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        self.entradas = []
        for i, (_ruta, jdata) in enumerate(self._registros, start=1):
            fila = agregar_fila(
                self.tabla,
                (i, jdata.get("MODELO") or "Desconocido", jdata.get("SERIAL", "?"), "", "", "", ""),
                centradas=(0,),
            )
            entrada = QLineEdit()
            # Lo ya asignado se muestra: la pantalla se usa varias veces sobre
            # la misma OT, a medida que se arman las entregas.
            entrada.setText(jdata.get("OFFICE_CAJA", ""))
            entrada.editingFinished.connect(self._revisar_todo)
            entrada.textChanged.connect(self._contar)
            entrada.returnPressed.connect(lambda f=fila: self._saltar(f))
            self.tabla.setCellWidget(fila, _COL_CAJA, entrada)
            self.entradas.append(entrada)
            copiar = boton("Copiar", lambda _=False, f=fila: self._copiar_key(f))
            copiar.setToolTip("Copiar la key de este equipo")
            self.tabla.setCellWidget(fila, _COL_COPIAR, copiar)
        self.tabla.verticalHeader().setDefaultSectionSize(38)
        cuerpo.addWidget(self.tabla, 1)
        layout.addLayout(cuerpo, 1)

        self.lbl_estado = etiqueta("", "ruta", ajustar=True)
        layout.addWidget(self.lbl_estado)
        layout.addLayout(
            fila_botones(
                boton("📋 Pegar códigos del portapapeles", self._pegar, variante="primario"),
                boton("🧹 Limpiar", self._limpiar),
                boton("💾 Guardar", self._guardar, variante="exito"),
                boton("Cerrar", self.accept),
            )
        )
        self._mostrar_keys()
        self._revisar_todo()
        primera_vacia = next((e for e in self.entradas if not e.text()), None)
        if primera_vacia is not None:
            primera_vacia.setFocus()

    # ── Revisión de cada fila ─────────────────────────────
    def _revisar_todo(self):
        """Estado de cada fila: la base dice si la caja sirve; la tabla, si se repite."""
        cajas = []
        for i, ((_ruta, jdata), entrada) in enumerate(zip(self._registros, self.entradas)):
            codigo = licencias_office.normalizar_codigo(entrada.text())
            try:
                lic = licencias_office.buscar(codigo) if codigo else None
                estado = office_ot.revisar_codigo(codigo, jdata.get("SERIAL", ""), self.version_ot)
            except sqlite3.Error as e:
                lic, estado = None, ("error", f"Base de licencias: {e}")
            cajas.append(lic["caja"] if lic else None)
            self._fijar_estado(i, estado)
        # La misma caja en dos filas (por código de caja o de barras) no se puede.
        for i, caja in enumerate(cajas):
            if caja and cajas.count(caja) > 1:
                otra = next(j for j, c in enumerate(cajas) if c == caja and j != i)
                self._fijar_estado(i, ("error", f"Repetida en la fila {otra + 1}"))
        self._refrescar_libres(set(c for c in cajas if c))
        self._contar()

    def _fijar_estado(self, fila, estado):
        self._estados[fila] = estado
        tipo, texto = estado
        item = QTableWidgetItem(f"{_ICONOS[tipo]} {texto}" if tipo else "")
        item.setToolTip(texto)
        self.tabla.setItem(fila, _COL_ESTADO, item)

    def _refrescar_libres(self, en_la_tabla):
        """Disponibles de la versión de la OT, sin las que ya están escritas en la tabla."""
        if not self.version_ot:
            return
        try:
            libres = licencias_office.listar_disponibles(self.version_ot)
        except sqlite3.Error:
            libres = []
        self._libres = [l for l in libres if l["caja"] not in en_la_tabla]
        llenar_disponibles(self.tabla_libres, self._libres)
        self.lbl_libres.setText(f"📦 Disponibles Office {self.version_ot}: {len(self._libres)}")

    def _contar(self, *_):
        con_caja = sum(1 for e in self.entradas if licencias_office.normalizar_codigo(e.text()))
        self.lbl_estado.setText(f"{con_caja} de {len(self.entradas)} notebook(s) con caja")

    def _saltar(self, fila):
        """Enter = siguiente fila: la pistola manda Enter al final de cada lectura."""
        if fila + 1 < len(self.entradas):
            self.entradas[fila + 1].setFocus()
            self.tabla.scrollToItem(self.tabla.item(fila + 1, 0))

    def _usar_libre(self, indice):
        """Doble clic en una disponible: va al primer equipo sin caja."""
        destino = next((e for e in self.entradas if not e.text().strip()), None)
        if destino is None:
            avisos.aviso(self, "Sin lugar", "Todos los equipos ya tienen una caja escrita.")
            return
        destino.setText(self._libres[indice.row()]["caja"])
        self._revisar_todo()

    # ── Keys ───────────────────────────────────────────────
    def _mostrar_keys(self):
        """La key de cada equipo, solo cuando su caja ya está guardada."""
        # Monoespaciada: se lee carácter por carácter al tipearla en Office.
        fuente = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        for fila, (_ruta, jdata) in enumerate(self._registros):
            guardada = bool(jdata.get("OFFICE_CAJA")) and jdata.get("SN_APP") not in (
                None, "", office_ot.PENDIENTE
            )
            item = QTableWidgetItem(jdata["SN_APP"] if guardada else "")
            item.setFont(fuente)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)
            self.tabla.setItem(fila, _COL_KEY, item)
            self.tabla.cellWidget(fila, _COL_COPIAR).setEnabled(guardada)

    def _copiar_key(self, fila):
        jdata = self._registros[fila][1]
        QApplication.clipboard().setText(jdata.get("SN_APP", ""))
        self.lbl_estado.setText(
            f"📋 Key de {jdata.get('SERIAL', '?')} (caja {jdata.get('OFFICE_CAJA', '?')}) "
            "copiada: pegala en Office para activarlo."
        )

    # ── Acciones ───────────────────────────────────────────
    def _pegar(self):
        codigos = seriales_del_portapapeles(QApplication.clipboard().text())
        if not codigos:
            avisos.aviso(
                self,
                "Portapapeles vacío",
                "Copiá primero la columna de códigos de caja (uno por fila).",
            )
            return
        # El pegado es posicional desde la primera fila: si había cajas
        # escritas, se avisa antes de taparlas.
        if any(e.text().strip() for e in self.entradas) and not avisos.confirmar(
            self,
            "Sobrescribir",
            "Ya hay cajas escritas en la lista.\n\n"
            f"Pegar reemplaza las primeras {min(len(codigos), len(self.entradas))} "
            "fila(s) en orden. ¿Continuar?",
        ):
            return
        for entrada, codigo in zip(self.entradas, codigos):
            entrada.setText(codigo)
        self._revisar_todo()
        if len(codigos) > len(self.entradas):
            avisos.aviso(
                self,
                "Sobran códigos",
                f"Pegaste {len(codigos)} códigos pero la OT tiene {len(self.entradas)} "
                f"notebooks.\n\nSe usaron los primeros {len(self.entradas)}.",
            )

    def _limpiar(self):
        if not avisos.confirmar(
            self,
            "Limpiar",
            "¿Vaciar la columna de cajas?\n\nTodavía no se guarda nada: las cajas "
            "asignadas siguen como están hasta que aprietes GUARDAR.",
        ):
            return
        for entrada in self.entradas:
            entrada.clear()
        self._revisar_todo()

    def _guardar(self):
        self._revisar_todo()
        filas = [
            (i + 1, j.get("SERIAL", "?"), est)
            for i, ((_r, j), est) in enumerate(zip(self._registros, self._estados))
        ]
        errores = [f"Fila {n} ({s}): {t}" for n, s, (tipo, t) in filas if tipo == "error"]
        if errores:
            avisos.error(
                self,
                "Hay cajas que no se pueden usar",
                "Corregí estas filas antes de guardar:\n\n" + "\n".join(errores[:12]),
            )
            return
        dudas = [f"Fila {n} ({s}): {t}" for n, s, (tipo, t) in filas if tipo == "aviso"]
        if dudas and not avisos.confirmar(
            self,
            "Revisar antes de guardar",
            "\n".join(dudas[:12])
            + "\n\nUna caja que hoy es de otro equipo de esta OT pasa a este. ¿Guardar igual?",
        ):
            return

        try:
            cambiados = office_ot.guardar_cajas(
                self.lote,
                [(r, j, e.text()) for (r, j), e in zip(self._registros, self.entradas)],
            )
        except licencias_office.ErrorLicencia as e:
            avisos.error(self, "No se guardó nada", e.mensaje)
            self._revisar_todo()
            return
        except sqlite3.Error as e:
            avisos.error(self, "Base de licencias", f"No se pudo usar la base de licencias:\n{e}")
            return

        # guardar_cajas escribió los JSON: la tabla pasa a mostrar sus keys.
        self._mostrar_keys()
        self._revisar_todo()
        if cambiados:
            self.lbl_estado.setText(
                f"✅ {cambiados} equipo(s) actualizado(s). El HTML y el JSON FUSIONADO ya se "
                "regeneraron con las keys. Ya podés copiar la key de cada equipo."
            )
        else:
            self.lbl_estado.setText("Sin cambios: ya estaba todo guardado.")


class DialogoCajasDisponibles(QDialog):
    """Solo mirar: qué cajas de una versión quedan libres y dónde están guardadas."""

    def __init__(self, padre, version):
        super().__init__(padre)
        self.setWindowTitle(f"Cajas disponibles Office {version}")
        self.resize(460, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        try:
            cajas = licencias_office.listar_disponibles(version)
        except sqlite3.Error:
            cajas = []
        layout.addWidget(
            etiqueta(f"📦 Office {version}: {len(cajas)} disponible(s)", "titulo-dialogo")
        )
        layout.addWidget(
            etiqueta(
                "En el orden en que conviene sacarlas: por caja de almacenamiento y código.",
                "ayuda",
                ajustar=True,
            )
        )
        self.tabla = tabla_disponibles()
        llenar_disponibles(self.tabla, cajas)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_botones(boton("Cerrar", self.accept)))


def ver_disponibles(padre, version):
    DialogoCajasDisponibles(padre, version).exec()


def abrir(ventana):
    lote = cargar_lote_activo()
    if not lote:
        avisos.aviso(
            ventana,
            "Sin OT activa",
            "Las cajas de Office se asignan a los equipos de una OT.\n\n"
            "Abrí o creá una OT antes.",
        )
        return False
    if lote["mov"] != "Entrega":
        avisos.aviso(ventana, "OT de retiro", "Office se asigna solo en OT de entrega.")
        return False
    if not office_ot.equipos(lote):
        avisos.aviso(
            ventana, "OT sin notebooks", f"{etiqueta_lote(lote)} todavía no tiene notebooks."
        )
        return False
    DialogoAsignarOffice(ventana, lote).exec()
    return False
