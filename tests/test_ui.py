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


def test_dialogo_requerimiento_solo_en_entrega(app, carpeta, sin_modales):
    from inventario.ui.dialogos import DialogoNuevoLote

    dlg = DialogoNuevoLote(None, "Entrega")
    assert dlg.requerimiento.isVisibleTo(dlg)
    dlg.combo_cli.setCurrentText("Acme")
    dlg.entry_num.setText("553")
    dlg.requerimiento.combo_cpu.setCurrentText("i5")
    dlg.requerimiento.combo_ram.setCurrentText("16")
    dlg.requerimiento.combo_tipo.setCurrentText("SSD")
    dlg._confirmar()
    assert lotes.requerimiento_en_disco(dlg.lote["ruta"]) == {
        "cpu": "i5",
        "ram_gb": 16,
        "disco_tipo": "SSD",
    }

    dlg.combo_mov.setCurrentText("Retiro")
    assert not dlg.requerimiento.isVisibleTo(dlg)


def test_formulario_avisa_equipo_distinto(app, carpeta, sin_modales, monkeypatch):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["requerimiento"] = {"ram_gb": 16, "office": True}
    lotes.abrir_lote(lote)
    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E1"), lote)
    assert "DISTINTO A LO PEDIDO" in form.banner_req.text()
    assert "RAM: tiene 8 GB" in form.banner_req.text()
    assert "Office" in form.banner_req.text()

    # Marcar Office saca esa diferencia en el momento.
    form.office.chk.setChecked(True)
    assert "Office" not in form.banner_req.text()

    # Si no se confirma, no se guarda.
    preguntas = []
    monkeypatch.setattr(
        avisos, "confirmar", lambda _p, titulo, _t: preguntas.append(titulo) or False
    )
    form._guardar()
    assert preguntas == ["Equipo distinto a lo pedido"]
    assert lotes.leer_equipos_lote(lote) == []


def test_formulario_sin_requerimiento_no_muestra_tarjeta(app, lote_con_equipos):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E2"), lote_con_equipos)
    assert form.tarjeta_req is None


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
    form.office.entry_numero.setText("OFF-KEY")
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


# ─────────────────────────────────────────────────────────
#  Licencias de Office
# ─────────────────────────────────────────────────────────
@pytest.fixture
def base_office(carpeta):
    from inventario.nucleo import licencias_office

    from test_licencias_office import maestra

    licencias_office.importar(licencias_office.interpretar_filas(maestra())[0])
    return licencias_office


def test_seccion_office_busca_la_caja(app, base_office):
    from inventario.ui.componentes import SeccionOffice

    sec = SeccionOffice(serial="SN-NUEVO")
    sec.entry_caja.setText("1000000798904")  # el código de barras de la caja
    sec._buscar_caja()
    assert sec.chk.isChecked() and sec.entry_numero.text() == "88880811420680"
    assert sec.entry_numero.isReadOnly() and sec.combo_version.currentText() == "2013"
    assert "disponible" in sec.lbl_caja.text() and sec.activar()
    assert sec.caja() == "1000000798904"

    sec.entry_caja.setText("NO-EXISTE")
    sec._buscar_caja()
    assert "no está en la base" in sec.lbl_caja.text()
    assert sec.entry_numero.text() == "" and not sec.entry_numero.isReadOnly()

    # Asignada a otro equipo: avisa y no carga la key ajena.
    sec.entry_caja.setText("88880811759930")
    sec._buscar_caja()
    assert "otro equipo" in sec.lbl_caja.text() and sec.entry_numero.text() == ""


def test_formulario_asigna_caja_y_activa(app, lote_con_equipos, base_office, sin_modales, monkeypatch):
    from inventario.nucleo import activacion_office
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal
    from test_licencias_office import K1

    activadas = []
    monkeypatch.setattr(
        activacion_office,
        "cargar_y_activar",
        lambda clave, version: activadas.append((clave, version)) or ("activada", "Office activado."),
    )
    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E7"), lote_con_equipos)
    form.office.entry_caja.setText("88880811420680")
    form.office._buscar_caja()
    form._guardar()

    eq = [e for e in lotes.leer_equipos_lote(lote_con_equipos) if e["SERIAL"] == "E7"][0]
    # Al JSON va el número de caja; la key solo se usa para activar.
    assert (eq["SN_APP"], eq["OFFICE"], eq["OFFICE_CAJA"]) == ("88880811420680", "Office 2013", "88880811420680")
    assert activadas == [(K1, "2013")]
    lic = base_office.buscar("88880811420680")
    assert (lic["serial"], lic["documento"], lic["activacion"]) == ("E7", "OT-553", "activada")
    assert sin_modales[-1][0] == "info"
    with open(lotes.ruta_html_lote(lote_con_equipos), encoding="utf-8") as f:
        contenido = f.read()
    assert "(Caja: 88880811420680)" in contenido and K1 not in contenido


def test_formulario_no_guarda_si_la_caja_es_de_otro(app, lote_con_equipos, base_office, sin_modales):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E8"), lote_con_equipos)
    form.office.chk.setChecked(True)
    form.office.entry_caja.setText("88880811759930")  # asignada a MXL0DEMO01
    form._guardar()
    assert sin_modales[-1][0] == "error"
    assert not [e for e in lotes.leer_equipos_lote(lote_con_equipos) if e["SERIAL"] == "E8"]


