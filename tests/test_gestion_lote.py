"""Gestión del lote desde el celular: cargadores, mover, quitar, documento y cierre."""

import json
import os

import pytest

from inventario.nucleo import gestion_lote, lotes, sincronizacion
from inventario.nucleo.api_celular import ApiCelular

from conftest import datos_equipo

LOTE = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}


@pytest.fixture
def api():
    eventos = []
    api = ApiCelular(token="secreto", reglas=[], al_evento=eventos.append)
    api.eventos = eventos
    return api


def pedir(api, ruta, datos):
    cab = {"authorization": "Bearer secreto"}
    return api.atender("POST", ruta, cab, json.dumps(datos).encode())


def escanear(api, texto, **extra):
    codigo, r = pedir(
        api, "/api/v1/escaneo", {"lote": LOTE, "lecturas": [{"texto": texto}], **extra}
    )
    assert codigo == 200, r
    return r


def transformadores(lote):
    return {e["SERIAL"]: e["SN_Transf"] for e in lotes.leer_equipos_lote(lote)}


# ─── Cargador: leer y elegir el equipo ───────────────────
def test_leer_cargador_no_asigna_nada(api, lote_con_equipos):
    r = escanear(api, "TR-0001", esperado="Transformador", solo_leer=True)
    assert (r["estado"], r["sn_transf"], r["equipo"]) == ("leido", "TR-0001", None)
    assert set(transformadores(lote_con_equipos).values()) == {"PENDIENTE"}

    # Con el equipo elegido en el celular, se asigna a ESE (no al primero libre).
    r = escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN2")
    assert (r["estado"], r["equipo"]) == ("asignado", "SN2")

    # Leerlo otra vez dice de quién es hoy.
    r = escanear(api, "TR-0001", esperado="Transformador", solo_leer=True)
    assert (r["estado"], r["equipo"]) == ("leido", "SN2")


def test_pasar_cargador_de_un_equipo_a_otro(api, lote_con_equipos):
    escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN1")
    escanear(api, "TR-0002", tipo="Transformador", serial_equipo="SN2")

    # Sin reasignar, sigue siendo "duplicado" como siempre.
    r = escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN2")
    assert r["estado"] == "duplicado"

    r = escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN2", reasignar=True)
    assert (r["estado"], r["equipo"], r["desde"], r["reemplazo"]) == (
        "asignado", "SN2", "SN1", "TR-0002",
    )
    assert transformadores(lote_con_equipos) == {"SN1": "PENDIENTE", "SN2": "TR-0001"}

    r = escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN2", reasignar=True)
    assert r["estado"] == "ya_estaba"
    r = escanear(api, "TR-0009", tipo="Transformador", serial_equipo="NOESTA1", reasignar=True)
    assert r["estado"] == "equipo_no_encontrado"
    # El HTML del lote ya lo muestra.
    with open(lotes.ruta_html_lote(lote_con_equipos), encoding="utf-8") as f:
        assert "TR-0001" in f.read()


# ─── Mover y quitar equipos ──────────────────────────────
def test_mover_equipo_a_otro_lote(api, lote_con_equipos):
    otro = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "600", numero_sec="G-60"))
    escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN1")

    destino = {"mov": "Entrega", "cliente": "ACME", "numero": "600"}
    codigo, r = pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "sn1", "destino": destino})
    assert codigo == 200
    assert (r["estado"], r["serial"], r["total"]) == ("movido", "SN1", 1)
    (movido,) = lotes.leer_equipos_lote(otro)
    assert (movido["SERIAL"], movido["OT_ID"], movido["GUIA_ID"], movido["SN_Transf"]) == (
        "SN1", "600", "G-60", "TR-0001",
    )

    # Mismo lote, ya está en el destino, destino inexistente o sin destino.
    assert pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "SN2", "destino": LOTE})[0] == 400
    lotes.guardar_equipo_general(otro, datos_equipo("SN2"), "", False, "", "2016", [])
    codigo, r = pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "SN2", "destino": destino})
    assert (codigo, r["error"]) == (409, "ya_esta")
    falso = {**destino, "numero": "999"}
    assert pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "SN2", "destino": falso})[0] == 404
    assert pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "SN2"})[0] == 400
    assert pedir(api, "/api/v1/equipo/mover", {"lote": LOTE, "serial": "NOESTA", "destino": destino})[0] == 404


