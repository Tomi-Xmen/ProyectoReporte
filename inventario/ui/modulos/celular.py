"""
Panel del lector celular: enciende el servidor, muestra el QR para emparejar
el celular y registra cada escaneo que llega.

Una vez encendido, el servidor sigue andando aunque se cierre esta ventana:
se apaga solo con "Apagar" o al salir del programa. Con "Encender solo al
abrir el programa" arranca junto con la app y con el mismo código, así el
celular queda emparejado de un día para otro sin escanear el QR otra vez.
La ventana no es modal: se puede seguir usando el menú al mismo tiempo.
Viene apagado: si nadie lo enciende nunca, no se abre ningún puerto.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...nucleo.api_celular import (
    ApiCelular,
    cargar_preferencias,
    describir_respuesta,
    guardar_preferencias,
    token_nuevo,
)
from .. import avisos, reporte_vivo
from ..servidor_celular import PUERTO_DEFAULT, ServidorCelular, interfaces_locales
from ..widgets import Banner, boton, etiqueta, tabla

# El QR se dibuja con segno (Python puro, sin dependencias). Si falta, el
# panel sigue funcionando y los datos se copian con el botón.
try:
    import segno

    SEGNO_AVAILABLE = True
except ImportError:
    SEGNO_AVAILABLE = False

_MAX_FILAS_REGISTRO = 200
_panel = None  # una sola instancia: abrir() de nuevo la trae al frente


class VistaQR(QWidget):
    """QR dibujado con QPainter: siempre negro sobre blanco, en tema claro u oscuro."""

    _MARGEN = 4  # zona de silencio en módulos, la que piden los lectores

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 260)
        self._matriz = None

    def fijar(self, texto):
        self._matriz = segno.make_qr(texto, error="m").matrix if (texto and SEGNO_AVAILABLE) else None
        self.update()

    def paintEvent(self, _evento):
        if not self._matriz:
            return
        modulos = len(self._matriz) + 2 * self._MARGEN
        lado = min(self.width(), self.height())
        paso = max(1, lado // modulos)
        total = paso * modulos
        x0 = (self.width() - total) // 2
        y0 = (self.height() - total) // 2

        p = QPainter(self)
        p.fillRect(x0, y0, total, total, QColor("white"))
        negro = QColor("black")
        for fila, valores in enumerate(self._matriz):
            for col, oscuro in enumerate(valores):
                if oscuro:
                    p.fillRect(
                        x0 + (col + self._MARGEN) * paso,
                        y0 + (fila + self._MARGEN) * paso,
                        paso,
                        paso,
                        negro,
                    )
        p.end()


class PanelCelular(QDialog):
    def __init__(self, ventana):
        super().__init__(ventana)
        self.ventana = ventana
        self.setWindowTitle("Lector celular")
        self.resize(860, 760)
        self.api = None
        self.servidor = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(etiqueta("📱 Lector celular", "titulo"))
        layout.addWidget(
            etiqueta(
                "Usá el celular como lector de códigos para las OT y guías abiertas. "
                "El celular y esta PC tienen que estar en la misma red Wi-Fi. "
                "Encendido, el celular sigue conectado aunque cierres esta "
                "ventana; se desconecta con \"Apagar\" o al salir del programa.",
                "ayuda",
                ajustar=True,
            )
        )

        self.banner = Banner("Apagado. Encendelo para emparejar el celular.", "info")
        layout.addWidget(self.banner)

        fila = QHBoxLayout()
        fila.addWidget(etiqueta("Red:", "campo"))
        self.combo_ip = QComboBox()
        self.combo_ip.currentIndexChanged.connect(self._refrescar_qr)
        fila.addWidget(self.combo_ip, 1)
        self.btn_encender = boton("▶ Encender", self._alternar, variante="exito")
        fila.addWidget(self.btn_encender)
        layout.addLayout(fila)

        self.prefs = cargar_preferencias()
        opciones = QHBoxLayout()
        self.chk_al_iniciar = QCheckBox("Encender solo al abrir el programa (el celular queda emparejado)")
        self.chk_al_iniciar.setChecked(self.prefs["encender_al_iniciar"] or not self.prefs["token"])
        self.chk_al_iniciar.toggled.connect(self._cambio_al_iniciar)
        opciones.addWidget(self.chk_al_iniciar, 1)
        self.btn_codigo = boton("🔄 Código nuevo", self._codigo_nuevo)
        self.btn_codigo.setToolTip(
            "Cambia el código del QR: todo celular emparejado tiene que escanearlo de nuevo."
        )
        opciones.addWidget(self.btn_codigo)
        layout.addLayout(opciones)

        centro = QHBoxLayout()
        self.qr = VistaQR()
        centro.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)
        lateral = QVBoxLayout()
        self.lbl_qr = etiqueta("", "ayuda", ajustar=True)
        self.lbl_url = etiqueta("", "ruta", ajustar=True)
        self.lbl_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_contacto = etiqueta("", "campo", ajustar=True)
        self.btn_copiar = boton("📋 Copiar datos de emparejamiento", self._copiar)
        self.btn_copiar.setToolTip(
            "Copia lo mismo que trae el QR. Sirve para probar con "
            "herramientas/simular_celular.py sin la app."
        )
        self.btn_vivo = boton("📡 Reportes en vivo", self._abrir_en_vivo, variante="ot")
        self.btn_vivo.setToolTip(
            "Abre en el navegador los reportes de las OT abiertas: se "
            "actualizan solos con cada escaneo del celular."
        )
        for w in (self.lbl_qr, self.lbl_url, self.lbl_contacto, self.btn_copiar, self.btn_vivo):
            lateral.addWidget(w)
        lateral.addStretch(1)
        centro.addLayout(lateral, 1)
        layout.addLayout(centro)

        layout.addWidget(etiqueta("ÚLTIMOS ESCANEOS", "seccion"))
        self.tabla = tabla([("Hora", 80), ("Lote", 220), ("Código", 160), ("Resultado", None)])
        layout.addWidget(self.tabla, 1)

        self._cargar_ips()
        self._mostrar_apagado()

    # ── Estado ───────────────────────────────────────────
    def _cargar_ips(self):
        self.combo_ip.blockSignals(True)
        self.combo_ip.clear()
        for ip, nombre in interfaces_locales():
            self.combo_ip.addItem(f"{ip}  ·  {nombre}", ip)
        self.combo_ip.blockSignals(False)

    def _ip(self):
        return self.combo_ip.currentData()

    def _mostrar_apagado(self):
        self.btn_encender.setText("▶ Encender")
        self.btn_encender.setProperty("variante", "exito")
        self.btn_encender.style().polish(self.btn_encender)
        self.btn_copiar.setEnabled(False)
        self.qr.fijar(None)
        self.lbl_qr.setText("")
        self.lbl_url.setText("")
        self.lbl_contacto.setText("")

    def _alternar(self):
        if self.servidor and self.servidor.activo:
            self.apagar()
        else:
            self.encender()

    def encender(self, silencioso=False):
        """silencioso: al abrir el programa no se muestran ventanas de error."""
        if self._ip() is None:
            self._cargar_ips()
        if self._ip() is None:
            if silencioso:
                self.banner.fijar("No se encendió solo: esta PC no tiene IP de red local.", "aviso")
                return False
            avisos.aviso(
                self,
                "Sin red local",
                "Esta PC no tiene una IP de red local.\n\n"
                "Conectala al mismo Wi-Fi o red que el celular y probá de nuevo.",
            )
            return False

        # El mismo token y puerto de la última vez: el celular emparejado
        # vuelve a conectarse solo. "Código nuevo" lo cambia.
        if not self.prefs["token"]:
            self.prefs["token"] = token_nuevo()
        self.api = ApiCelular(token=self.prefs["token"], al_evento=self._registrar_evento)
        self.servidor = ServidorCelular(self.api, self)
        self.servidor.contacto.connect(self._contacto)
        puerto = self.servidor.iniciar(self.prefs["puerto"] or PUERTO_DEFAULT)
        if not puerto:
            self.servidor = None
            if silencioso:
                self.banner.fijar("No se encendió solo: los puertos del lector están ocupados.", "aviso")
                return False
            avisos.error(
                self,
                "No se pudo encender",
                "Los puertos del lector están ocupados por otro programa.",
            )
            return False

        self.prefs["puerto"] = puerto
        self.prefs["encender_al_iniciar"] = self.chk_al_iniciar.isChecked()
        guardar_preferencias(self.prefs)

        self.btn_encender.setText("■ Apagar")
        self.btn_encender.setProperty("variante", "envio")
        self.btn_encender.style().polish(self.btn_encender)
        self.btn_copiar.setEnabled(True)
        self.lbl_contacto.setText("Esperando al celular…")
        self._refrescar_qr()
        self._refrescar_menu()
        return True

    def apagar(self):
        if self.servidor:
            self.servidor.detener()
        self.servidor = None
        self.api = None
        self.banner.fijar("Apagado. El celular ya no puede registrar equipos.", "info")
        self._mostrar_apagado()
        self._refrescar_menu()

    def _cambio_al_iniciar(self, marcado):
        self.prefs["encender_al_iniciar"] = marcado
        guardar_preferencias(self.prefs)

    def _codigo_nuevo(self):
        if not avisos.confirmar(
            self,
            "Código nuevo",
            "Todo celular emparejado se desconecta y tiene que escanear el QR "
            "nuevo.\n\n¿Cambiar el código?",
        ):
            return
        self.prefs["token"] = token_nuevo()
        guardar_preferencias(self.prefs)
        if self.api:
            self.api.token = self.prefs["token"]
            self._refrescar_qr()

    def _refrescar_qr(self, *_):
        if not (self.servidor and self.servidor.activo and self._ip()):
            return
        puerto = self.servidor.puerto
        texto = self.api.texto_qr(self._ip(), puerto)
        self.qr.fijar(texto)
        self.banner.fijar(f"Encendido · escuchando en {self._ip()}:{puerto}", "ok")
        self.lbl_url.setText(f"http://{self._ip()}:{puerto}")
        self.lbl_qr.setText(
            "Escaneá este código desde la app del celular para emparejarlo."
            if SEGNO_AVAILABLE
            else "No se puede dibujar el QR (falta la librería 'segno'). "
            "Copiá los datos con el botón."
        )

    def _abrir_en_vivo(self):
        if not reporte_vivo.abrir_indice():
            avisos.error(self, "Reporte en vivo", "No se pudo abrir el reporte en vivo.")

    def _copiar(self):
        if self.api and self.servidor and self._ip():
            QApplication.clipboard().setText(
                self.api.texto_qr(self._ip(), self.servidor.puerto)
            )

    # ── Eventos del celular ──────────────────────────────
    def _contacto(self, ip):
        self.lbl_contacto.setText(f"📶 Celular conectado desde {ip}")

    def _registrar_evento(self, evento):
        # Lo último arriba.
        self.tabla.insertRow(0)
        valores = (
            evento["hora"],
            evento["lote"],
            evento["valor"] or "—",
            describir_respuesta(evento["respuesta"]),
        )
        for col, valor in enumerate(valores):
            self.tabla.setItem(0, col, QTableWidgetItem(valor))
        while self.tabla.rowCount() > _MAX_FILAS_REGISTRO:
            self.tabla.removeRow(self.tabla.rowCount() - 1)
        self._refrescar_menu()

    def _refrescar_menu(self):
        """
        El contador de equipos del menú se pone al día solo si el menú está a
        la vista: si el PC está en medio de un formulario, no se lo toca.
        """
        inicio = getattr(self.ventana, "inicio", None)
        paginas = getattr(self.ventana, "paginas", None)
        if inicio is not None and paginas is not None and paginas.currentWidget() is inicio:
            inicio.refrescar()

    def done(self, resultado):
        # Cerrar solo oculta: el servidor sigue y el registro se conserva
        # para cuando se vuelva a abrir. Se apaga con el botón o al salir.
        super().done(resultado)


def _panel_de(ventana):
    global _panel
    if _panel is None:
        _panel = PanelCelular(ventana)
    return _panel


def encender_al_iniciar(ventana):
    """Al abrir el programa: enciende el lector si quedó marcado, sin mostrar el panel."""
    if cargar_preferencias()["encender_al_iniciar"]:
        _panel_de(ventana).encender(silencioso=True)


def esta_encendido():
    return bool(_panel and _panel.servidor and _panel.servidor.activo)


def abrir(ventana):
    panel = _panel_de(ventana)
    panel.show()
    panel.raise_()
    panel.activateWindow()
    return False
