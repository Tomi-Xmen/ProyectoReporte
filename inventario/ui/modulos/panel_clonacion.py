"""
Panel central del flujo de clonación: qué OT están tomando los equipos
clonados, cuáles ya llegaron, cuáles faltan, y el cierre del lote.

Todo el estado vive en el servidor, no acá: esta ventana lo lee y lo
escribe, pero cualquier equipo puede abrirla y ver lo mismo. Cada consulta
corre en segundo plano, así la ventana no se congela mientras el SSH responde.
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...nucleo import fog, remoto, sincronizacion
from ...nucleo.lotes import cargar_lote_activo, esta_cerrado, etiqueta_lote, regenerar_lote
from .. import avisos, reporte_vivo, tema
from ..tareas import con_espera, en_segundo_plano
from ..widgets import Banner, agregar_fila, boton, etiqueta, fila_botones, tabla

# Cada cuánto se trae lo nuevo del servidor mientras el panel está abierto.
_INTERVALO_TRAER_MS = 15_000


def _seriales_recibidos(llegados):
    return {str(e.get("SERIAL", "")).strip().upper() for e in llegados}


class PanelClonacion(QDialog):
    def __init__(self, padre):
        super().__init__(padre)
        self.setWindowTitle("Panel de clonación — OT activa")
        self.resize(1000, 700)
        self.lote, self.llegados, self.esperados = None, [], []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("🛰️ Panel de clonación", "titulo"))

        self.banner = Banner("Consultando el servidor…", "aviso")
        layout.addWidget(self.banner)
        self.lbl_resumen = etiqueta("", "campo")
        layout.addWidget(self.lbl_resumen)

        self.tabla = tabla(
            [
                ("Estado", 140),
                ("N° de serie", 170),
                ("Modelo", 250),
                ("Escaneado", 140),
                ("Observaciones", None),
            ]
        )
        layout.addWidget(self.tabla, 1)

        layout.addLayout(
            fila_botones(
                boton("🔄 Refrescar", self.refrescar, variante="ot"),
                boton("📤 Publicar OT activa", self._publicar, variante="marca"),
                boton("📋 Seriales esperados", self._cargar_esperados, variante="utilidad"),
                boton("⬇️ Traer y reconstruir", self._traer_y_reconstruir, variante="reparar"),
                boton("✅ Cerrar lote", self._cerrar_remoto, variante="exito"),
            )
        )
        # Fila aparte para las acciones de FOG: así no compite por ancho con la
        # de arriba y queda lista para sumar el botón de unicast al lado.
        layout.addLayout(
            fila_botones(
                boton("🛰️ Multicast en FOG", self._crear_multicast, variante="envio"),
                boton("📡 Ver en vivo", self._ver_en_vivo, variante="ot"),
            )
        )

        # Traer automático: lo que mandan los equipos clonados entra solo a la
        # OT local y su HTML se regenera, sin apretar "Traer y reconstruir".
        fila_auto = QHBoxLayout()
        self.chk_auto = QCheckBox("🔄 Traer automático (cada 15 s)")
        self.chk_auto.setChecked(True)
        self.chk_auto.toggled.connect(self._al_cambiar_auto)
        self.lbl_auto = etiqueta("", "ayuda")
        fila_auto.addWidget(self.chk_auto)
        fila_auto.addWidget(self.lbl_auto, 1)
        layout.insertLayout(2, fila_auto)

        self._trayendo = False
        self._cerrado = False
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVALO_TRAER_MS)
        self._timer.timeout.connect(self._traer_auto)
        self._timer.start()
        QTimer.singleShot(0, self._traer_auto)

    # --- servidor ---------------------------------------------------------
    def _remoto(self, texto, tarea, titulo_error):
        """Corre tarea(cliente) con un modal de espera. None si falló (ya avisado)."""
        try:
            return con_espera(self, "Servidor", texto, remoto.con_conexion, tarea)
        except Exception as e:
            avisos.error(self, titulo_error, str(e))
            return None

    def refrescar(self):
        def tarea(cliente):
            lote = remoto.leer_lote_activo_remoto(cliente)
            if not lote:
                return None, [], []
            return (
                lote,
                remoto.equipos_remotos(cliente, lote),
                remoto.leer_esperados(cliente, lote),
            )

        datos = self._remoto(
            "Consultando el servidor…", tarea, "No se pudo consultar el servidor"
        )
        if datos is None:
            self.banner.fijar("⚠️  No se pudo consultar el servidor", "error")
            return
        self.lote, self.llegados, self.esperados = datos
        self._pintar()

    def _pintar(self):
        self.tabla.setRowCount(0)
        if not self.lote:
            self.banner.fijar(
                "⚠️  No hay ninguna OT publicada — los equipos clonados no tienen "
                "dónde mandar sus datos",
                "aviso",
            )
            self.lbl_resumen.setText("")
            return

        self.banner.fijar(f"📍 OT publicada: {etiqueta_lote(self.lote)}", "ok")

        recibidos = {}
        for eq in self.llegados:
            recibidos[str(eq.get("SERIAL", "")).strip().upper()] = eq
        esperados_up = {s.upper() for s in self.esperados}

        for sn, eq in recibidos.items():
            esperado = not self.esperados or sn in esperados_up
            data = eq.get("DATA") or {}
            fila = agregar_fila(
                self.tabla,
                (
                    "✓ llegó" if esperado else "⚠ no esperado",
                    eq.get("SERIAL", ""),
                    eq.get("MODELO", "") or data.get("model", ""),
                    data.get("fecha", "") or eq.get("ESCANEADO", ""),
                    eq.get("OBS", ""),
                ),
                centradas=(0, 1),
            )
            self._colorear(fila, "ok" if esperado else "sobra")

        faltan = [s for s in self.esperados if s.upper() not in recibidos]
        for sn in faltan:
            fila = agregar_fila(
                self.tabla, ("✗ falta", sn, "—", "—", "todavía no envió"), centradas=(0, 1)
            )
            self._colorear(fila, "falta")

        if self.esperados:
            self.lbl_resumen.setText(
                f"Llegaron {len(recibidos)} de {len(self.esperados)} esperados  ·  "
                f"faltan {len(faltan)}"
            )
        else:
            self.lbl_resumen.setText(
                f"{len(recibidos)} equipo(s) recibidos  ·  sin lista esperada cargada"
            )

    def _colorear(self, fila, marca):
        texto, fondo = {
            "ok": ("verde", None),
            "falta": ("error_texto", "error_fondo"),
            "sobra": ("aviso_texto", "aviso_fondo"),
        }[marca]
        for col in range(self.tabla.columnCount()):
            item = self.tabla.item(fila, col)
            item.setForeground(QColor(tema.color(texto)))
            if fondo:
                item.setBackground(QColor(tema.color(fondo)))

    # --- traer automático -------------------------------------------------
    def _al_cambiar_auto(self, activo):
        if activo:
            self._timer.start()
            self._traer_auto()
        else:
            self._timer.stop()
            self.lbl_auto.setText("Pausado: usá \"Traer y reconstruir\" para traer a mano.")

    def _traer_auto(self):
        """Una vuelta en segundo plano: sin modal, la ventana sigue usable."""
        if self._trayendo or self._cerrado or not self.chk_auto.isChecked():
            return
        self._trayendo = True
        en_segundo_plano(
            remoto.con_conexion,
            sincronizacion.consultar,
            al_terminar=self._al_traer,
            al_fallar=self._al_fallar_traer,
        )

    def _al_traer(self, res):
        # Vuelve al hilo de la interfaz: acá se escribe, nunca en el de trabajo.
        self._trayendo = False
        if self._cerrado:
            return
        traido = self._aplicar_traido(res)
        if traido is None:
            self.lbl_auto.setText("Sin OT publicada.")
            return
        local, escritos = traido
        if esta_cerrado(local["ruta"]):
            self.lbl_auto.setText(
                f"⚠️ {etiqueta_lote(local)} está cerrada en esta PC: no se trae nada."
            )
        else:
            nuevos = f" · {escritos} equipo(s) nuevo(s) o actualizado(s)" if escritos else ""
            self.lbl_auto.setText(f"Última vuelta {res['hora']}{nuevos}")

    def _aplicar_traido(self, res):
        """
        Escribe lo que trajo sincronizacion.consultar() y pinta la tabla.
        Devuelve (lote local, equipos escritos), o None sin OT publicada. Una
        OT cerrada en esta PC no se toca.
        """
        if res is None:
            self.lote, self.llegados, self.esperados = None, [], []
            self._pintar()
            return None
        lote = res["lote"]
        local = sincronizacion.lote_local(lote)
        escritos = 0
        if not esta_cerrado(local["ruta"]):
            escritos = sincronizacion.aplicar(lote, res["huellas"], res["contenidos"])
        self.lote, self.esperados = lote, res["esperados"]
        self.llegados = sincronizacion.equipos_locales(lote, res["huellas"])
        self._pintar()
        if escritos:
            self._refrescar_menu()
        return local, escritos

    def _al_fallar_traer(self, exc):
        self._trayendo = False
        if not self._cerrado:
            primera = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            self.lbl_auto.setText(f"⚠️ Sin conexión con el servidor, se reintenta: {primera}")

    def _refrescar_menu(self):
        inicio = getattr(self.parent(), "inicio", None)
        if inicio is not None:
            inicio.refrescar()

    def _ver_en_vivo(self):
        if not self.lote:
            avisos.aviso(self, "Sin OT", "No hay OT publicada.")
            return
        local = sincronizacion.lote_local(self.lote)
        if not reporte_vivo.abrir_lote(local):
            avisos.error(self, "Reporte en vivo", "No se pudo abrir el reporte en vivo.")

    def done(self, resultado):
        # Una vuelta que todavía corre no escribe nada al terminar.
        self._cerrado = True
        self._timer.stop()
        super().done(resultado)

    # --- acciones ---------------------------------------------------------
    def _publicar(self):
        lote = cargar_lote_activo()
        if not lote:
            avisos.aviso(
                self,
                "Sin OT activa",
                "No hay una OT activa en este equipo.\n\n"
                "Creá o cambiá de OT desde el menú y volvé a publicar.",
            )
            return
        if not avisos.confirmar(
            self,
            "Publicar OT",
            f"¿Publicar {etiqueta_lote(lote)} como OT activa?\n\n"
            "Todos los equipos que se clonen a partir de ahora van a mandar sus "
            "datos a esta OT.",
        ):
            return
        if self._remoto(
            "Publicando la OT…",
            lambda c: remoto.publicar_lote_activo(c, lote) or True,
            "No se pudo publicar",
        ):
            avisos.info(self, "Publicada", etiqueta_lote(lote))
            self.refrescar()

    def _cargar_esperados(self):
        if not self.lote:
            avisos.aviso(self, "Sin OT", "Primero publicá una OT.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Seriales esperados")
        dlg.resize(460, 520)
        cuerpo = QVBoxLayout(dlg)
        cuerpo.setContentsMargins(20, 18, 20, 18)
        cuerpo.addWidget(etiqueta("Seriales que deben llegar", "titulo-dialogo"))
        cuerpo.addWidget(
            etiqueta("Uno por línea. Pegá la lista de equipos a clonar.", "subtitulo")
        )
        caja = QPlainTextEdit("\n".join(self.esperados))
        cuerpo.addWidget(caja, 1)

        def guardar():
            seriales = [s.strip() for s in caja.toPlainText().splitlines() if s.strip()]
            guardados = self._remoto(
                "Guardando la lista…",
                lambda c: remoto.guardar_esperados(c, self.lote, seriales),
                "No se pudo guardar",
            )
            if guardados is not None:
                dlg.accept()
                avisos.info(self, "Lista guardada", f"{len(guardados)} serial(es).")
                self.refrescar()

        cuerpo.addLayout(
            fila_botones(
                boton("💾 Guardar lista", guardar, variante="exito"),
                boton("Cancelar", dlg.reject),
            )
        )
        dlg.exec()

    def _traer_y_reconstruir(self):
        """
        Lo mismo que el traer automático, a pedido y con aviso. Antes bajaba
        TODO del servidor y pisaba lo local: un cargador cargado acá o desde el
        celular se perdía y lo quitado a mano volvía. Ahora baja solo lo nuevo
        o lo que cambió allá, y regenera el HTML y el FUSIONADO aunque no haya
        nada nuevo (sirve también para rearmar un reporte roto).
        """
        if not self.lote:
            avisos.aviso(self, "Sin OT", "No hay OT publicada.")
            return
        # Envuelto en un dict: _remoto devuelve None cuando falla, y consultar
        # devuelve None cuando no hay OT publicada; hay que distinguirlos.
        datos = self._remoto(
            "Trayendo los JSON del servidor…",
            lambda c: {"res": sincronizacion.consultar(c)},
            "No se pudo traer",
        )
        if datos is None:
            return
        traido = self._aplicar_traido(datos["res"])
        if traido is None:
            avisos.aviso(self, "Sin OT", "Ya no hay OT publicada en el servidor.")
            return
        local, escritos = traido
        if esta_cerrado(local["ruta"]):
            avisos.aviso(
                self,
                "OT cerrada",
                f"{etiqueta_lote(local)} está cerrada en esta PC: no se trajo nada.\n\n"
                "Reabrila desde \"Nueva OT\" si tiene que recibir más equipos.",
            )
            return
        total = regenerar_lote(local)
        avisos.info(
            self,
            "Reconstrucción lista",
            f"Se trajeron {escritos} equipo(s) nuevo(s) o actualizado(s) del servidor.\n"
            "Lo cargado en esta PC (cargadores, correcciones) no se pisó y lo "
            "quitado a mano no volvió.\n\n"
            f"La OT quedó con {total} equipo(s) y su HTML y JSON FUSIONADO se "
            f"regeneraron en:\n{local['ruta']}",
        )

    def _cerrar_remoto(self):
        if not self.lote:
            avisos.aviso(self, "Sin OT", "No hay OT publicada.")
            return
        recibidos = _seriales_recibidos(self.llegados)
        faltan = [s for s in self.esperados if s.upper() not in recibidos]
        aviso = ""
        if faltan:
            aviso = (
                f"\n\n⚠️ Todavía faltan {len(faltan)} equipo(s):\n"
                + "\n".join(f"  • {s}" for s in faltan[:10])
                + ("\n  …" if len(faltan) > 10 else "")
                + "\n\nSi cerrás ahora, esos equipos ya no van a poder enviar."
            )
        if not avisos.confirmar(
            self,
            "Cerrar lote",
            f"¿Cerrar {etiqueta_lote(self.lote)} en el servidor?\n\n"
            f"Recibidos: {len(self.llegados)} equipo(s).{aviso}",
        ):
            return
        lote, total = self.lote, len(self.llegados)
        if self._remoto(
            "Cerrando el lote…",
            lambda c: remoto.cerrar_lote_remoto(c, lote, total) or True,
            "No se pudo cerrar",
        ):
            avisos.info(
                self,
                "Lote cerrado",
                "La OT quedó cerrada en el servidor y ya no es la OT activa.",
            )
            self.refrescar()

    def _crear_multicast(self):
        try:
            imagenes = con_espera(
                self, "FOG", "Consultando las imágenes de FOG…", fog.imagenes_habilitadas
            )
        except Exception as e:
            avisos.error(self, "No se pudo conectar a FOG", str(e))
            return
        if not imagenes:
            avisos.aviso(
                self, "Sin imágenes", "FOG no devolvió ninguna imagen habilitada."
            )
            return
        DialogoMulticast(self, imagenes, self.lote, len(self.esperados) or 1).exec()


class DialogoMulticast(QDialog):
    """Equivalente a "Image Management → Multicast Image" de la web de FOG."""

    def __init__(self, padre, imagenes, lote, cantidad_sugerida):
        super().__init__(padre)
        self.setWindowTitle("Crear sesión multicast en FOG")
        self.setMinimumWidth(480)
        self._por_nombre = {i["name"]: i["id"] for i in imagenes}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(etiqueta("🛰️ Nueva sesión multicast", "titulo-dialogo"))

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.entry_nombre = QLineEdit(etiqueta_lote(lote) if lote else "")
        form.addRow(etiqueta("Nombre de la sesión:", "campo"), self.entry_nombre)
        self.combo_imagen = QComboBox()
        self.combo_imagen.addItems(list(self._por_nombre))
        self.combo_imagen.setCurrentIndex(-1)
        self.combo_imagen.setPlaceholderText("Elegí una imagen")
        form.addRow(etiqueta("Imagen:", "campo"), self.combo_imagen)
        self.spin_cantidad = QSpinBox()
        self.spin_cantidad.setRange(1, 999)
        self.spin_cantidad.setValue(cantidad_sugerida)
        form.addRow(etiqueta("Cantidad de equipos:", "campo"), self.spin_cantidad)
        layout.addLayout(form)

        layout.addWidget(
            etiqueta(
                "Los equipos se siguen uniendo a mano por PXE con este nombre, "
                "igual que hoy en la web de FOG.",
                "ayuda",
                ajustar=True,
            )
        )
        layout.addLayout(
            fila_botones(
                boton("🚀 Crear sesión", self._confirmar, variante="exito"),
                boton("Cancelar", self.reject),
            )
        )

    def _confirmar(self):
        nombre = self.entry_nombre.text().strip()
        imagen = self.combo_imagen.currentText()
        cantidad = self.spin_cantidad.value()
        if not nombre:
            avisos.aviso(self, "Falta el nombre", "Ponele un nombre a la sesión.")
            return
        if imagen not in self._por_nombre:
            avisos.aviso(self, "Falta la imagen", "Elegí una imagen de la lista.")
            return
        try:
            sesion = con_espera(
                self,
                "FOG",
                "Creando la sesión multicast…",
                fog.fog_crear_sesion_multicast,
                nombre,
                self._por_nombre[imagen],
                cantidad,
            )
        except Exception as e:
            avisos.error(self, "No se pudo crear la sesión", str(e))
            return
        self.accept()
        avisos.info(
            self.parent(),
            "Sesión creada",
            f"'{sesion.get('name')}' arrancó en el puerto {sesion.get('port')}.\n\n"
            f"Ahora booteá por PXE los {cantidad} equipo(s) y elegí esa sesión "
            "para unirse, igual que siempre.",
        )


def abrir(ventana):
    panel = PanelClonacion(ventana)
    # La primera consulta arranca recién con el panel en pantalla, para que
    # el modal de espera quede encima de él y no de la ventana principal.
    QTimer.singleShot(0, panel.refrescar)
    panel.exec()
    return False
