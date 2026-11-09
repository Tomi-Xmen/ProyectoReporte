"""Buscador de series: historial de un equipo en todas las OT y guías, y su HTML."""

import json
import os
import re

import pytest

from inventario.nucleo import gestion_lote, historial as H, licencias_office as L, lotes

from conftest import datos_equipo


def guardar(lote, serial, cuando):
    """Registra el equipo en el lote con una hora de escaneo fija."""
    lotes.guardar_equipo_general(lote, datos_equipo(serial), "", False, "", "2016", [])
    ruta = lotes.ruta_json_equipo(lote, serial)
    with open(ruta, encoding="utf-8") as f:
        jdata = json.load(f)
    jdata["ESCANEADO"] = cuando
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f)


@pytest.fixture
def ciclo(carpeta):
    """
    5CD0DEMO01: entregado a ACME (OT cerrada), retirado (guía cerrada) y
    vuelto a entregar a BETA (OT abierta). 5CD0DEMO02 se quitó de la OT de BETA.
    """
    acme = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-1"))
    guardar(acme, "5CD0DEMO01", "2026-07-01T10:00:00")
    guardar(acme, "5CD0OTRO99", "2026-07-01T10:05:00")
    lotes.cerrar_lote(acme)

    retiro = lotes.abrir_lote(lotes.hacer_lote("Retiro", "ACME", "77"))
    guardar(retiro, "5CD0DEMO01", "2026-08-15T09:00:00")
    lotes.cerrar_lote(retiro)

    beta = lotes.abrir_lote(lotes.hacer_lote("Entrega", "BETA", "900"))
    guardar(beta, "5CD0DEMO01", "2026-09-02T12:00:00")
    guardar(beta, "5CD0DEMO02", "2026-09-02T12:01:00")
    gestion_lote.quitar_equipo(beta, "5CD0DEMO02")
    return {"acme": acme, "retiro": retiro, "beta": beta}


def test_clave_serial_acepta_lo_que_lee_la_pistola():
    assert H.clave_serial(" s/n: 5cd0-demo01 ") == "5CD0DEMO01"
    assert H.clave_serial("SN 5CD0DEMO01") == "5CD0DEMO01"


def test_historial_en_orden_con_estados(ciclo):
    pasos = H.historial("5cd0demo01")
    assert [(p["mov"], p["cliente"], p["documento"], p["estado"]) for p in pasos] == [
        ("Entrega", "BETA", "OT-900", "abierta"),
        ("Retiro", "ACME", "GUIA-77", "cerrada"),
        ("Entrega", "ACME", "OT-553", "cerrada"),
    ]
    assert pasos[1]["lote"]["ruta"] == ciclo["retiro"]["ruta"]
    assert pasos[0]["jdata"]["SERIAL"] == "5CD0DEMO01"


def test_lo_quitado_tambien_es_historia(ciclo):
    (paso,) = H.historial("5CD0DEMO02")
    assert (paso["estado"], paso["documento"], paso["cliente"]) == ("quitado", "OT-900", "BETA")
    assert paso["fecha"] == "2026-09-02T12:01:00"


def test_registro_del_modelo_viejo_suelto_en_el_cliente(ciclo):
    viejo = os.path.join(lotes.ruta_reportes(), "ENTREGA", "ACME", "Reporte_Entregas_ACME_SN_5CD0DEMO01.json")
    with open(viejo, "w", encoding="utf-8") as f:
        json.dump({"SERIAL": "5CD0DEMO01", "DATA": {"fecha": "20/06/2026 09:30"}}, f)
    pasos = H.historial("5CD0DEMO01")
    assert pasos[-1]["estado"] == "sin OT" and pasos[-1]["fecha"] == "2026-06-20T09:30:00"


def test_buscar_exacta_y_parcial(ciclo):
    exacta = H.buscar("5CD0DEMO01")
    assert exacta[0]["serial"] == "5CD0DEMO01" and exacta[0]["registros"] == 3
    assert exacta[0]["cliente"] == "BETA" and exacta[0]["ultima"].startswith("2026-09-02")

    # Parcial: desde 4 caracteres, en cualquier parte de la serie; la más reciente primero.
    assert [s["serial"] for s in H.buscar("DEMO")] == ["5CD0DEMO02", "5CD0DEMO01"]
    assert [s["serial"] for s in H.buscar("emo01")] == ["5CD0DEMO01"]
    # La exacta va primero aunque otra coincida y sea más nueva.
    assert H.buscar("5CD0DEMO01")[0]["serial"] == "5CD0DEMO01"
    # Con menos de 4 solo vale la exacta.
    assert H.buscar("O01") == []
    assert H.buscar("") == [] and H.buscar("NO-EXISTE") == []


