"""Panel de clonación: el traer automático escribe la OT local y pinta la tabla."""

import json
import os

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from inventario.nucleo import lotes, sincronizacion  # noqa: E402
from inventario.ui.tema import aplicar_tema  # noqa: E402

from test_sincronizacion import json_remoto, nombre  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instancia = QApplication.instance() or QApplication([])
    aplicar_tema(instancia, oscuro=False)
    return instancia


def respuesta_servidor(seriales=("C1", "C2"), esperados=("C1", "C2", "C3")):
    """Lo que devuelve sincronizacion.consultar() con la OT ACME 553 publicada."""
    publicado = lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-9")
    archivos = {nombre(s): json_remoto(s) for s in seriales}
    return {
        "lote": publicado,
        "huellas": {n: sincronizacion.huella(t) for n, t in archivos.items()},
        "contenidos": archivos,
        "esperados": list(esperados),
        "hora": "10:00:00",
    }


@pytest.fixture
def servidor(monkeypatch):
    """Servidor configurado; cada vuelta del sincronizador contesta 'respuesta' (o falla)."""
    from inventario.nucleo import config
    from inventario.ui import sincronizador

    monkeypatch.setattr(config, "SERVIDOR_CONFIGURADO", True)
    monkeypatch.setattr(config, "SCP_AVAILABLE", True)
    estado = {"respuesta": respuesta_servidor(), "falla": None, "vueltas": 0}

    def en_segundo_plano(_fn, _tarea, al_terminar, al_fallar):
        estado["vueltas"] += 1
        if estado["falla"]:
            al_fallar(estado["falla"])
        else:
            al_terminar(estado["respuesta"])

    monkeypatch.setattr(sincronizador, "en_segundo_plano", en_segundo_plano)
    return estado


def test_traer_automatico_sin_el_panel(app, carpeta, servidor):
    from inventario.ui.ventana_principal import VentanaPrincipal

    ventana = VentanaPrincipal()
    ventana.sincronizador.arrancar()
    local = sincronizacion.lote_local(servidor["respuesta"]["lote"])
    assert {e["SERIAL"] for e in lotes.leer_equipos_lote(local)} == {"C1", "C2"}
    assert lotes.es_publicada(local)
    texto = ventana.inicio.lbl_clonacion.text()
    assert "ACME · OT-553" in texto and "2 recibido(s)" in texto and "faltan 1" in texto
    # Con OT publicada vuelve rápido; sin conexión, más espaciado y avisa.
    assert ventana.sincronizador._timer.interval() == 15_000
    servidor["falla"] = RuntimeError("No se pudo conectar a 192.168.1.10:22\nmás detalle")
    ventana.sincronizador.traer_ahora()
    assert ventana.sincronizador._timer.interval() == 60_000
    assert "sin conexión" in ventana.inicio.lbl_clonacion.text()
    ventana.close()
    antes = servidor["vueltas"]
    ventana.sincronizador.traer_ahora()
    assert servidor["vueltas"] == antes  # cerrada la ventana, no vuelve a consultar


def test_sin_servidor_configurado_no_consulta(app, carpeta, servidor):
    from inventario.nucleo import config
    from inventario.ui.ventana_principal import VentanaPrincipal

    config.SERVIDOR_CONFIGURADO = False
    ventana = VentanaPrincipal()
    ventana.sincronizador.arrancar()
    assert servidor["vueltas"] == 0
    assert not ventana.inicio.lbl_clonacion.isVisibleTo(ventana)


def test_el_panel_muestra_lo_que_trae_el_sincronizador(app, carpeta, servidor):
    from inventario.ui.modulos import panel_clonacion

    panel = panel_clonacion.PanelClonacion(None)
    panel.sinc.traer_ahora()
    assert "2 equipo(s) nuevo(s)" in panel.lbl_auto.text()
    assert panel.tabla.rowCount() == 3  # dos llegaron, uno falta
    assert "faltan 1" in panel.lbl_resumen.text()

    # Pausado no consulta; cerrado el panel, el sincronizador sigue sin pintarlo.
    panel.chk_auto.setChecked(False)
    antes = servidor["vueltas"]
    panel.sinc.traer_ahora()
    assert servidor["vueltas"] == antes and "Pausado" in panel.lbl_auto.text()
    panel.chk_auto.setChecked(True)
    panel.done(0)
    panel.sinc.traer_ahora()  # no revienta: el panel ya no escucha
    panel.sinc._al_fallar(RuntimeError("no conecta"))


def test_traer_y_reconstruir_no_pisa_ni_devuelve_lo_quitado(app, carpeta, monkeypatch):
    from inventario.nucleo import gestion_lote
    from inventario.ui import avisos
    from inventario.ui.modulos import panel_clonacion

    publicado = lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-9")
    archivos = {nombre("C1"): json_remoto("C1"), nombre("C2"): json_remoto("C2")}
    huellas = {n: sincronizacion.huella(t) for n, t in archivos.items()}

    def consulta(nombres):
        return {
            "res": {
                "lote": publicado,
                "huellas": huellas,
                "contenidos": {n: archivos[n] for n in nombres},
                "esperados": [],
                "hora": "10:00:00",
            }
        }

    mostrados = []
    monkeypatch.setattr(avisos, "info", lambda *a, **k: mostrados.append(a[2]))
    from inventario.ui import sincronizador

    monkeypatch.setattr(sincronizador, "en_segundo_plano", lambda *a, **k: None)
    panel = panel_clonacion.PanelClonacion(None)
    panel.lote = publicado

    # Primera vez: entran los dos.
    monkeypatch.setattr(panel, "_remoto", lambda *a: consulta(archivos))
    panel._traer_y_reconstruir()
    local = sincronizacion.lote_local(publicado)
    assert lotes.contar_equipos(local["ruta"]) == 2 and "2 equipo(s) nuevo(s)" in mostrados[-1]

    # Acá se le carga el cargador a C1 y se quita C2 del lote.
    ruta_c1 = lotes.ruta_json_equipo(local, "C1")
    with open(ruta_c1, encoding="utf-8") as f:
        c1 = json.load(f)
    c1["SN_Transf"] = "TR-ACA"
    with open(ruta_c1, "w", encoding="utf-8") as f:
        json.dump(c1, f)
    gestion_lote.quitar_equipo(local, "C2")
    html = lotes.ruta_html_lote(local)
    os.remove(html)  # un reporte roto también se rearma

    # El servidor manda TODO otra vez (como antes hacía el botón): nada se pisa.
    monkeypatch.setattr(panel, "_remoto", lambda *a: consulta(archivos))
    panel._traer_y_reconstruir()
    equipos = lotes.leer_equipos_lote(local)
    assert [(e["SERIAL"], e["SN_Transf"]) for e in equipos] == [("C1", "TR-ACA")]
    assert "0 equipo(s) nuevo(s)" in mostrados[-1]
    assert os.path.exists(html)
    panel.done(0)
