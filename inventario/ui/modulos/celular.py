"""
Panel del lector celular: enciende el servidor, muestra el QR para emparejar
el celular y registra cada escaneo que llega.

El servidor vive mientras esta ventana está abierta y se apaga al cerrarla:
"panel abierto = celular conectado". La ventana no es modal, así que se puede
seguir usando el menú (escanear hardware, transformadores…) al mismo tiempo.
Viene apagado: si nadie lo enciende, no se abre ningún puerto.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...nucleo.api_celular import ApiCelular, describir_respuesta
from .. import avisos
from ..servidor_celular import ServidorCelular, interfaces_locales
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
                "Mientras esta ventana esté abierta el celular puede registrar "
                "equipos; al cerrarla se desconecta.",
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
        for w in (self.lbl_qr, self.lbl_url, self.lbl_contacto, self.btn_copiar):
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

    def encender(self):
        if self._ip() is None:
            self._cargar_ips()
        if self._ip() is None:
            avisos.aviso(
                self,
                "Sin red local",
                "Esta PC no tiene una IP de red local.\n\n"
                "Conectala al mismo Wi-Fi o red que el celular y probá de nuevo.",
            )
            return False

        # Token nuevo en cada encendido: apagar y encender desempareja a
        # cualquier celular que tuviera el QR anterior.
        self.api = ApiCelular(al_evento=self._registrar_evento)
        self.servidor = ServidorCelular(self.api, self)
        self.servidor.contacto.connect(self._contacto)
        if not self.servidor.iniciar():
            self.servidor = None
            avisos.error(
                self,
                "No se pudo encender",
                "Los puertos del lector están ocupados por otro programa.",
            )
            return False

        self.btn_encender.setText("■ Apagar")
        self.btn_encender.setProperty("variante", "envio")
        self.btn_encender.style().polish(self.btn_encender)
        self.btn_copiar.setEnabled(True)
        self.lbl_contacto.setText("Esperando al celular…")
        self._refrescar_qr()
        return True

    def apagar(self):
        if self.servidor:
            self.servidor.detener()
        self.servidor = None
        self.api = None
        self.banner.fijar("Apagado. El celular ya no puede registrar equipos.", "info")
        self._mostrar_apagado()

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
        global _panel
        self.apagar()
        _panel = None
        super().done(resultado)
        # Tiene padre (la ventana principal): sin esto quedaría oculto en
        # memoria cada vez que se cierra.
        self.deleteLater()


def abrir(ventana):
    global _panel
    if _panel is None:
        _panel = PanelCelular(ventana)
    _panel.show()
    _panel.raise_()
    _panel.activateWindow()
    return False