def test_retiro_libera_la_caja(app, carpeta, base_office, sin_modales):
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    retiro = lotes.abrir_lote(lotes.hacer_lote("Retiro", "MUNDO_DULCE", "77"))
    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("MXL0DEMO01"), retiro)
    assert form.chk_liberar.isChecked() and form.office.entry_caja is None
    form._guardar()
    lic = base_office.buscar("88880811759930")
    assert lic["estado"] == "disponible"
    assert "GUIA-77" in base_office.historial("88880811759930")[0]["detalle"]
    assert "liberada" in sin_modales[-1][1] or sin_modales[-1][0] == "info"


def test_dialogo_licencias_importa_y_lista(app, carpeta, sin_modales):
    from inventario.ui.modulos.licencias import DialogoLicencias
    from test_licencias_office import maestra

    dlg = DialogoLicencias(None)
    assert dlg.tabla.rowCount() == 0 and "Todavía no hay" in dlg.lbl_resumen.text()
    dlg.importar_filas(maestra())
    assert dlg.tabla.rowCount() == 4
    assert "Office 2013: 1 disponible(s) de 2" in dlg.lbl_resumen.text()
    dlg.entry_filtro.setText("demo")
    assert dlg.tabla.rowCount() == 1



def test_dialogo_ot_con_office(app, carpeta, sin_modales):
    from inventario.nucleo import licencias_office
    from inventario.ui.dialogos import DialogoNuevoLote

    from test_office_ot import cargar_cajas

    cargar_cajas(("C-1", "1"), ("C-2", "1"))
    dlg = DialogoNuevoLote(None, "Entrega")
    assert dlg.combo_office.itemText(1) == "Office 2016 · 2 disponible(s)"
    dlg.combo_cli.setCurrentText("Acme")
    dlg.entry_num.setText("553")
    dlg.combo_office.setCurrentIndex(1)
    dlg._confirmar()
    assert lotes.office_en_disco(dlg.lote["ruta"]) == "2016"

    # Al volver a escribir la misma OT, el combo muestra con qué Office va.
    otra = DialogoNuevoLote(None, "Entrega")
    otra.combo_cli.setCurrentText("Acme")
    otra.entry_num.setText("553")
    assert otra.combo_office.currentData() == "2016"
    otra.combo_mov.setCurrentText("Retiro")
    assert not otra.combo_office.isVisibleTo(otra)
    assert licencias_office.disponibles("2016") == 2


def test_formulario_de_ot_con_office_sin_escanear_queda_pendiente(app, carpeta, sin_modales):
    from inventario.nucleo import licencias_office, office_ot
    from inventario.ui.ventana_principal import PaginaFormulario, VentanaPrincipal

    from test_office_ot import cargar_cajas

    cargar_cajas(("C-1", "1"))
    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["office"] = "2016"
    lotes.abrir_lote(lote)

    form = PaginaFormulario(VentanaPrincipal(), datos_equipo("E1"), lote)
    assert form.office.chk.isChecked() and not form.office.combo_version.isEnabled()
    assert "Asignar Office" in form.office.lbl_caja.text()
    form._guardar()
    e1 = [e for e in lotes.leer_equipos_lote(lote) if e["SERIAL"] == "E1"][0]
    # La app no elige: va con Office 2016, pero la caja se elige después.
    assert (e1["OFFICE"], e1["SN_APP"]) == ("Office 2016", "PENDIENTE")
    assert office_ot.necesita_office(e1) and licencias_office.disponibles("2016") == 1


def test_pantalla_asignar_office(app, carpeta, sin_modales, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from inventario.nucleo import licencias_office
    from inventario.ui.modulos.asignar_office import DialogoAsignarOffice

    from test_office_ot import cargar_cajas

    cargar_cajas(("C-1", "1"), ("C-2", "2"), ("C-3", "2"))
    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["office"] = "2016"
    lote = lotes.abrir_lote(lote)
    from test_office_ot import guardar

    for serial in ("SN1", "SN2"):
        guardar(lote, serial, tiene=True)

    dlg = DialogoAsignarOffice(None, lote)
    assert dlg.tabla_libres.rowCount() == 3 and "Disponibles Office 2016: 3" in dlg.lbl_libres.text()

    # Escanear en la fila 1 y doble clic en una disponible para la fila 2.
    dlg.entradas[0].setText("C-3")
    dlg._revisar_todo()
    assert dlg.tabla.item(0, 4).text() == "✅ Disponible"
    assert dlg.tabla_libres.rowCount() == 2  # la C-3 ya no figura libre
    dlg._usar_libre(dlg.tabla_libres.model().index(0, 0))
    assert dlg.entradas[1].text() == "C-1"
    # Antes de guardar no hay key para copiar.
    assert not dlg.tabla.cellWidget(0, 6).isEnabled()

    dlg._guardar()
    assert "2 equipo(s) actualizado(s)" in dlg.lbl_estado.text()
    key_sn1 = licencias_office.buscar("C-3")["clave"]
    assert dlg.tabla.item(0, 5).text() == key_sn1
    dlg._copiar_key(0)
    assert QApplication.clipboard().text() == key_sn1

    # Una caja repetida no deja guardar.
    dlg.entradas[1].setText("C-3")
    dlg._guardar()
    assert sin_modales[-1][0] == "error"
    assert licencias_office.buscar("C-1")["serial"] == "SN2"
