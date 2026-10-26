"""Transporte HTTP y panel del lector celular, con pedidos reales a un puerto local."""

import http.client
import json
import threading
import time

import pytest

pytest.importorskip("PySide6.QtNetwork")

from PySide6.QtWidgets import QApplication  # noqa: E402

from inventario.nucleo.api_celular import ApiCelular  # noqa: E402
from inventario.ui.servidor_celular import (  # noqa: E402
    ErrorHttp,
    ServidorCelular,
    armar_respuesta,
    parsear_pedido,
)
from inventario.ui.tema import aplicar_tema  # noqa: E402

LOTE = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}


@pytest.fixture(scope="module")
def app():
    instancia = QApplication.instance() or QApplication([])
    aplicar_tema(instancia, oscuro=False)
    return instancia


# ─── HTTP sin red ────────────────────────────────────────
def test_parsear_pedido_completo_e_incompleto():
    pedido = (
        b"POST /api/v1/lote HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer t\r\n"
        b"Content-Length: 7\r\n\r\n{\"a\":1}"
    )
    assert parsear_pedido(pedido[:20]) is None
    assert parsear_pedido(pedido[:-2]) is None  # falta cuerpo
    metodo, ruta, cabeceras, cuerpo = parsear_pedido(bytearray(pedido))
    assert (metodo, ruta, cuerpo) == ("POST", "/api/v1/lote", b'{"a":1}')
    assert cabeceras["authorization"] == "Bearer t"


@pytest.mark.parametrize(
    "pedido, codigo",
    [
        (b"BASURA\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nsin-dos-puntos\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nContent-Length: x\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nContent-Length: 999999\r\n\r\n", 413),
        (b"GET / HTTP/1.1\r\nX: " + b"a" * 9000, 413),
    ],
)
def test_parsear_pedido_rechaza(pedido, codigo):
    with pytest.raises(ErrorHttp) as e:
        parsear_pedido(pedido)
    assert e.value.codigo == codigo


def test_armar_respuesta():
    crudo = armar_respuesta(409, {"mensaje": "OT cerrada ñ"})
    cabecera, cuerpo = crudo.split(b"\r\n\r\n", 1)
    assert cabecera.startswith(b"HTTP/1.1 409 Conflict")
    assert f"Content-Length: {len(cuerpo)}".encode() in cabecera
    assert json.loads(cuerpo) == {"mensaje": "OT cerrada ñ"}


# ─── Pedidos reales ──────────────────────────────────────
def _pedir(app, puerto, metodo, ruta, datos=None, token="secreto", cuerpo=None):
    """Hace el pedido desde otro hilo (como el celular) mientras Qt atiende en este."""
    resultado = {}

    def cliente():
        try:
            conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
            cabeceras = {"Content-Type": "application/json"}
            if token:
                cabeceras["Authorization"] = f"Bearer {token}"
            enviar = cuerpo if cuerpo is not None else (
                json.dumps(datos).encode() if datos is not None else None
            )
            conexion.request(metodo, ruta, body=enviar, headers=cabeceras)
            r = conexion.getresponse()
            resultado["respuesta"] = (r.status, json.loads(r.read()))
            conexion.close()
        except Exception as e:  # se re-lanza en el hilo del test
            resultado["error"] = e

    hilo = threading.Thread(target=cliente)
    hilo.start()
    limite = time.monotonic() + 10
    while hilo.is_alive() and time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.005)
    hilo.join(1)
    if "error" in resultado:
        raise resultado["error"]
    return resultado["respuesta"]


@pytest.fixture
def servidor(app):
    srv = ServidorCelular(ApiCelular(token="secreto", reglas=[]))
    assert srv.iniciar(0)
    yield srv
    srv.detener()


def test_puerto_guardado_no_se_sale_del_rango_del_lector(app):
    # Un puerto guardado fuera del rango (lo dejaba la búsqueda vieja, que
    # partía del último) no se reusa: el firewall solo abre PUERTOS_LECTOR.
    from inventario.ui.servidor_celular import PUERTOS_LECTOR

    afuera = ServidorCelular(ApiCelular(token="secreto", reglas=[]))
    adentro = ServidorCelular(ApiCelular(token="secreto", reglas=[]))
    try:
        assert afuera.iniciar(PUERTOS_LECTOR.stop + 7) in PUERTOS_LECTOR
        # Uno guardado dentro del rango se respeta si está libre.
        libre = next(p for p in PUERTOS_LECTOR if p != afuera.puerto)
        assert adentro.iniciar(libre) == libre
    finally:
        afuera.detener()
        adentro.detener()