def test_html_del_equipo(ciclo):
    pasos = H.historial("5CD0DEMO01")
    contenido = H.html_equipo("5CD0DEMO01", pasos)
    assert "<title>Historial 5CD0DEMO01</title>" in contenido
    assert "Historial del equipo 5CD0DEMO01" in contenido
    assert '<span id="total-count">3</span>' in contenido
    ids = re.findall(r'<details id="([^"]+)"', contenido)
    assert ids == ["dev-5CD0DEMO01-1", "dev-5CD0DEMO01-2", "dev-5CD0DEMO01-3"]
    assert "eliminarEquipo('dev-5CD0DEMO01-2')" in contenido
    # La línea de tiempo nombra cada paso.
    for texto in ("BETA", "ACME", "Retiro", "02/09/2026 12:00", "cerrada"):
        assert texto in contenido
    # Solo las filas marcadas.
    solo_una = H.html_equipo("5CD0DEMO01", pasos[1:2])
    assert '<span id="total-count">1</span>' in solo_una and "BETA" not in solo_una


def test_guardar_html_fuera_de_las_ot(ciclo):
    ruta = H.guardar_html("5CD0DEMO01", H.historial("5CD0DEMO01"))
    assert os.path.dirname(ruta) == os.path.join(lotes.ruta_reportes(), "_CONSULTAS")
    assert os.path.basename(ruta).startswith("Historial_5CD0DEMO01_")
    # No aparece como OT ni como registro de un equipo.
    assert all("_CONSULTAS" not in o["ruta"] for o in lotes.listar_lotes_abiertos())
    assert len(H.historial("5CD0DEMO01")) == 3


def test_office_del_equipo(ciclo):
    assert H.office_del_equipo("5CD0DEMO01") == []  # sin base de licencias

    licencias = []
    for caja, n in (("C-1", 1), ("C-2", 2)):
        lic = L._licencia_vacia(caja, f"AAAAA-BBBBB-CCCCC-DDDDD-0000{n}", "2016")
        licencias.append(lic)
    L.importar(licencias)
    L.asignar("C-1", "5CD0DEMO01")
    L.asignar("C-2", "5CD0DEMO01", reemplazar=True)  # libera la C-1
    cajas = H.office_del_equipo("5CD0DEMO01")
    assert [(c["caja"], c["estado"]) for c in cajas] == [("C-2", "actual"), ("C-1", "anterior")]
    # Un serial que empieza igual no se confunde.
    L.asignar("C-1", "5CD0DEMO011")
    assert [c["caja"] for c in H.office_del_equipo("5CD0DEMO01")] == ["C-2", "C-1"]
    assert [c["caja"] for c in H.office_del_equipo("5CD0DEMO011")] == ["C-1"]


# ─────────────────────────────────────────────────────────
#  Pantalla "Buscar serie"
# ─────────────────────────────────────────────────────────
@pytest.fixture
def app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_pantalla_busca_marca_y_genera_html(app, ciclo, monkeypatch):
    from PySide6.QtCore import Qt

    from inventario.ui.modulos import buscar_serie

    abiertos = []
    monkeypatch.setattr(buscar_serie.webbrowser, "open", abiertos.append)
    dlg = buscar_serie.DialogoBuscarSerie(None, "demo")

    # Parcial: dos series, la más reciente primero y ya elegida.
    assert dlg.tabla_series.isVisibleTo(dlg) and dlg.tabla_series.rowCount() == 2
    assert dlg.serial == "5CD0DEMO02"
    dlg.tabla_series.selectRow(1)
    assert dlg.serial == "5CD0DEMO01" and dlg.tabla.rowCount() == 3
    assert "último: Entrega a BETA (OT-900, abierta)" in dlg.lbl_resumen.text()
    assert dlg.tabla.item(1, 2).text() == "Retiro" and dlg.tabla.item(1, 6).text() == "cerrada"

    # Se desmarca el retiro: el HTML lleva las otras dos.
    dlg.tabla.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    dlg._generar_html()
    (url,) = abiertos
    ruta = url.replace("file://", "")
    with open(ruta, encoding="utf-8") as f:
        contenido = f.read()
    assert '<span id="total-count">2</span>' in contenido and "GUIA-77" not in contenido

    # Activar solo para la OT abierta.
    dlg.tabla.selectRow(0)
    assert dlg.btn_activar.isEnabled()
    dlg._activar()
    assert lotes.cargar_lote_activo()["ruta"] == ciclo["beta"]["ruta"] and dlg.activada
    dlg.tabla.selectRow(2)
    assert not dlg.btn_activar.isEnabled()

    carpetas = []
    monkeypatch.setattr(buscar_serie, "abrir_carpeta", carpetas.append)
    dlg._abrir_carpeta()
    assert carpetas == [ciclo["acme"]["ruta"]]


def test_pantalla_exacta_y_sin_resultados(app, ciclo):
    from inventario.ui.modulos import buscar_serie

    dlg = buscar_serie.DialogoBuscarSerie(None, "S/N: 5CD0DEMO01")
    assert not dlg.tabla_series.isVisibleTo(dlg) and dlg.tabla.rowCount() == 3

    dlg.entry.setText("ZZZZZZ")
    dlg.buscar()
    assert "No se encontró" in dlg.lbl_estado.text() and dlg.tabla.rowCount() == 0
    assert not dlg.btn_html.isEnabled()
