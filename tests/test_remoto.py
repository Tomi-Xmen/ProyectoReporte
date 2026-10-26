import json
import os

import pytest

from inventario.nucleo import lotes, remoto
from inventario.nucleo.transformadores import equipos_en_orden_de_escaneo


def _escribir(ruta, jdata):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f)


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def test_bajado_conserva_el_transformador_local(tmp_path):
    local, bajado = tmp_path / "local.json", tmp_path / "bajado.json"
    _escribir(local, {"SERIAL": "SN1", "SN_Transf": "WDJTH123", "OBS": "vieja"})
    _escribir(bajado, {"SERIAL": "SN1", "SN_Transf": "PENDIENTE", "OBS": "nueva"})

    remoto.guardar_bajado_sin_pisar(bajado, local)

    jdata = _leer(local)
    assert jdata["SN_Transf"] == "WDJTH123"
    assert jdata["OBS"] == "nueva"  # el resto viene del servidor


def test_bajado_sin_local_o_local_sin_transformador_queda_tal_cual(tmp_path):
    bajado = tmp_path / "bajado.json"
    _escribir(bajado, {"SERIAL": "SN1", "SN_Transf": "PENDIENTE"})

    nuevo = tmp_path / "nuevo.json"
    remoto.guardar_bajado_sin_pisar(bajado, nuevo)
    assert _leer(nuevo)["SN_Transf"] == "PENDIENTE"

    pendiente = tmp_path / "pendiente.json"
    _escribir(pendiente, {"SERIAL": "SN1", "SN_Transf": "PENDIENTE"})
    remoto.guardar_bajado_sin_pisar(bajado, pendiente)
    assert _leer(pendiente)["SN_Transf"] == "PENDIENTE"


def test_bajado_ilegible_no_pisa_el_local(tmp_path):
    local, bajado = tmp_path / "local.json", tmp_path / "bajado.json"
    _escribir(local, {"SERIAL": "SN1", "SN_Transf": "WDJTH123"})
    bajado.write_text("{roto", encoding="utf-8")

    with pytest.raises(ValueError):
        remoto.guardar_bajado_sin_pisar(bajado, local)
    assert _leer(local)["SN_Transf"] == "WDJTH123"


def test_traer_del_servidor_no_borra_los_transformadores(lote_con_equipos, monkeypatch):
    """El caso real: los clonados subieron su JSON con PENDIENTE y en la central
    ya se habían asignado los cargadores antes de volver a traer."""
    lote = lote_con_equipos
    servidor = {}
    for ruta, jdata in equipos_en_orden_de_escaneo(lote):
        servidor[f"/nas/{os.path.basename(ruta)}"] = dict(jdata, SN_Transf="PENDIENTE")
    nuevo = dict(_leer(next(iter(r for r, _ in equipos_en_orden_de_escaneo(lote)))))
    nuevo.update(SERIAL="SN3", SN_Transf="PENDIENTE")
    servidor["/nas/" + os.path.basename(lotes.ruta_json_equipo(lote, "SN3"))] = nuevo

    for ruta, jdata in equipos_en_orden_de_escaneo(lote):
        jdata["SN_Transf"] = f"CARGADOR-{jdata['SERIAL']}"
        _escribir(ruta, jdata)

    class SCPFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, origen, local_path):
            _escribir(local_path, servidor[origen])

    class ClienteFalso:
        def get_transport(self):
            return None

    monkeypatch.setattr(remoto, "SCPClient", SCPFalso, raising=False)
    monkeypatch.setattr(
        remoto, "correr_remoto", lambda c, cmd: (0, "\n".join(servidor), "")
    )

    bajados, total = remoto.descargar_equipos_remotos(ClienteFalso(), lote)

    assert (bajados, total) == (3, 3)
    trafos = {j["SERIAL"]: j["SN_Transf"] for _, j in equipos_en_orden_de_escaneo(lote)}
    assert trafos == {"SN1": "CARGADOR-SN1", "SN2": "CARGADOR-SN2", "SN3": "PENDIENTE"}
    fusionado = {f["SERIAL"]: f["SN_Transf"] for f in _leer(lotes.ruta_fusionado(lote))}
    assert fusionado == trafos
