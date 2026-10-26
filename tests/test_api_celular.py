import json

import pytest

from inventario.nucleo import lotes
from inventario.nucleo.api_celular import ApiCelular, es_red_local

LOTE = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}


@pytest.fixture
def api():
    eventos = []
    api = ApiCelular(token="secreto", reglas=[], al_evento=eventos.append)
    api.eventos = eventos
    return api


def pedir(api, metodo, ruta, datos=None, token="secreto"):
    cabeceras = {"authorization": f"Bearer {token}"} if token else {}
    cuerpo = json.dumps(datos).encode() if datos is not None else b""
    return api.atender(metodo, ruta, cabeceras, cuerpo)


def escanear(api, *textos, **extra):
    """Cada lectura es un texto o un par (texto, formato de ML Kit)."""
    lecturas = [
        {"texto": t[0], "formato": t[1]} if isinstance(t, tuple) else {"texto": t}
        for t in textos
    ]
    datos = {"lote": LOTE, "lecturas": lecturas, **extra}
    codigo, r = pedir(api, "POST", "/api/v1/escaneo", datos)
    assert codigo == 200, r
    return r


def test_sin_token_o_token_viejo_es_401(api):
    assert pedir(api, "GET", "/api/v1/estado", token=None)[0] == 401
    assert pedir(api, "GET", "/api/v1/estado", token="viejo")[0] == 401
    assert pedir(api, "GET", "/api/v1/estado") == (200, {"app": "inventario-arrienda", "v": 1})


def test_rutas_y_errores_de_formato(api):
    assert pedir(api, "GET", "/api/v1/nada")[0] == 404
    assert pedir(api, "GET", "/otra/cosa")[0] == 404
    assert pedir(api, "GET", "/api/v1/escaneo")[0] == 405
    codigo, r = api.atender("POST", "/api/v1/lote", {"authorization": "Bearer secreto"}, b"{no")
    assert (codigo, r["error"]) == (400, "json_invalido")
    assert pedir(api, "POST", "/api/v1/lote", {"lote": "x"})[0] == 400


def test_emparejamiento(api):
    datos = json.loads(api.texto_qr("192.168.1.20", 8765))
    assert datos == {
        "app": "inventario-arrienda",
        "v": 1,
        "url": "http://192.168.1.20:8765",
        "token": "secreto",
    }
    # Cada sesión, un token distinto.
    assert ApiCelular(reglas=[]).token != ApiCelular(reglas=[]).token


def test_lista_lotes_sin_rutas_del_pc(api, lote_con_equipos):
    codigo, r = pedir(api, "GET", "/api/v1/lotes")
    assert codigo == 200
    (lote,) = r["lotes"]
    assert lote["numero"] == "553" and lote["equipos"] == 2 and lote["numero_sec"] == "G-9"
    assert "ruta" not in lote
    assert pedir(api, "GET", "/api/v1/clientes")[1] == {"clientes": ["ACME"]}


