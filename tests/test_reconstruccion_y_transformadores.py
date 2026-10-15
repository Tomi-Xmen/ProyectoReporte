import json
import os

from inventario.nucleo import lotes, reconstruccion, transformadores


def test_reconstruir_ot_canonica_es_identica(lote_con_equipos):
    lote = lote_con_equipos
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        antes = f.read()
    os.remove(lotes.ruta_html_lote(lote))
    os.remove(lotes.ruta_fusionado(lote))

    carpetas = reconstruccion.carpetas_a_reconstruir(lotes.ruta_reportes())
    total, regenerados, sueltos, errores = reconstruccion.reconstruir_carpetas(carpetas)
    assert (total, sueltos, errores) == (2, [], [])
    assert len(regenerados) == 1
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert f.read() == antes


def test_reconstruir_carpeta_suelta(lote_con_equipos, tmp_path):
    suelta = tmp_path / "bajados"
    suelta.mkdir()
    for ruta, _ in lotes.leer_equipos_lote_con_ruta(lote_con_equipos):
        (suelta / os.path.basename(ruta)).write_bytes(open(ruta, "rb").read())
    total, regenerados, sueltos, _errores = reconstruccion.reconstruir_carpetas(
        [str(suelta)]
    )
    assert total == 2 and regenerados == []
    assert any(a.endswith("_RECONSTRUIDO.html") for a in sueltos)
    assert any(a.endswith("_RECONSTRUIDO_FUSIONADO.json") for a in sueltos)


def test_seriales_del_portapapeles():
    texto = "T1\tcelda vecina\r\n\n  \t T2  \nT3"
    assert transformadores.seriales_del_portapapeles(texto) == ["T1", "T2", "T3"]


def test_calcular_y_guardar_transformadores(lote_con_equipos):
    lote = lote_con_equipos
    registros = transformadores.equipos_en_orden_de_escaneo(lote)
    filas = [(r, j, t) for (r, j), t in zip(registros, ["TX-1", "tx-1"])]
    cambios, duplicados = transformadores.calcular_cambios(filas)
    assert len(cambios) == 2 and len(duplicados) == 1

    assert transformadores.guardar_transformadores(lote, cambios) == []
    with open(lotes.ruta_fusionado(lote), encoding="utf-8") as f:
        assert {e["SN_Transf"] for e in json.load(f)} == {"TX-1", "tx-1"}
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert "Serie Transformador" in f.read()

    # Vaciar la celda devuelve el equipo a PENDIENTE.
    registros = transformadores.equipos_en_orden_de_escaneo(lote)
    cambios, _ = transformadores.calcular_cambios([(r, j, "") for r, j in registros])
    transformadores.guardar_transformadores(lote, cambios)
    assert all(
        transformadores.transformador_actual(j) == "PENDIENTE"
        for _, j in transformadores.equipos_en_orden_de_escaneo(lote)
    )
