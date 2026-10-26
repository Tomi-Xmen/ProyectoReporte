"""Traer automático de la OT publicada: qué se baja, qué no se pisa, re-etiquetado."""

import json
import os

import pytest

from inventario.nucleo import lotes, remoto, sincronizacion

from conftest import datos_equipo


def json_remoto(serial, guia="G-VIEJA", transf="PENDIENTE"):
    """Un JSON como el que sube un equipo clonado."""
    return json.dumps(
        {
            "CLIENTE": "ACME",
            "SERIAL": serial,
            "MODELO": "HP",
            "TIPO_MOVIMIENTO": "Entrega",
            "GUIA_ID": guia,
            "OT_ID": "553",
            "SN_Transf": transf,
            "DATA": datos_equipo(serial),
            "ESCANEADO": "2026-10-24T10:00:00",
        },
        indent=4,
    )


class Servidor:
    """Lo que hay en la carpeta de la OT en el servidor: {archivo: texto}."""

    def __init__(self, lote, archivos):
        self.lote = lote
        self.archivos = archivos

    def huellas(self):
        return {n: sincronizacion.huella(t) for n, t in self.archivos.items()}

    def vuelta(self):
        """consultar() + aplicar(), sin SSH."""
        local = sincronizacion.lote_local(self.lote)
        traer, _ = sincronizacion.a_traer(self.huellas(), local["ruta"])
        contenidos = {n: self.archivos[n] for n in traer}
        return sincronizacion.aplicar(self.lote, self.huellas(), contenidos)


def nombre(serial):
    return os.path.basename(lotes.ruta_json_equipo(lotes.hacer_lote("Entrega", "ACME", "553"), serial))


@pytest.fixture
def publicado(carpeta):
    """La OT publicada; en esta PC la guía ya se completó después de publicar."""
    lote = lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-VIEJA")
    lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-NUEVA"))
    return lote


def test_trae_lo_nuevo_y_regenera_con_la_guia_local(publicado):
    srv = Servidor(publicado, {nombre("C1"): json_remoto("C1"), nombre("C2"): json_remoto("C2")})
    assert srv.vuelta() == 2
    local = sincronizacion.lote_local(publicado)
    equipos = lotes.leer_equipos_lote(local)
    assert {e["SERIAL"] for e in equipos} == {"C1", "C2"}
    assert {e["GUIA_ID"] for e in equipos} == {"G-NUEVA"}
    assert os.path.exists(lotes.ruta_html_lote(local))
    # Nada cambió en el servidor: la vuelta siguiente no escribe nada.
    assert srv.vuelta() == 0


def test_no_pisa_lo_cargado_en_la_pc(publicado):
    srv = Servidor(publicado, {nombre("C1"): json_remoto("C1")})
    srv.vuelta()
    local = sincronizacion.lote_local(publicado)

    # En la PC (o desde el celular) se le carga el transformador.
    ruta = lotes.ruta_json_equipo(local, "C1")
    with open(ruta, encoding="utf-8") as f:
        jdata = json.load(f)
    jdata["SN_Transf"] = "TR-1"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f)

    assert srv.vuelta() == 0
    assert lotes.leer_equipos_lote(local)[0]["SN_Transf"] == "TR-1"

    # Si el equipo vuelve a mandar (re-escaneo), lo del servidor es nuevo y entra.
    srv.archivos[nombre("C1")] = json_remoto("C1", transf="TR-SERVIDOR")
    assert srv.vuelta() == 1
    assert lotes.leer_equipos_lote(local)[0]["SN_Transf"] == "TR-SERVIDOR"


def test_lo_cargado_aca_antes_de_traer_manda(publicado):
    local = sincronizacion.lote_local(publicado)
    lotes.guardar_equipo_general(local, datos_equipo("C1"), "escaneado acá", False, "", "2016", [])
    srv = Servidor(publicado, {nombre("C1"): json_remoto("C1")})
    assert srv.vuelta() == 0
    assert lotes.leer_equipos_lote(local)[0]["OBS"] == "escaneado acá"


def test_lote_cerrado_en_la_pc_no_se_toca(publicado):
    local = sincronizacion.lote_local(publicado)
    lotes.cerrar_lote(local)
    assert Servidor(publicado, {nombre("C1"): json_remoto("C1")}).vuelta() == 0
    assert lotes.contar_equipos(local["ruta"]) == 0


def test_nombres_raros_del_servidor_se_ignoran(publicado):
    huellas = {
        "../fuera.json": "a" * 40,
        ".oculto.json": "a" * 40,
        "Reporte_FUSIONADO.json": "a" * 40,
        "notas.txt": "a" * 40,
    }
    assert sincronizacion.a_traer(huellas, sincronizacion.lote_local(publicado)["ruta"]) == ({}, {})


def test_lectura_del_servidor(monkeypatch, publicado):
    """huellas_remotas() y bajar() interpretan bien lo que devuelve el SSH."""
    a, b = nombre("C1"), nombre("C2")
    salidas = {
        "sha1sum": f"{'1' * 40}  {a}\n{'2' * 40}  {b}\nbasura\n",
        "cat": f"===ARCHIVO:{a}\n{json_remoto('C1')}\n===ARCHIVO:{b}\n{json_remoto('C2')}\n",
    }

    def correr(_cliente, comando):
        return 0, salidas["sha1sum" if "sha1sum" in comando else "cat"], ""

    monkeypatch.setattr(remoto, "correr_remoto", correr)
    assert sincronizacion.huellas_remotas(None, publicado) == {a: "1" * 40, b: "2" * 40}
    bajados = sincronizacion.bajar(None, publicado, [a, b, "../malo.json"])
    assert set(bajados) == {a, b}
    assert json.loads(bajados[b])["SERIAL"] == "C2"