def test_servidor_responde_y_exige_token(app, servidor, lote_con_equipos):
    puerto = servidor.puerto
    contactos = []
    servidor.contacto.connect(contactos.append)

    assert _pedir(app, puerto, "GET", "/api/v1/estado", token=None)[0] == 401
    assert contactos == []  # un pedido sin token no cuenta como celular conectado

    assert _pedir(app, puerto, "GET", "/api/v1/estado") == (
        200,
        {"app": "inventario-arrienda", "v": 1},
    )
    assert contactos == ["127.0.0.1"]

    codigo, r = _pedir(
        app,
        puerto,
        "POST",
        "/api/v1/escaneo",
        {"lote": LOTE, "lecturas": [{"texto": "S/N: MON12345"}], "esperado": "Monitor"},
    )
    assert (codigo, r["estado"], r["serial"]) == (200, "registrado", "MON12345")


def test_servidor_rechaza_cuerpo_gigante(app, servidor):
    codigo, r = _pedir(app, servidor.puerto, "POST", "/api/v1/lote", cuerpo=b"x" * 70_000)
    assert codigo == 413


def test_servidor_apagado_no_escucha(app):
    srv = ServidorCelular(ApiCelular(reglas=[]))
    assert not srv.activo and srv.puerto is None
    puerto = srv.iniciar(0)
    srv.detener()
    assert not srv.activo
    with pytest.raises(OSError):
        _pedir(app, puerto, "GET", "/api/v1/estado")


# ─── Panel ───────────────────────────────────────────────
def _descartar(app, panel):
    """El panel ya no se borra al cerrarlo (vive con la ventana): en el test se borra a mano."""
    panel.apagar()
    panel.deleteLater()
    app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_panel_enciende_empareja_y_apaga(app, lote_con_equipos, monkeypatch):
    from inventario.ui.modulos import celular

    monkeypatch.setattr(celular, "interfaces_locales", lambda: [("192.168.1.20", "Wi-Fi")])
    panel = celular.PanelCelular(None)
    assert panel.servidor is None  # viene apagado: ningún puerto abierto

    assert panel.encender()
    puerto = panel.servidor.puerto
    datos_qr = json.loads(panel.api.texto_qr("192.168.1.20", puerto))
    assert datos_qr["url"] == f"http://192.168.1.20:{puerto}"
    if celular.SEGNO_AVAILABLE:
        assert panel.qr._matriz

    codigo, _ = _pedir(
        app,
        puerto,
        "POST",
        "/api/v1/escaneo",
        {"lote": LOTE, "lecturas": [{"texto": "IMP12345"}], "esperado": "Impresora"},
        token=panel.api.token,
    )
    assert codigo == 200
    assert panel.tabla.rowCount() == 1
    assert panel.tabla.item(0, 2).text() == "IMP12345"
    assert "Impresora registrado" in panel.tabla.item(0, 3).text()

    # Apagar y encender conserva token y puerto: el celular sigue emparejado.
    token = panel.api.token
    panel.apagar()
    assert panel.servidor is None
    panel.encender()
    assert (panel.api.token, panel.servidor.puerto) == (token, puerto)

    # Cerrar la ventana no desconecta: el servidor sigue atendiendo.
    panel.done(0)
    codigo, _ = _pedir(app, puerto, "GET", "/api/v1/estado", token=token)
    assert codigo == 200

    # "Código nuevo" desempareja al celular de antes.
    monkeypatch.setattr(celular.avisos, "confirmar", lambda *a, **k: True)
    panel._codigo_nuevo()
    assert _pedir(app, puerto, "GET", "/api/v1/estado", token=token)[0] == 401
    assert _pedir(app, puerto, "GET", "/api/v1/estado", token=panel.api.token)[0] == 200
    _descartar(app, panel)


def test_lector_se_enciende_solo_al_abrir_si_quedo_marcado(app, carpeta, monkeypatch):
    from inventario.nucleo import api_celular
    from inventario.ui.modulos import celular

    monkeypatch.setattr(celular, "interfaces_locales", lambda: [("192.168.1.20", "Wi-Fi")])
    monkeypatch.setattr(celular, "_panel", None)

    celular.encender_al_iniciar(None)  # sin preferencias: no abre ningún puerto
    assert not celular.esta_encendido()

    api_celular.guardar_preferencias(
        {"encender_al_iniciar": True, "token": "t" * 32, "puerto": None}
    )
    celular.encender_al_iniciar(None)
    assert celular.esta_encendido()
    assert celular._panel.api.token == "t" * 32
    assert api_celular.cargar_preferencias()["puerto"] == celular._panel.servidor.puerto
    _descartar(app, celular._panel)


def test_preferencias_rotas_quedan_apagadas(carpeta):
    from inventario.nucleo import api_celular

    (carpeta / api_celular.ARCHIVO_PREFERENCIAS).write_text("{roto", encoding="utf-8")
    assert api_celular.cargar_preferencias() == {
        "encender_al_iniciar": False, "token": None, "puerto": None,
    }
    (carpeta / api_celular.ARCHIVO_PREFERENCIAS).write_text(
        '{"encender_al_iniciar": "si", "token": "corto", "puerto": 22}', encoding="utf-8"
    )
    assert api_celular.cargar_preferencias() == {
        "encender_al_iniciar": False, "token": None, "puerto": None,
    }
