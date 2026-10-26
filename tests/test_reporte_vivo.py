"""Reporte en vivo: rutas, huella, script inyectado y el servidor local real."""

import http.client
import json
import threading
import time

import pytest

from inventario.nucleo import lotes, reporte_vivo

from conftest import datos_equipo


def test_lote_desde_partes_solo_acepta_nombres_canonicos(lote_con_equipos):
    lote = reporte_vivo.lote_desde_partes("ENTREGA", "ACME", "OT-553")
    assert lote and lote["ruta"] == lote_con_equipos["ruta"] and lote["numero_sec"] == "G-9"
    for partes in [
        ("ENTREGA", "ACME", "OT-999"),  # no existe
        ("ENTREGA", "acme", "OT-553"),  # no canónico
        ("ENTREGA", "..", "OT-553"),
        ("ENTREGA", "ACME", "GUIA-553"),  # prefijo de otro movimiento
        ("OTRO", "ACME", "OT-553"),
        ("ENTREGA", "ACME", "OT-"),
    ]:
        assert reporte_vivo.lote_desde_partes(*partes) is None, partes


def test_pagina_con_script_y_archivo_intacto(lote_con_equipos):
    lote = lote_con_equipos
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        original = f.read()
    pagina = reporte_vivo.pagina_lote(lote, "/tok/huella/ENTREGA/ACME/OT-553")
    assert "EN VIVO" in pagina and "/tok/huella/ENTREGA/ACME/OT-553" in pagina
    assert pagina.index("vivo-insignia") < pagina.lower().rindex("</body>")
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert f.read() == original  # el archivo del disco no se toca

    huella = reporte_vivo.huella_lote(lote)
    time.sleep(0.02)
    lotes.guardar_equipo_general(lote, datos_equipo("SN3"), "", False, "", "2016", [])
    assert reporte_vivo.huella_lote(lote)["huella"] != huella["huella"]
    lotes.cerrar_lote(lote)
    assert reporte_vivo.huella_lote(lote)["cerrado"] is True


def test_lote_sin_equipos_tiene_pagina_que_espera(carpeta):
    lote = lotes.abrir_lote(lotes.hacer_lote("Retiro", "BETA", "7"))
    pagina = reporte_vivo.pagina_lote(lote, "/t/huella/RETIROS/BETA/GUIA-7")
    assert "Todavía no hay equipos" in pagina and "EN VIVO" in pagina
    assert reporte_vivo.huella_lote(lote)["huella"] == ""


def test_indice_lista_los_lotes_abiertos(lote_con_equipos):
    pagina = reporte_vivo.pagina_indice("/tok")
    assert "/tok/lote/ENTREGA/ACME/OT-553" in pagina and "2 equipo(s)" in pagina


# ─── Servidor real en 127.0.0.1 ──────────────────────────
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6.QtNetwork")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _get(puerto, ruta, resultado):
    con = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
    con.request("GET", ruta)
    r = con.getresponse()
    resultado.append((r.status, r.getheader("Content-Type"), r.read().decode("utf-8")))
    con.close()


def pedir(app, servidor, ruta):
    """GET desde otro hilo mientras el loop de Qt atiende (como el navegador)."""
    resultado = []
    hilo = threading.Thread(target=_get, args=(servidor._servidor.serverPort(), ruta, resultado))
    hilo.start()
    limite = time.time() + 5
    while hilo.is_alive() and time.time() < limite:
        app.processEvents()
        time.sleep(0.01)
    hilo.join(1)
    return resultado[0]


def test_servidor_local(app, lote_con_equipos):
    from inventario.ui.reporte_vivo import ServidorReporte, atender

    s = ServidorReporte()
    assert s.iniciar()
    try:
        assert s.base.startswith("http://127.0.0.1:")
        ruta_lote = s.url_lote(lote_con_equipos).split(str(s._servidor.serverPort()), 1)[1]

        codigo, tipo, cuerpo = pedir(app, s, ruta_lote)
        assert codigo == 200 and tipo.startswith("text/html") and "EN VIVO" in cuerpo

        codigo, tipo, cuerpo = pedir(app, s, ruta_lote.replace("/lote/", "/huella/"))
        assert codigo == 200 and json.loads(cuerpo)["cerrado"] is False

        assert pedir(app, s, f"/{s.token}/")[0] == 200
        assert pedir(app, s, "/token-viejo/")[0] == 404
        assert pedir(app, s, f"/{s.token}/lote/ENTREGA/ACME/OT-999")[0] == 404
    finally:
        s.detener()
        app.processEvents()

    assert atender("t", "POST", "/t/")[0] == 405
