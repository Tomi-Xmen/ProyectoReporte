"""
Transporte HTTP del lector celular, sobre QtNetwork (viene en
PySide6-Essentials: no suma dependencias ni peso al .exe).

Corre en el hilo de la interfaz, dentro del loop de Qt: cada pedido se
atiende completo antes que el siguiente, así el celular y la ventana nunca
escriben el mismo JSON al mismo tiempo. Toda la lógica está en
nucleo/api_celular.py; acá solo se mueven bytes.

HTTP mínimo y estricto: un pedido por conexión (Connection: close), cuerpo
JSON con Content-Length, límites de tamaño y de tiempo, y solo conexiones
desde la red local.
"""

import json

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QTcpServer

from ..nucleo.api_celular import es_red_local, ip_principal

PUERTO_DEFAULT = 8765
# Si el puerto está ocupado se prueban los siguientes, siempre dentro de
# PUERTO_DEFAULT..+9: el firewall de Windows autoriza al programa, pero uno
# por puerto (ufw en Linux) abre esa ventana y nada fuera de ella.
_PUERTOS_A_PROBAR = 10
PUERTOS_LECTOR = range(PUERTO_DEFAULT, PUERTO_DEFAULT + _PUERTOS_A_PROBAR)
_MAX_CABECERAS = 8 * 1024
_MAX_CUERPO = 64 * 1024
_TIMEOUT_MS = 10_000

_RAZONES = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    500: "Internal Server Error",
}

# Adaptadores que tienen IP privada pero no llegan al Wi-Fi del celular.
_VIRTUALES = ("vethernet", "virtualbox", "vmware", "docker", "wsl", "hyper-v", "loopback")


class ErrorHttp(Exception):
    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def parsear_pedido(buf):
    """
    (método, ruta, cabeceras, cuerpo) si el pedido está completo en 'buf',
    None si falta que lleguen bytes. Lanza ErrorHttp si está mal formado o
    se pasa de los límites. Las cabeceras quedan con la clave en minúsculas.
    """
    fin = buf.find(b"\r\n\r\n")
    if fin < 0:
        if len(buf) > _MAX_CABECERAS:
            raise ErrorHttp(413, "Cabeceras demasiado grandes.")
        return None
    if fin > _MAX_CABECERAS:
        raise ErrorHttp(413, "Cabeceras demasiado grandes.")

    lineas = bytes(buf[:fin]).decode("latin-1").split("\r\n")
    partes = lineas[0].split(" ")
    if len(partes) != 3 or not partes[2].startswith("HTTP/"):
        raise ErrorHttp(400, "Línea de pedido inválida.")
    metodo, ruta, _version = partes

    cabeceras = {}
    for linea in lineas[1:]:
        clave, sep, valor = linea.partition(":")
        if not sep:
            raise ErrorHttp(400, "Cabecera inválida.")
        cabeceras[clave.strip().lower()] = valor.strip()
    if "transfer-encoding" in cabeceras:
        raise ErrorHttp(400, "Se necesita Content-Length.")

    try:
        largo = int(cabeceras.get("content-length", "0"))
    except ValueError:
        raise ErrorHttp(400, "Content-Length inválido.")
    if largo < 0:
        raise ErrorHttp(400, "Content-Length inválido.")
    if largo > _MAX_CUERPO:
        raise ErrorHttp(413, "Cuerpo demasiado grande.")

    cuerpo = bytes(buf[fin + 4 : fin + 4 + largo])
    if len(cuerpo) < largo:
        return None
    return metodo, ruta, cabeceras, cuerpo


