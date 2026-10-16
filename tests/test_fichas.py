import json

import pytest

from inventario.nucleo import lotes
from inventario.nucleo.api_celular import ApiCelular
from inventario.nucleo.escaneos import registrar_equipo
from inventario.nucleo.fichas import COMPONENTES, filas_tabla

LOTE = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}


@pytest.fixture
def api():
    eventos = []
    api = ApiCelular(token="secreto", reglas=[], al_evento=eventos.append)
    api.eventos = eventos
    return api


def pedir(api, ruta, datos):
    cuerpo = json.dumps(datos).encode()
    return api.atender("POST", ruta, {"authorization": "Bearer secreto"}, cuerpo)


def ficha(api, serial="SN1"):
    codigo, r = pedir(api, "/api/v1/equipo", {"lote": LOTE, "serial": serial})
    assert codigo == 200, r
    return r


def editar(api, cambios, serial="SN1", version=None):
    version = version or ficha(api, serial)["version"]
    return pedir(
        api,
        "/api/v1/equipo/editar",
        {"lote": LOTE, "serial": serial, "version": version, "cambios": cambios},
    )


def json_equipo(lote, serial):
    with open(lotes.ruta_json_equipo(lote, serial), encoding="utf-8") as f:
        return json.load(f)


def html_lote(lote):
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        return f.read()


def test_filas_tabla_saca_el_texto_de_las_celdas():
    filas = filas_tabla(
        "<tr><th>Módulo RAM</th><td>8GB | 2400</td></tr>"
        "<tr><td>Red Activa</td><td><span class='net-tag'>Realtek &amp; Co</span></td></tr>"
        "<tr><td colspan='2'>Sin red activa</td></tr>"
    )
    assert filas == [
        {"etiqueta": "Módulo RAM", "valor": "8GB | 2400"},
        {"etiqueta": "Red Activa", "valor": "Realtek & Co"},
        {"etiqueta": "", "valor": "Sin red activa"},
    ]


def test_ficha_de_un_equipo_escaneado(api, lote_con_equipos):
    r = ficha(api, "sn1")  # sin importar mayúsculas
    assert r["serial"] == "SN1"
    assert r["tipo"] == "Notebook"
    assert r["sin_hardware"] is False
    assert r["datos"]["modelo"] == "HP EliteBook 840"
    assert r["datos"]["sn_win"] == "AAAAA-BBBBB"
    # PENDIENTE y "Sin observaciones" se muestran vacíos para editar.
    assert r["datos"]["sn_transf"] == ""
    assert r["datos"]["obs"] == ""
    assert r["fecha"] == "01/01/2026 10:00"
    assert r["hardware"] == {
        "host": "PC",
        "cpu": "Intel i5",
        "bateria": "90%",
        "ram": ["8GB|3200|PC4|Kingston|PN1"],
        "discos": [{"desc": "SSD 256GB", "serial": "DISCO-01"}],
        "red": [],
    }


def test_equipo_leido_por_celular_ofrece_la_revision_en_ok(api, lote_con_equipos):
    registrar_equipo(lote_con_equipos, "MON12345", "Monitor")
    r = ficha(api, "MON12345")
    assert r["sin_hardware"] is True
    assert r["revisado"] is False
    assert [c["nombre"] for c in r["componentes"]] == COMPONENTES
    assert all(c["estado"] == "OK" for c in r["componentes"])
    # Sin las filas de respaldo ("RAM No detectada"): vacío para cargarlo.
    assert r["hardware"] == {"host": "", "cpu": "", "bateria": "", "ram": [], "discos": [], "red": []}


def test_equipo_inexistente_es_404(api, lote_con_equipos):
    codigo, r = pedir(api, "/api/v1/equipo", {"lote": LOTE, "serial": "NOEXISTE"})
    assert (codigo, r["error"]) == (404, "equipo")


