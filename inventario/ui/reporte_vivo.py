"""
Servidor del reporte en vivo (ver nucleo/reporte_vivo.py).

Escucha SOLO en 127.0.0.1: el reporte se abre en el navegador de esta PC y
nadie más de la red lo ve. Arranca la primera vez que se pide un reporte en
vivo y queda prendido hasta cerrar el programa; cada arranque usa un token
nuevo en la URL, así una página vieja no lee nada.

Igual que el servidor del celular, corre en el hilo de la interfaz: lee los
archivos del lote entre una escritura y otra, nunca a mitad de una.
"""

import json
import secrets

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import QApplication

from ..nucleo import reporte_vivo
from .servidor_celular import ErrorHttp, parsear_pedido

_TIMEOUT_MS = 10_000
_RAZONES = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}

_servidor = None


def _respuesta(codigo, cuerpo, tipo):
    if isinstance(cuerpo, str):
        cuerpo = cuerpo.encode("utf-8")
    cabecera = (
        f"HTTP/1.1 {codigo} {_RAZONES.get(codigo, 'Error')}\r\n"
        f"Content-Type: {tipo}; charset=utf-8\r\n"
        f"Content-Length: {len(cuerpo)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    )
    return cabecera.encode("ascii") + cuerpo


def atender(token, metodo, ruta):
    """(código, cuerpo, tipo) para un pedido. Sin red: se prueba directo."""
    if metodo != "GET":
        return 405, "Solo GET.", "text/plain"
    partes = [p for p in ruta.split("?", 1)[0].split("/") if p]
    if not partes or not secrets.compare_digest(partes[0], token):
        return 404, "No existe.", "text/plain"
    base = f"/{token}"
    if len(partes) == 1:
        return 200, reporte_vivo.pagina_indice(base), "text/html"
    if len(partes) == 5 and partes[1] in ("lote", "huella"):
        lote = reporte_vivo.lote_desde_partes(*partes[2:])
        if lote is None:
            return 404, "Ese lote no existe.", "text/plain"
        if partes[1] == "huella":
            return 200, json.dumps(reporte_vivo.huella_lote(lote)), "application/json"
        url_huella = "/".join([base, "huella", *partes[2:]])
        return 200, reporte_vivo.pagina_lote(lote, url_huella), "text/html"
    return 404, "No existe.", "text/plain"


class ServidorReporte(QObject):
    def __init__(self, padre=None):
        super().__init__(padre)
        self.token = secrets.token_urlsafe(16)
        self._servidor = QTcpServer(self)
        self._servidor.newConnection.connect(self._nueva_conexion)
        self._sockets = set()
        self._buffers = {}

    def iniciar(self):
        """Puerto elegido por el sistema en 127.0.0.1. False si no se pudo."""
        return self._servidor.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0)

    def detener(self):
        """
        Cierra todo y se descarta con deleteLater: destruirlo en el acto con
        conexiones a medio cerrar hace abortar a Qt (ver servidor_celular).
        """
        self._servidor.close()
        for sock in list(self._sockets):
            sock.abort()
        self._buffers.clear()
        self.deleteLater()

    @property
    def base(self):
        return f"http://127.0.0.1:{self._servidor.serverPort()}/{self.token}"

    def url_lote(self, lote):
        return "/".join([self.base, "lote", *reporte_vivo.partes_de_lote(lote)])

    def _nueva_conexion(self):
        while self._servidor.hasPendingConnections():
            sock = self._servidor.nextPendingConnection()
            if not sock.peerAddress().isLoopback():
                sock.abort()
                sock.deleteLater()
                continue
            self._sockets.add(sock)
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._leer(s))
            sock.disconnected.connect(lambda s=sock: self._cerrado(s))
            QTimer.singleShot(_TIMEOUT_MS, sock, lambda s=sock: self._vencido(s))

    def _leer(self, sock):
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf += sock.readAll().data()
        try:
            pedido = parsear_pedido(buf)
        except ErrorHttp as e:
            self._responder(sock, e.codigo, e.mensaje, "text/plain")
            return
        if pedido is None:
            return
        metodo, ruta, _cabeceras, _cuerpo = pedido
        try:
            codigo, cuerpo, tipo = atender(self.token, metodo, ruta)
        except Exception as e:  # un error de lectura no tumba el programa
            codigo, cuerpo, tipo = 500, str(e) or type(e).__name__, "text/plain"
        self._responder(sock, codigo, cuerpo, tipo)

    def _responder(self, sock, codigo, cuerpo, tipo):
        self._buffers.pop(sock, None)
        sock.write(_respuesta(codigo, cuerpo, tipo))
        sock.disconnectFromHost()

    def _cerrado(self, sock):
        self._sockets.discard(sock)
        self._buffers.pop(sock, None)
        sock.deleteLater()

    def _vencido(self, sock):
        if sock in self._buffers:
            self._buffers.pop(sock, None)
            sock.abort()


def servidor():
    """El servidor del reporte en vivo, arrancándolo si hace falta. None si no pudo."""
    global _servidor
    if _servidor is None:
        nuevo = ServidorReporte(QApplication.instance())
        if not nuevo.iniciar():
            nuevo.deleteLater()
            return None
        _servidor = nuevo
    return _servidor


def abrir_lote(lote):
    """Abre el reporte en vivo del lote en el navegador. False si no se pudo."""
    s = servidor()
    return bool(s) and QDesktopServices.openUrl(QUrl(s.url_lote(lote)))


def abrir_indice():
    """Abre la lista de lotes abiertos, cada uno con su reporte en vivo."""
    s = servidor()
    return bool(s) and QDesktopServices.openUrl(QUrl(s.base + "/"))