def test_quitar_equipo_va_a_la_papelera(api, lote_con_equipos):
    codigo, r = pedir(api, "/api/v1/equipo/quitar", {"lote": LOTE, "serial": "SN1"})
    assert codigo == 200 and (r["estado"], r["serial"], r["total"]) == ("quitado", "SN1", 1)
    assert [e["SERIAL"] for e in lotes.leer_equipos_lote(lote_con_equipos)] == ["SN2"]
    with open(lotes.ruta_fusionado(lote_con_equipos), encoding="utf-8") as f:
        assert [e["SERIAL"] for e in json.load(f)] == ["SN2"]

    (guardado,) = os.listdir(gestion_lote.ruta_papelera(lote_con_equipos))
    assert ".quitado-" in guardado and not guardado.endswith(".json")
    # La papelera no aparece como cliente ni entra al backup ni al envío.
    assert lotes.clientes_existentes() == ["ACME"]
    assert pedir(api, "/api/v1/equipo/quitar", {"lote": LOTE, "serial": "SN1"})[0] == 404


# ─── Documento secundario ────────────────────────────────
def test_completar_la_guia_actualiza_todos_los_equipos(api, carpeta):
    lote = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553"))
    lotes.guardar_lote_activo(lote)
    for serial in ("SN1", "SN2"):
        lotes.guardar_equipo_general(lote, datos_equipo(serial), "", False, "", "2016", [])
    assert {e["GUIA_ID"] for e in lotes.leer_equipos_lote(lote)} == {"Sin Guía"}

    codigo, r = pedir(api, "/api/v1/lote/documento", {"lote": LOTE, "numero_sec": "guía 77"})
    assert codigo == 200 and r["numero_sec"] == "77"
    assert {e["GUIA_ID"] for e in lotes.leer_equipos_lote(lote)} == {"77"}
    assert {e["OT_ID"] for e in lotes.leer_equipos_lote(lote)} == {"553"}
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert "Sin Guía" not in f.read()
    # La OT activa del PC también: lo próximo que se escanee ahí sale con la guía.
    assert lotes.cargar_lote_activo()["numero_sec"] == "77"

    # En un retiro el segundo documento es la OT.
    retiro = lotes.abrir_lote(lotes.hacer_lote("Retiro", "ACME", "2121"))
    lotes.guardar_equipo_general(retiro, datos_equipo("R1"), "", False, "", "2016", [])
    gestion_lote.fijar_documento_secundario(retiro, "OT 900")
    (eq,) = lotes.leer_equipos_lote(retiro)
    assert (eq["OT_ID"], eq["GUIA_ID"]) == ("900", "2121")

    # Vacío lo borra; basura se rechaza.
    gestion_lote.fijar_documento_secundario(retiro, "")
    assert lotes.leer_equipos_lote(retiro)[0]["OT_ID"] == "Sin Orden"
    codigo, r = pedir(api, "/api/v1/lote/documento", {"lote": LOTE, "numero_sec": "CON"})
    assert (codigo, r["error"]) == (400, "dato")


# ─── Resumen y cierre ────────────────────────────────────
def test_resumen_y_cierre_desde_el_celular(api, lote_con_equipos):
    escanear(api, "TR-0001", tipo="Transformador", serial_equipo="SN1")
    codigo, r = pedir(api, "/api/v1/lote/resumen", {"lote": LOTE})
    assert codigo == 200
    assert (r["equipos"], r["sin_cargador"], r["con_fallas"], r["falta_documento"]) == (
        2, ["SN2"], 0, None,
    )

    codigo, r = pedir(api, "/api/v1/lote/cerrar", {"lote": LOTE})
    assert codigo == 200 and (r["estado"], r["total"]) == ("cerrado", 2)
    assert r["backup"] and r["backup"].endswith("_cierre.zip")
    assert lotes.esta_cerrado(lote_con_equipos["ruta"])
    # Era la OT activa del PC: queda sin OT activa, igual que al cerrar en el PC.
    assert lotes.cargar_lote_activo() is None
    # Ya cerrado, el celular no puede seguir trabajando en él.
    assert pedir(api, "/api/v1/lote/resumen", {"lote": LOTE})[0] == 409
    assert [e["respuesta"]["estado"] for e in api.eventos][-1] == "cerrado"


def test_resumen_avisa_documento_faltante(carpeta):
    lote = lotes.abrir_lote(lotes.hacer_lote("Retiro", "ACME", "5"))
    assert gestion_lote.resumen_cierre(lote)["falta_documento"] == "OT"


# ─── Quitar y el traer automático ────────────────────────
def test_lo_quitado_no_vuelve_del_servidor(lote_con_equipos):
    lote = lote_con_equipos
    ruta_sn1 = lotes.ruta_json_equipo(lote, "SN1")
    nombre = os.path.basename(ruta_sn1)
    with open(ruta_sn1, "rb") as f:
        en_servidor = f.read()  # lo subió "Enviar" tal cual
    firma = sincronizacion.huella(en_servidor)

    gestion_lote.quitar_equipo(lote, "SN1")
    assert sincronizacion.a_traer({nombre: firma}, lote["ruta"]) == ({}, {})
    # Si el equipo manda algo nuevo (otro escaneo), sí vuelve.
    assert nombre in sincronizacion.a_traer({nombre: "f" * 40}, lote["ruta"])[0]