def armar_respuesta(codigo, datos):
    cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
    cabecera = (
        f"HTTP/1.1 {codigo} {_RAZONES.get(codigo, 'Error')}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(cuerpo)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    )
    return cabecera.encode("ascii") + cuerpo


def interfaces_locales():
    """
    [(ip, nombre del adaptador)] donde el celular puede encontrar a esta PC:
    primero la IP con salida por defecto, al final los adaptadores virtuales
    (Docker, WSL, VirtualBox), que tienen IP privada pero no ven el Wi-Fi.
    """
    encontradas = []
    for interfaz in QNetworkInterface.allInterfaces():
        banderas = interfaz.flags()
        if not (
            banderas & QNetworkInterface.InterfaceFlag.IsUp
            and banderas & QNetworkInterface.InterfaceFlag.IsRunning
        ) or banderas & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for entrada in interfaz.addressEntries():
            ip = entrada.ip()
            if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            texto = ip.toString()
            if es_red_local(texto) and not texto.startswith("127."):
                encontradas.append((texto, interfaz.humanReadableName()))

    principal = ip_principal()

    def orden(par):
        ip, nombre = par
        virtual = any(v in nombre.lower() for v in _VIRTUALES)
        return (ip != principal, virtual, nombre)

    return sorted(encontradas, key=orden)


class ServidorCelular(QObject):
    """Escucha pedidos del celular y los pasa a la ApiCelular."""

    contacto = Signal(str)  # IP del celular en cada pedido aceptado

    def __init__(self, api, padre=None):
        super().__init__(padre)
        self.api = api
        self._servidor = QTcpServer(self)
        self._servidor.newConnection.connect(self._nueva_conexion)
        self._sockets = set()  # todas las conexiones vivas
        self._buffers = {}  # las que todavía no recibieron el pedido completo

    @property
    def activo(self):
        return self._servidor.isListening()

    @property
    def puerto(self):
        return self._servidor.serverPort() if self.activo else None

    def iniciar(self, puerto=PUERTO_DEFAULT):
        """
        Escucha en todas las interfaces IPv4. Devuelve el puerto, o None si no pudo.

        'puerto' es el preferido (el de la última vez, así el celular emparejado
        vuelve solo); si está ocupado o fuera de PUERTOS_LECTOR se busca desde
        PUERTO_DEFAULT. Antes se buscaba desde el preferido y, guardado de nuevo
        cada vez, el puerto se iba corriendo hasta salir del rango del firewall.
        """
        if puerto == 0:
            candidatos = [0]
        else:
            preferido = [puerto] if puerto in PUERTOS_LECTOR else []
            candidatos = preferido + [p for p in PUERTOS_LECTOR if p != puerto]
        cualquiera = QHostAddress(QHostAddress.SpecialAddress.AnyIPv4)
        for p in candidatos:
            if self._servidor.listen(cualquiera, p):
                return self._servidor.serverPort()
        return None

    def detener(self):
        """
        Cierra el puerto y las conexiones y descarta el servidor: para volver
        a escuchar se crea uno nuevo (y con él un token nuevo). Se destruye
        con deleteLater porque destruirlo en el acto —cuando Python suelta la
        referencia— con conexiones a medio cerrar hace abortar a Qt.
        """
        self._servidor.close()
        for sock in list(self._sockets):
            sock.abort()
        self._buffers.clear()
        self.deleteLater()

    # ── Conexiones ───────────────────────────────────────
    def _nueva_conexion(self):
        while self._servidor.hasPendingConnections():
            sock = self._servidor.nextPendingConnection()
            if not es_red_local(sock.peerAddress().toString()):
                sock.abort()
                sock.deleteLater()
                continue
            self._sockets.add(sock)
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._leer(s))
            sock.disconnected.connect(lambda s=sock: self._cerrado(s))
            # Un celular que abre la conexión y no manda nada no la retiene.
            QTimer.singleShot(_TIMEOUT_MS, sock, lambda s=sock: self._vencido(s))

    def _leer(self, sock):
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf += sock.readAll().data()
        try:
            pedido = parsear_pedido(buf)
        except ErrorHttp as e:
            self._responder(sock, e.codigo, {"error": "http", "mensaje": e.mensaje})
            return
        if pedido is None:
            return

        metodo, ruta, cabeceras, cuerpo = pedido
        codigo, datos = self.api.atender(metodo, ruta, cabeceras, cuerpo)
        if codigo != 401:
            self.contacto.emit(sock.peerAddress().toString())
        self._responder(sock, codigo, datos)

    def _responder(self, sock, codigo, datos):
        self._buffers.pop(sock, None)
        sock.write(armar_respuesta(codigo, datos))
        sock.disconnectFromHost()  # espera a que salga lo escrito

    def _cerrado(self, sock):
        self._sockets.discard(sock)
        self._buffers.pop(sock, None)
        sock.deleteLater()

    def _vencido(self, sock):
        if sock in self._buffers:
            self._buffers.pop(sock, None)
            sock.abort()
