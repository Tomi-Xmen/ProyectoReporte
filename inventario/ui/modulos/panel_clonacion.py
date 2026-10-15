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
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...nucleo import fog, remoto
from ...nucleo.lotes import cargar_lote_activo, etiqueta_lote
from .. import avisos, tema
from ..tareas import con_espera
from ..widgets import Banner, agregar_fila, boton, etiqueta, fila_botones, tabla


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
            fila_botones(boton("🛰️ Multicast en FOG", self._crear_multicast, variante="envio"))
        )

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
        if not self.lote:
            avisos.aviso(self, "Sin OT", "No hay OT publicada.")
            return
        lote = self.lote
        res = self._remoto(
            "Trayendo los JSON del servidor…",
            lambda c: remoto.descargar_equipos_remotos(c, lote),
            "No se pudo traer",
        )
        if res is None:
            return
        bajados, total = res
        avisos.info(
            self,
            "Reconstrucción lista",
            f"Se trajeron {bajados} JSON del servidor.\n\n"
            f"La OT quedó con {total} equipo(s) y su HTML y JSON FUSIONADO ya se "
            f"regeneraron en:\n{lote['ruta']}",
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
