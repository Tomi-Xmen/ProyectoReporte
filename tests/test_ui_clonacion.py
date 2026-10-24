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


def test_traer_automatico(app, carpeta, monkeypatch):
    from inventario.ui.modulos import panel_clonacion

    publicado = lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-9")
    archivos = {nombre("C1"): json_remoto("C1"), nombre("C2"): json_remoto("C2")}
    respuesta = {
        "lote": publicado,
        "huellas": {n: sincronizacion.huella(t) for n, t in archivos.items()},
        "contenidos": archivos,
        "esperados": ["C1", "C2", "C3"],
        "hora": "10:00:00",
    }
    vueltas = []

    def en_segundo_plano(_fn, _tarea, al_terminar, al_fallar):
        vueltas.append(1)
        al_terminar(respuesta)

    monkeypatch.setattr(panel_clonacion, "en_segundo_plano", en_segundo_plano)
    panel = panel_clonacion.PanelClonacion(None)
    panel._traer_auto()

    local = sincronizacion.lote_local(publicado)
    assert {e["SERIAL"] for e in lotes.leer_equipos_lote(local)} == {"C1", "C2"}
    assert "2 equipo(s) nuevo(s)" in panel.lbl_auto.text()
    assert panel.tabla.rowCount() == 3  # dos llegaron, uno falta
    assert "faltan 1" in panel.lbl_resumen.text()

    # Pausado no consulta; al cerrar el panel tampoco.
    panel.chk_auto.setChecked(False)
    antes = len(vueltas)
    panel._traer_auto()
    assert len(vueltas) == antes
    panel.done(0)
    assert not panel._timer.isActive()

    panel._al_fallar_traer(RuntimeError("no conecta"))  # tras cerrar, no revienta


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
    monkeypatch.setattr(panel_clonacion, "en_segundo_plano", lambda *a, **k: None)
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