def test_editar_reescribe_el_json_y_regenera_el_html(api, lote_con_equipos):
    codigo, r = editar(
        api,
        {"modelo": "HP ProBook 450 G5", "sn_win": "XXXXX-YYYYY", "obs": "Rayón en tapa"},
    )
    assert codigo == 200, r
    assert r["datos"]["modelo"] == "HP ProBook 450 G5"

    jdata = json_equipo(lote_con_equipos, "SN1")
    assert jdata["MODELO"] == "HP ProBook 450 G5"
    assert jdata["OBS"] == "Rayón en tapa"
    # El HTML lee DATA primero: se actualiza a la par.
    assert jdata["DATA"]["model"] == "HP ProBook 450 G5"
    assert jdata["DATA"]["key"] == "XXXXX-YYYYY"
    contenido = html_lote(lote_con_equipos)
    assert "HP ProBook 450 G5" in contenido and "XXXXX-YYYYY" in contenido
    assert "Rayón en tapa" in contenido
    # Lo que no se tocó queda igual, y el otro equipo también.
    assert jdata["SN_Transf"] == "PENDIENTE"
    assert json_equipo(lote_con_equipos, "SN2")["MODELO"] == "HP EliteBook 840"
    assert api.eventos[-1]["respuesta"] == {"estado": "editado", "campos": ["modelo", "obs", "sn_win"]}


def test_vaciar_un_campo_lo_devuelve_a_pendiente(api, lote_con_equipos):
    assert editar(api, {"sn_transf": "TR-1", "obs": "algo"})[0] == 200
    assert editar(api, {"sn_transf": "  ", "obs": ""})[0] == 200
    jdata = json_equipo(lote_con_equipos, "SN1")
    assert jdata["SN_Transf"] == "PENDIENTE"
    assert jdata["OBS"] == "Sin observaciones"


def test_office_y_su_key(api, lote_con_equipos):
    assert editar(api, {"office": "2024", "sn_app": "KEY-123"})[0] == 200
    jdata = json_equipo(lote_con_equipos, "SN1")
    assert (jdata["OFFICE"], jdata["SN_APP"]) == ("Office 2024", "KEY-123")
    assert "(Key: KEY-123)" in html_lote(lote_con_equipos)
    assert ficha(api)["datos"]["office"] == "Office 2024"

    assert editar(api, {"office": "No"})[0] == 200
    assert json_equipo(lote_con_equipos, "SN1")["OFFICE"] == "No"
    codigo, r = editar(api, {"office": "1999"})
    assert (codigo, r["error"]) == (400, "dato")


def test_componentes_marcan_fallas(api, lote_con_equipos):
    componentes = [{"nombre": n, "estado": "OK", "obs": "se borra"} for n in COMPONENTES]
    componentes[1] = {"nombre": "Pantalla", "estado": "MALO", "obs": "Píxeles muertos"}
    assert editar(api, {"componentes": componentes})[0] == 200
    jdata = json_equipo(lote_con_equipos, "SN1")
    assert jdata["TIENE_FALLAS"] is True
    assert jdata["DETALLE_COMPONENTES"][1]["obs"] == "Píxeles muertos"
    assert jdata["DETALLE_COMPONENTES"][0]["obs"] == ""  # en OK no lleva observación
    assert "Pantalla (MALO)" in html_lote(lote_con_equipos)

    componentes[1]["estado"] = "SUPER"
    assert editar(api, {"componentes": componentes})[0] == 400


def test_transformador_repetido_en_el_lote(api, lote_con_equipos):
    assert editar(api, {"sn_transf": "TR-9"}, serial="SN2")[0] == 200
    codigo, r = editar(api, {"sn_transf": "tr-9"})
    assert (codigo, r["error"]) == (409, "duplicado")
    assert "SN2" in r["mensaje"]


def test_no_pisa_cambios_hechos_despues_de_abrir_la_ficha(api, lote_con_equipos):
    vieja = ficha(api)["version"]
    assert editar(api, {"obs": "primero"})[0] == 200
    codigo, r = editar(api, {"obs": "segundo"}, version=vieja)
    assert (codigo, r["error"]) == (409, "cambiado")
    assert json_equipo(lote_con_equipos, "SN1")["OBS"] == "primero"


def test_no_edita_lo_que_no_corresponde(api, lote_con_equipos):
    for cambios in (
        {},
        {"serial": "OTRO"},
        {"cpu": "i9"},  # va dentro de 'hardware'
        {"modelo": ""},
        {"obs": 5},
        {"hardware": "x"},
        {"hardware": {"ram": "8GB"}},
        {"hardware": {"discos": ["SSD"]}},
    ):
        codigo, r = editar(api, cambios)
        assert (codigo, r["error"]) == (400, "dato"), cambios
    codigo, _ = pedir(
        api, "/api/v1/equipo/editar", {"lote": LOTE, "serial": "SN1", "cambios": {"obs": "x"}}
    )
    assert codigo == 400  # sin versión


