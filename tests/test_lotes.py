import json
import os

from inventario.nucleo import lotes

from conftest import datos_equipo


def test_normalizar_numero():
    assert lotes.normalizar_numero("OT 553") == "553"
    assert lotes.normalizar_numero("ot-553") == "553"
    assert lotes.normalizar_numero("guía: 88/91") == "88-91"
    assert lotes.normalizar_numero("CON") == ""
    assert lotes.normalizar_numero("   ") == ""


def test_normalizar_cliente():
    assert lotes.normalizar_cliente("Acme Ltda.") == "ACME_LTDA"
    assert lotes.normalizar_cliente("¡¿!") == "GENERAL"


def test_numeros_lote_segun_movimiento():
    entrega = lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G1")
    retiro = lotes.hacer_lote("Retiro", "ACME", "G1")
    assert lotes.numeros_lote(entrega) == ("553", "G1")
    assert lotes.numeros_lote(retiro) == ("Sin Orden", "G1")


def test_guardar_equipo_genera_derivados(lote_con_equipos):
    lote = lote_con_equipos
    assert lotes.contar_equipos(lote["ruta"]) == 2
    with open(lotes.ruta_fusionado(lote), encoding="utf-8") as f:
        fusionado = json.load(f)
    assert {e["SERIAL"] for e in fusionado} == {"SN1", "SN2"}
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        html = f.read()
    assert '<span id="total-count">2</span>' in html
    assert "SN1" in html and "SN2" in html


def test_reescanear_pisa_el_registro(lote_con_equipos):
    lote = lote_con_equipos
    total = lotes.guardar_equipo_general(
        lote, datos_equipo("SN1"), "otra vez", False, "", "2016", []
    )
    assert total == 2
    sn1 = [e for e in lotes.leer_equipos_lote(lote) if e["SERIAL"] == "SN1"]
    assert len(sn1) == 1 and sn1[0]["OBS"] == "otra vez"


def test_lote_activo_y_cierre(lote_con_equipos):
    lote = lote_con_equipos
    assert lotes.cargar_lote_activo()["ruta"] == lote["ruta"]
    assert lotes.cargar_lote_activo()["numero_sec"] == "G-9"

    total, malos = lotes.cerrar_lote(lote)
    assert (total, malos) == (2, [])
    assert lotes.esta_cerrado(lote["ruta"])
    assert lotes.cargar_lote_activo() is None
    assert lotes.listar_lotes_abiertos() == []

    lotes.reabrir_lote(lote)
    assert [l["numero"] for l in lotes.listar_lotes_abiertos()] == ["553"]


def test_retiro_con_fallas(carpeta):
    lote = lotes.abrir_lote(lotes.hacer_lote("Retiro", "ACME", "77"))
    comps = [{"nombre": "Pantalla", "estado": "MALO", "obs": "rota"}]
    lotes.guardar_equipo_general(lote, datos_equipo("R1"), "", True, "KEY-1", "2019", comps)
    (eq,) = lotes.leer_equipos_lote(lote)
    assert eq["TIENE_FALLAS"] and eq["OFFICE"] == "Office 2019" and eq["SN_APP"] == "KEY-1"
    _total, malos = lotes.cerrar_lote(lote)
    assert [m["SERIAL"] for m in malos] == ["R1"]


def test_mover_equipos(lote_con_equipos):
    origen = lote_con_equipos
    destino = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "600"))
    assert lotes.mover_equipos_a_lote(origen, ["SN1"], destino) == 1
    assert [e["SERIAL"] for e in lotes.leer_equipos_lote(origen)] == ["SN2"]
    (movido,) = lotes.leer_equipos_lote(destino)
    assert movido["SERIAL"] == "SN1" and movido["OT_ID"] == "600"
    assert lotes.mover_equipos_a_lote(origen, ["SN2"], origen) == 0


def test_serial_repetido_en_otra_ot(lote_con_equipos):
    otra = lotes.abrir_lote(lotes.hacer_lote("Entrega", "BETA", "1"))
    encontrado = lotes.buscar_serial_en_abiertos("SN1", excluir_ruta=otra["ruta"])
    assert encontrado["cliente"] == "ACME"
    assert lotes.buscar_serial_en_abiertos("SN1", excluir_ruta=lote_con_equipos["ruta"]) is None


def test_pendientes_de_envio(lote_con_equipos):
    lote = lote_con_equipos
    pendientes, hay = lotes.pendientes_envio()
    assert hay and [p[2] for p in pendientes] == ["OT-553"] and pendientes[0][4]
    lotes.marcar_enviado(lote["ruta"])
    assert lotes.pendientes_envio()[0] == []
    # Contenido nuevo vuelve a dejarla pendiente.
    lotes.guardar_equipo_general(lote, datos_equipo("SN3"), "", False, "", "2016", [])
    assert len(lotes.pendientes_envio()[0]) == 1


def test_backup(lote_con_equipos):
    ruta = lotes.crear_backup("prueba")
    assert ruta and ruta.endswith("_prueba.zip") and os.path.isfile(ruta)


def test_migrar_legacy(carpeta):
    os.makedirs(lotes.ruta_reportes())
    viejo = os.path.join(lotes.ruta_reportes(), "data_Retiro_X.json")
    with open(viejo, "w", encoding="utf-8") as f:
        json.dump({"SERIAL": "L1", "DATA": datos_equipo("L1")}, f)
    assert lotes.pendientes_legacy()["Retiro"] == [viejo]
    lote = lotes.hacer_lote("Retiro", "ACME", "5")
    assert lotes.migrar_legacy_a_lote([viejo], lote) == 1
    assert not os.path.exists(viejo)
    assert lotes.leer_equipos_lote(lote)[0]["GUIA_ID"] == "5"