def test_crear_lote_y_reabrir_solo_si_se_pide(api, carpeta):
    codigo, r = pedir(api, "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "beta spa", "numero": "Guía 88"})
    assert codigo == 200 and (r["cliente"], r["numero"], r["equipos"]) == ("BETA_SPA", "88", [])
    # El celular no cambia la OT activa del PC.
    assert lotes.cargar_lote_activo() is None

    codigo, r = pedir(api, "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "", "numero": "1"})
    assert (codigo, r["titulo"]) == (400, "Falta el cliente")

    lotes.cerrar_lote(lotes.hacer_lote("Retiro", "BETA_SPA", "88"))
    codigo, r = pedir(api, "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "BETA SPA", "numero": "88"})
    assert (codigo, r["error"]) == (409, "cerrado")
    codigo, _ = pedir(
        api, "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "BETA SPA", "numero": "88", "reabrir": True}
    )
    assert codigo == 200 and not lotes.esta_cerrado(lotes.hacer_lote("Retiro", "BETA_SPA", "88")["ruta"])


def test_lote_cerrado_o_inexistente(api, lote_con_equipos):
    otro = {**LOTE, "numero": "999"}
    assert pedir(api, "POST", "/api/v1/lote", {"lote": otro})[0] == 404
    lotes.cerrar_lote(lote_con_equipos)
    codigo, r = pedir(api, "POST", "/api/v1/lote", {"lote": LOTE})
    assert (codigo, r["titulo"]) == (409, "Lote cerrado")


def test_escanear_equipo_y_su_transformador(api, lote_con_equipos):
    r = escanear(api, ("7801234567890", "EAN_13"), "S/N: MON12345", esperado="Monitor")
    assert (r["estado"], r["serial"], r["tipo"]) == ("registrado", "MON12345", "Monitor")
    assert len(r["descartes"]) == 1  # el EAN de la caja

    r = escanear(api, "TR-0001", esperado="Transformador", serial_equipo="SN1")
    assert (r["estado"], r["equipo"]) == ("asignado", "SN1")

    _, estado = pedir(api, "POST", "/api/v1/lote", {"lote": LOTE})
    por_serial = {e["serial"]: e for e in estado["equipos"]}
    assert por_serial["SN1"]["sn_transf"] == "TR-0001"
    assert por_serial["MON12345"]["sin_hardware"]

    assert [e["valor"] for e in api.eventos] == ["MON12345", "TR-0001"]


def test_reintento_con_el_mismo_id_no_duplica(api, lote_con_equipos):
    primera = escanear(api, "ABC12345", esperado="Notebook", id="uuid-1")
    otra_vez = escanear(api, "ABC12345", esperado="Notebook", id="uuid-1")
    assert primera["estado"] == otra_vez["estado"] == "registrado"
    # Sin id, la segunda lectura es una lectura nueva: el equipo ya estaba.
    assert escanear(api, "ABC12345", esperado="Notebook")["estado"] == "ya_estaba"
    assert len(api.eventos) == 2


def test_elegir_sin_serial_y_sin_tipo(api, lote_con_equipos):
    r = escanear(api, "ABC12345", "XYZ98765", esperado="Notebook")
    assert r["estado"] == "elegir" and set(r["candidatos"]) == {"ABC12345", "XYZ98765"}

    r = escanear(api, ("7801234567890", "EAN_13"))
    assert r["estado"] == "sin_serial" and r["descartes"]

    assert escanear(api, "ABC12345")["estado"] == "sin_tipo"
    assert lotes.contar_equipos(lote_con_equipos["ruta"]) == 2


def test_otro_tipo_y_tipo_elegido_a_mano(lote_con_equipos):
    reglas = [{"tipo": "Notebook", "nombre": "HP", "re": __import__("re").compile("^5CD")}]
    api = ApiCelular(token="secreto", reglas=reglas)
    r = escanear(api, "5CD805DVNV", esperado="Transformador")
    assert (r["estado"], r["tipo"], r["esperado"]) == ("otro_tipo", "Notebook", "Transformador")

    # El usuario confirma que sí es un transformador: las reglas no mandan.
    r = escanear(api, "5CD805DVNV", tipo="Transformador", serial_equipo="SN1")
    assert r["estado"] == "asignado"


def test_datos_invalidos_del_escaneo(api, lote_con_equipos):
    for datos in [
        {"lote": LOTE},
        {"lote": LOTE, "lecturas": []},
        {"lote": LOTE, "lecturas": [{"formato": "QR_CODE"}]},
        {"lote": LOTE, "lecturas": [{"texto": "ABC12345"}], "esperado": "Tostadora"},
        {"lecturas": [{"texto": "ABC12345"}]},
    ]:
        assert pedir(api, "POST", "/api/v1/escaneo", datos)[0] == 400


def test_un_error_interno_no_revienta(api, lote_con_equipos, monkeypatch):
    from inventario.nucleo import api_celular

    def explota(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(api_celular, "registrar_equipo", explota)
    codigo, r = pedir(
        api, "POST", "/api/v1/escaneo",
        {"lote": LOTE, "lecturas": [{"texto": "ABC12345"}], "esperado": "Notebook"},
    )
    assert (codigo, r["mensaje"]) == (500, "disco lleno")


@pytest.mark.parametrize(
    "ip, local",
    [
        ("127.0.0.1", True),
        ("192.168.1.50", True),
        ("10.0.0.7", True),
        ("172.20.1.1", True),
        ("::ffff:192.168.1.50", True),
        ("8.8.8.8", False),
        ("200.1.2.3", False),
        ("no-es-ip", False),
    ],
)
def test_es_red_local(ip, local):
    assert es_red_local(ip) is local


def test_cargadores_en_borrador_y_guardar_con_boton(api, lote_con_equipos):
    lote = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}
    codigo, r = pedir(api, "POST", "/api/v1/escaneo", {
        "lote": lote, "lecturas": [{"texto": "TR-0001"}], "esperado": "Transformador", "borrador": True,
    })
    assert (codigo, r["estado"], r["sn_transf"]) == (200, "propuesto", "TR-0001")

    codigo, r = pedir(api, "POST", "/api/v1/lote", {"lote": lote})
    assert all(e["sn_transf"] is None for e in r["equipos"])  # el borrador no escribió

    codigo, r = pedir(api, "POST", "/api/v1/cargadores", {
        "lote": lote, "pares": [{"serial": "SN1", "sn_transf": "TR-0001"}],
    })
    assert (codigo, r["estado"], r["guardados"]) == (
        200, "guardado", [{"serial": "SN1", "sn_transf": "TR-0001"}],
    )
    codigo, r = pedir(api, "POST", "/api/v1/lote", {"lote": lote})
    assert {e["serial"]: e["sn_transf"] for e in r["equipos"]}["SN1"] == "TR-0001"