def test_editar_deja_la_ot_pendiente_de_envio(api, lote_con_equipos):
    marcador = lotes.os.path.join(lote_con_equipos["ruta"], lotes.MARCADOR_ENVIADO)
    open(marcador, "w").close()
    assert editar(api, {"obs": "cambio"})[0] == 200
    assert not lotes.os.path.exists(marcador)


HW = {
    "host": "NB-01",
    "cpu": "Intel i7-8550U",
    "bateria": "80%",
    "ram": ["8GB | 2400 | PC4 | Kingston | KPN1", "8GB | 2400 | PC4 | Micron | MPN2", "  "],
    "discos": [{"desc": "SSD 500GB", "serial": "AB-12/34"}, {"desc": "", "serial": ""}],
    "red": ["Intel Wi-Fi | MAC: 00:11"],
}


def test_editar_hardware_rearma_las_filas_como_el_escaneo(api, lote_con_equipos):
    codigo, r = editar(api, {"hardware": HW})
    assert codigo == 200, r
    # Lo vacío se descarta; el serial del disco queda normalizado como en el escaneo.
    assert r["hardware"]["ram"] == HW["ram"][:2]
    assert r["hardware"]["discos"] == [{"desc": "SSD 500GB", "serial": "AB-12/34"}]

    jdata = json_equipo(lote_con_equipos, "SN1")
    data = jdata["DATA"]
    assert data["cpu"] == "Intel i7-8550U" and data["host"] == "NB-01" and data["Battery"] == "80%"
    assert data["ram_html"].count("<th>Módulo RAM</th>") == 2
    assert (data["Manufacturer"], data["Partnumber"]) == ("Kingston / Micron", "KPN1 / MPN2")
    assert data["disk_serials"] == ["AB1234"]
    assert jdata["SN_HDD"] == "AB1234"
    assert "Intel Wi-Fi" in data["net_rows"] and data["net_rows"] == data["net_html"]

    contenido = html_lote(lote_con_equipos)
    for texto in ("Intel i7-8550U", "MPN2", "SSD 500GB", "AB1234", "Intel Wi-Fi", "80%"):
        assert texto in contenido, texto
    # El FUSIONADO sigue a los discos.
    with open(lotes.ruta_fusionado(lote_con_equipos), encoding="utf-8") as f:
        fusionado = {e["SERIAL"]: e for e in json.load(f)}
    assert fusionado["SN1"]["SN_HDD"] == "AB1234"


def test_vaciar_el_hardware(api, lote_con_equipos):
    vacio = {"host": "", "cpu": "", "bateria": "", "ram": [], "discos": [], "red": []}
    assert editar(api, {"hardware": vacio})[0] == 200
    jdata = json_equipo(lote_con_equipos, "SN1")
    assert "cpu" not in jdata["DATA"]
    assert jdata["SN_HDD"] == "PENDIENTE"
    contenido = html_lote(lote_con_equipos)
    assert "No detectada" in contenido and "Sin red activa" in contenido


def test_hardware_de_un_json_viejo_sale_de_las_filas_html(api, lote_con_equipos):
    """Los JSON viejos no traen disk_raw ni net_raw: solo las filas del reporte."""
    ruta = lotes.ruta_json_equipo(lote_con_equipos, "SN1")
    with open(ruta, encoding="utf-8") as f:
        jdata = json.load(f)
    for clave in ("ram_raw", "disk_raw", "net_raw", "net_html"):
        jdata["DATA"].pop(clave, None)
    jdata["DATA"]["net_rows"] = (
        "<tr><td>Red Activa</td><td><span class='net-tag'>Realtek | IP: 1.2.3.4</span></td></tr>"
    )
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f)

    hw = ficha(api)["hardware"]
    assert hw["ram"] == ["8GB|3200|PC4|Kingston|PN1"]
    assert hw["discos"] == [{"desc": "SSD 256GB", "serial": "DISCO01"}]
    assert hw["red"] == ["Realtek | IP: 1.2.3.4"]


def test_un_equipo_leido_por_celular_puede_cargar_su_hardware(api, lote_con_equipos):
    registrar_equipo(lote_con_equipos, "NB777777", "Notebook")
    assert editar(api, {"hardware": HW}, serial="NB777777")[0] == 200
    assert "Intel i7-8550U" in html_lote(lote_con_equipos)
    r = ficha(api, "NB777777")
    assert r["sin_hardware"] is False
    assert r["hardware"]["cpu"] == "Intel i7-8550U"
