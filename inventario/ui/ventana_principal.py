"""
Ventana principal: inicio (menú), pantalla de escaneo y formulario de
registro, como páginas de un QStackedWidget. Las demás herramientas abren
como diálogos encima.
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..nucleo import config, lotes
from ..nucleo.escaner import get_inventory_fast
from ..nucleo.lotes import MOV_CFG, carpeta_lote, etiqueta_lote
from . import acciones, avisos
from .componentes import COMPONENTES, RevisionComponentes, SeccionOffice
from .dialogos import nuevo_lote
from .modulos import etiquetas, mover_ot, panel_clonacion, transformadores
from .tareas import en_segundo_plano
from .widgets import Tarjeta, TarjetaAccion, area_scroll, boton, etiqueta


class PaginaInicio(QWidget):
    """
    Menú. Los equipos escaneados van SIEMPRE al lote activo: mostrarlo grande
    y permanente evita el error caro, escanear contra la OT equivocada.
    """

    def __init__(self, ventana):
        super().__init__()
        self.ventana = ventana
        self.setObjectName("pagina")
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)

        contenido = QWidget()
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        externo.addWidget(area_scroll(contenido))

        layout.addWidget(etiqueta("🖥️ Control de Inventario", "titulo"))
        layout.addWidget(etiqueta("Arrienda.cl · Entregas y retiros de equipos", "subtitulo"))

        # --- OT activa -----------------------------------------------------
        self.tarjeta_ot = Tarjeta(margen=18)
        self.lbl_ot_rotulo = etiqueta("OT ACTIVA", "seccion")
        self.lbl_ot = etiqueta("", "titulo-dialogo", ajustar=True)
        self.lbl_ot_detalle = etiqueta("", "subtitulo", ajustar=True)
        self.lbl_otras = etiqueta("", "ayuda", ajustar=True)
        for w in (self.lbl_ot_rotulo, self.lbl_ot, self.lbl_ot_detalle, self.lbl_otras):
            self.tarjeta_ot.cuerpo.addWidget(w)
        fila_ot = QHBoxLayout()
        fila_ot.setSpacing(8)
        fila_ot.addWidget(boton("➕ Nueva OT", self._con(acciones.nueva_ot), variante="ot"))
        self.btn_cambiar = boton("🔄 Cambiar OT", self._con(acciones.cambiar_ot), variante="ot")
        fila_ot.addWidget(self.btn_cambiar)
        fila_ot.addStretch(1)
        self.tarjeta_ot.cuerpo.addLayout(fila_ot)
        layout.addWidget(self.tarjeta_ot)

        # Equipos del modelo anterior (sueltos, sin carpeta de OT): hay que
        # adoptarlos en una OT para que entren al fusionado.
        self.btn_legacy = boton("", self._con(acciones.migrar_legacy), variante="envio")
        layout.addWidget(self.btn_legacy)

        btn_escanear = boton(
            "🔍  Escanear este equipo",
            ventana.iniciar_escaneo,
            variante="primario",
            tamano="grande",
        )
        btn_escanear.setToolTip("Lee el hardware y crea el registro en la OT activa")
        layout.addWidget(btn_escanear)

        # El color agrupa, no decora: celeste = manejo de la OT, verde =
        # cerrarla, naranja = sale de esta máquina, morado = reparación,
        # esmeralda = clonación, pizarra = utilitario suelto.
        self._seccion(
            layout,
            "Orden de trabajo",
            [
                ("↔️", "Mover equipos a otra OT",
                 "Pasa equipos de la OT activa a otra OT abierta.", "celeste", mover_ot.abrir),
                ("✅", "Cerrar OT",
                 "Regenera el FUSIONADO y marca la OT como finalizada.", "verde",
                 acciones.cerrar_ot),
            ],
        )
        self._seccion(
            layout,
            "Archivo y respaldo",
            [
                ("🚀", "Enviar OT al servidor",
                 f"Sube lo pendiente por SCP a {config.SCP_HOST}.", "naranja",
                 acciones.enviar_al_servidor),
                ("🔧", "Reconstruir / reparar desde JSONs",
                 "Rearma HTML y FUSIONADO de una OT, un cliente o un grupo.", "morado",
                 acciones.reconstruir_desde_json),
                ("🛰️", "Panel de clonación",
                 "OT publicada y seguimiento de los equipos clonados.", "esmeralda",
                 panel_clonacion.abrir),
            ],
        )
        self._seccion(
            layout,
            "Herramientas",
            [
                ("🔌", "Agregar transformadores",
                 "Asigna cargadores a los equipos de la OT activa.", "pizarra",
                 transformadores.abrir),
                ("🏷️", "Etiqueta manual",
                 "Etiqueta de diagnóstico para equipos malos.", "pizarra", etiquetas.abrir),
                ("💻", "Cambiar nombre del equipo",
                 "Renombra esta PC a ARR-<serial de BIOS>.", "pizarra",
                 acciones.cambiar_nombre_equipo),
            ],
        )
        layout.addStretch(1)

    def _con(self, accion):
        """Corre la acción con esta ventana como padre y refresca el menú."""

        def _correr(*_):
            accion(self.ventana)
            self.ventana.mostrar_menu()

        return _correr

    def _seccion(self, layout, titulo, items):
        layout.addWidget(etiqueta(titulo.upper(), "seccion"))
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(12)
        grilla.setVerticalSpacing(12)
        for i, (icono, nombre, desc, acento, accion) in enumerate(items):
            fila, col = divmod(i, 2)
            grilla.addWidget(
                TarjetaAccion(icono, nombre, desc, acento, self._con(accion)), fila, col
            )
        grilla.setColumnStretch(0, 1)
        grilla.setColumnStretch(1, 1)
        layout.addLayout(grilla)

    def refrescar(self):
        lote = lotes.cargar_lote_activo()
        abiertos = lotes.listar_lotes_abiertos()

        if lote:
            self.tarjeta_ot.fijar_estado("ok")
            self.lbl_ot_rotulo.setText("📍 OT ACTIVA")
            self.lbl_ot.setText(etiqueta_lote(lote))
            self.lbl_ot_detalle.setText(
                f"{lotes.contar_equipos(lote['ruta'])} equipo(s) escaneado(s)"
            )
        else:
            self.tarjeta_ot.fijar_estado("aviso")
            self.lbl_ot_rotulo.setText("⚠️ SIN OT ACTIVA")
            self.lbl_ot.setText("Ningún equipo tiene dónde caer todavía")
            self.lbl_ot_detalle.setText(
                "Creá una OT o activá una en curso antes de escanear."
            )

        otras = [
            o
            for o in abiertos
            if not lote or os.path.normcase(o["ruta"]) != os.path.normcase(lote["ruta"])
        ]
        if otras:
            resumen = ", ".join(
                f"{o['cliente'].replace('_', ' ')} {carpeta_lote(o['mov'], o['numero'])}"
                f" ({o['equipos']})"
                for o in otras[:3]
            )
            if len(otras) > 3:
                resumen += f" y {len(otras) - 3} más"
            self.lbl_otras.setText(f"También abiertas: {resumen}")
        self.lbl_otras.setVisible(bool(otras))
        self.btn_cambiar.setText(f"🔄 Cambiar OT ({len(abiertos)})")

        legacy = sum(len(v) for v in lotes.pendientes_legacy().values())
        self.btn_legacy.setText(f"⚠️ Migrar {legacy} equipo(s) del formato anterior")
        self.btn_legacy.setVisible(bool(legacy))


class PaginaEscaneo(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("pagina")
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(
            etiqueta("⏳", alinear=Qt.AlignmentFlag.AlignCenter),
        )
        self.lbl = etiqueta(
            "Escaneando hardware", "titulo", alinear=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(self.lbl)
        layout.addWidget(
            etiqueta(
                "Esto tomará unos segundos.",
                "subtitulo",
                alinear=Qt.AlignmentFlag.AlignCenter,
            )
        )
        barra = QProgressBar()
        barra.setRange(0, 0)
        barra.setTextVisible(False)
        barra.setFixedWidth(280)
        layout.addSpacing(10)
        layout.addWidget(barra, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        self._puntos = 0
        self._timer = QTimer(self)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._animar)

    def _animar(self):
        self._puntos = (self._puntos + 1) % 4
        self.lbl.setText("Escaneando hardware" + "." * self._puntos)

    def arrancar(self):
        self._puntos = 0
        self._timer.start()

    def detener(self):
        self._timer.stop()


class PaginaFormulario(QWidget):
    """Formulario de registro del equipo recién escaneado."""

    def __init__(self, ventana, data, lote):
        super().__init__()
        self.ventana, self.data, self.lote = ventana, data, lote
        self.setObjectName("pagina")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 16)
        layout.setSpacing(10)

        cabecera = QHBoxLayout()
        cabecera.addWidget(boton("⬅ Volver", ventana.mostrar_menu, variante="fantasma"))
        cabecera.addSpacing(8)
        cabecera.addWidget(etiqueta("💻 Asistente de Entrega / Retiro", "titulo"))
        cabecera.addStretch(1)
        layout.addLayout(cabecera)

        info = Tarjeta(margen=10)
        lbl_equipo = etiqueta(
            f"{data['model']}   |   S/N: {data['serial']}",
            "dato",
            alinear=Qt.AlignmentFlag.AlignCenter,
        )
        lbl_equipo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.cuerpo.addWidget(lbl_equipo)
        layout.addWidget(info)

        # El contenido scrollea; el botón de guardar queda siempre visible abajo.
        contenido = QWidget()
        cuerpo = QVBoxLayout(contenido)
        cuerpo.setContentsMargins(0, 4, 0, 4)
        cuerpo.setSpacing(12)

        # El movimiento y el número ya no se eligen por equipo: los define la
        # OT activa. Se muestran fijos para que siempre sea evidente dónde va
        # a caer lo que se está escaneando.
        cfg = MOV_CFG[lote["mov"]]
        destino = Tarjeta(estado="ok")
        destino.cuerpo.addWidget(etiqueta("🚚 DESTINO DE ESTE EQUIPO", "seccion"))
        destino.cuerpo.addWidget(etiqueta(f"📍 {etiqueta_lote(lote)}", "ruta"))
        destino.cuerpo.addWidget(
            etiqueta(
                f"{cfg['etiqueta_campo']}: {lote['numero']}\n"
                f"{cfg['etiqueta_campo_sec']}: {lote.get('numero_sec') or '—'}",
                "subtitulo",
            )
        )
        cuerpo.addWidget(destino)

        # La revisión de componentes solo aplica a retiros.
        self.revision = None
        if lote["mov"] == "Retiro":
            tarjeta = Tarjeta()
            tarjeta.cuerpo.addWidget(etiqueta("⚠️ REVISIÓN DE COMPONENTES", "seccion"))
            self.revision = RevisionComponentes(
                "Observación (obligatoria si es OBS/MALO)"
            )
            tarjeta.cuerpo.addWidget(self.revision)
            cuerpo.addWidget(tarjeta)

        extra = Tarjeta()
        extra.cuerpo.addWidget(etiqueta("Observación general para el acta", "campo"))
        self.entry_obs = QLineEdit()
        extra.cuerpo.addWidget(self.entry_obs)
        extra.cuerpo.addSpacing(4)
        self.office = SeccionOffice()
        extra.cuerpo.addWidget(self.office)
        cuerpo.addWidget(extra)
        cuerpo.addStretch(1)
        layout.addWidget(area_scroll(contenido), 1)

        btn_guardar = boton(
            f"💾 Guardar en {carpeta_lote(lote['mov'], lote['numero'])}",
            self._guardar,
            variante="primario",
            tamano="grande",
        )
        layout.addWidget(btn_guardar)
        self.entry_obs.setFocus()

    def _guardar(self):
        data, lote = self.data, self.lote
        # En una entrega no se revisan componentes, pero el JSON los lleva
        # todos en OK, igual que siempre.
        detalle = self.revision.detalle() if self.revision else [
            {"nombre": n, "estado": "OK", "obs": ""} for n in COMPONENTES
        ]
        tiene_office, office_key, version_office = self.office.valores()

        # Con varias OT en curso el mismo equipo puede acabar registrado en
        # dos. No se bloquea (a veces es legítimo re-escanear), pero se avisa.
        otro = lotes.buscar_serial_en_abiertos(data["serial"], excluir_ruta=lote["ruta"])
        if otro and not avisos.confirmar(
            self,
            "Equipo en otra OT",
            f"El serial {data['serial']} ya está registrado en:\n"
            f"{etiqueta_lote(otro)}\n\n¿Agregarlo igual a {etiqueta_lote(lote)}?",
        ):
            return

        total = lotes.guardar_equipo_general(
            lote,
            data,
            self.entry_obs.text().strip(),
            tiene_office,
            office_key,
            version_office,
            detalle,
        )
        avisos.info(
            self,
            "✅ Guardado",
            f"Equipo agregado a {etiqueta_lote(lote)}.\n\n"
            f"La OT lleva {total} equipo(s) y su JSON FUSIONADO ya está actualizado.",
        )
        self.ventana.mostrar_menu()


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Asistente de Entrega — Arrienda.cl")
        self.resize(780, 860)
        self.setMinimumSize(700, 600)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.paginas = QStackedWidget()
        self.setCentralWidget(self.paginas)
        self.inicio = PaginaInicio(self)
        self.escaneo = PaginaEscaneo()
        self.paginas.addWidget(self.inicio)
        self.paginas.addWidget(self.escaneo)
        self.formulario = None
        self.mostrar_menu()

    def _quitar_formulario(self):
        if self.formulario is not None:
            self.paginas.removeWidget(self.formulario)
            self.formulario.deleteLater()
            self.formulario = None

    def mostrar_menu(self):
        self._quitar_formulario()
        self.inicio.refrescar()
        self.paginas.setCurrentWidget(self.inicio)

    def iniciar_escaneo(self):
        # Sin OT activa no se escanea: el equipo no tendría dónde caer. Se
        # ofrece crearla en el momento para no cortar el flujo.
        lote = lotes.cargar_lote_activo()
        if not lote:
            if not avisos.confirmar(
                self,
                "Sin OT activa",
                "No hay ninguna OT activa y el equipo escaneado necesita una.\n\n"
                "¿Crear o elegir una ahora?",
            ):
                return
            lote = nuevo_lote(self)
            if not lote:
                return
            lotes.guardar_lote_activo(lote)

        self.paginas.setCurrentWidget(self.escaneo)
        self.escaneo.arrancar()
        en_segundo_plano(
            get_inventory_fast,
            al_terminar=lambda data: self._escaneo_listo(data, lote),
            al_fallar=lambda _exc: self._escaneo_listo(None, lote),
        )

    def _escaneo_listo(self, data, lote):
        self.escaneo.detener()
        if not data:
            avisos.error(self, "Error", "No se pudo obtener información del hardware.")
            self.mostrar_menu()
            return
        self._quitar_formulario()
        self.formulario = PaginaFormulario(self, data, lote)
        self.paginas.addWidget(self.formulario)
        self.paginas.setCurrentWidget(self.formulario)
