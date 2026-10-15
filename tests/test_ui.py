"""Pruebas de humo de la interfaz Qt (sin pantalla)."""

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from inventario.nucleo import lotes  # noqa: E402
from inventario.ui import avisos  # noqa: E402
from inventario.ui.tema import aplicar_tema  # noqa: E402

from conftest import datos_equipo  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instancia = QApplication.instance() or QApplication([])
    aplicar_tema(instancia, oscuro=False)
    return instancia


@pytest.fixture
def sin_modales(monkeypatch):
    """Los avisos se registran en vez de abrir una ventana que espere un clic."""
    mostrados = []
    for nombre in ("info", "aviso", "error"):
        monkeypatch.setattr(
            avisos, nombre, lambda *a, _n=nombre, **k: mostrados.append((_n, a[1]))
        )
    monkeypatch.setattr(avisos, "confirmar", lambda *a, **k: True)
    return mostrados


@pytest.mark.parametrize("oscuro", [False, True])
def test_tema(app, oscuro):
    aplicar_tema(app, oscuro=oscuro)
    assert app.styleSheet()
    aplicar_tema(app, oscuro=False)


def test_menu_muestra_ot_activa(app, lote_con_equipos):
    from inventario.ui.ventana_principal import VentanaPrincipal

    ventana = VentanaPrincipal()
    assert "ACME · OT-553" in ventana.inicio.lbl_ot.text()
    assert "2 equipo(s)" in ventana.inicio.lbl_ot_detalle.text()
    assert not ventana.inicio.btn_legacy.isVisibleTo(ventana)


def test_dialogo_nuevo_lote(app, carpeta, sin_modales):
    from inventario.ui.dialogos import DialogoNuevoLote

    dlg = DialogoNuevoLote(None, "Retiro")
    dlg.combo_cli.setCurrentText("Acme Ltda")
    dlg.entry_num.setText("guia 88")
    assert dlg.lbl_prev.text() == "📁 RETIROS / ACME_LTDA / GUIA-88"
    dlg._confirmar()
    assert dlg.lote and dlg.lote["numero"] == "88"
    assert lotes.listar_lotes_abiertos()[0]["cliente"] == "ACME_LTDA"


def test_formulario_guarda_equipo(app, lote_con_equipos, sin_modales):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    ventana = VentanaPrincipal()
    retiro = lotes.abrir_lote(lotes.hacer_lote("Retiro", "ACME", "9"))
    form = PaginaFormulario(ventana, datos_equipo("NUEVO"), retiro)
    form.revision._filas[1][1].setCurrentText("MALO")
    assert form.revision._filas[1][2].isEnabled()
    form.revision._filas[1][2].setText("pantalla rota")
    form.entry_obs.setText("obs general")
    form.office.chk.setChecked(True)
    form.office.entry_key.setText("OFF-KEY")
    form._guardar()

    (eq,) = lotes.leer_equipos_lote(retiro)
    assert eq["TIENE_FALLAS"] and eq["OBS"] == "obs general" and eq["SN_APP"] == "OFF-KEY"
    assert sin_modales[-1][0] == "info"


def test_entrega_guarda_componentes_ok(app, lote_con_equipos, sin_modales):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E9"), lote_con_equipos)
    assert form.revision is None
    form._guardar()
    eq = [e for e in lotes.leer_equipos_lote(lote_con_equipos) if e["SERIAL"] == "E9"][0]
    assert not eq["TIENE_FALLAS"] and len(eq["DETALLE_COMPONENTES"]) == 11


def test_dialogos_abren(app, lote_con_equipos):
    from inventario.nucleo.transformadores import equipos_en_orden_de_escaneo
    from inventario.ui.clonacion import VentanaObservaciones
    from inventario.ui.dialogos import DialogoElegirLote
    from inventario.ui.modulos.etiquetas import DialogoEtiquetaManual
    from inventario.ui.modulos.mover_ot import DialogoMoverOT
    from inventario.ui.modulos.panel_clonacion import PanelClonacion
    from inventario.ui.modulos.transformadores import DialogoTransformadores

    lote = lote_con_equipos
    elegir = DialogoElegirLote(None, "Cambiar", "Activar", lotes.listar_lotes_abiertos())
    assert elegir.tabla.rowCount() == 1
    transf = DialogoTransformadores(None, lote, equipos_en_orden_de_escaneo(lote))
    assert len(transf.entradas) == 2
    mover = DialogoMoverOT(None, lote, lotes.leer_equipos_lote(lote))
    assert mover.tabla.rowCount() == 2
    DialogoEtiquetaManual(None)

    panel = PanelClonacion(None)
    panel.lote, panel.llegados, panel.esperados = lote, lotes.leer_equipos_lote(lote), ["SN1", "X"]
    panel._pintar()
    assert panel.tabla.rowCount() == 3

    obs = VentanaObservaciones(datos_equipo(), lote)
    obs.reject()  # cerrar con la X = enviar igual
    assert obs.resultado()[2] is True


def test_con_espera_devuelve_y_relanza(app):
    from inventario.ui.tareas import con_espera

    assert con_espera(None, "t", "x", lambda a: a * 2, 21) == 42

    def falla():
        raise ValueError("mal")

    with pytest.raises(ValueError):
        con_espera(None, "t", "x", falla)


def test_escaneo_en_segundo_plano_abre_formulario(app, lote_con_equipos, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QThreadPool

    from inventario.ui import ventana_principal

    monkeypatch.setattr(ventana_principal, "get_inventory_fast", lambda: datos_equipo("SC1"))
    ventana = ventana_principal.VentanaPrincipal()
    ventana.iniciar_escaneo()
    assert ventana.paginas.currentWidget() is ventana.escaneo
    QThreadPool.globalInstance().waitForDone(QDeadlineTimer(5000))
    QCoreApplication.processEvents()
    assert ventana.formulario is not None
    assert ventana.paginas.currentWidget() is ventana.formulario
