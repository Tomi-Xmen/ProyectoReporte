"""
Contrato entre la API del PC y la app Android.

android/app/src/test/resources/contrato/respuestas_api.json guarda respuestas
REALES de ApiCelular, una por caso. La app las decodifica en sus tests en
modo estricto (ContratoTest.kt): si el PC manda un campo que la app no
conoce, falla allá. Este test falla acá si la API cambió de forma y el archivo
quedó viejo. Para regenerarlo después de un cambio intencional:

    set REGENERAR_CONTRATO=1 && .venv\\Scripts\\python -m pytest tests/test_contrato_celular.py

y después adaptar los modelos de la app (data/Modelos.kt) hasta que sus
tests pasen.
"""

import json
import os
import re
from pathlib import Path

from inventario.nucleo import lotes
from inventario.nucleo.api_celular import ApiCelular

from conftest import datos_equipo

ARCHIVO = (
    Path(__file__).resolve().parent.parent
    / "android/app/src/test/resources/contrato/respuestas_api.json"
)
LOTE = {"mov": "Entrega", "cliente": "ACME", "numero": "553"}


def _generar():
    """{caso: {"codigo", "cuerpo"}} con respuestas reales sobre un lote armado a mano."""
    lote = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-9"))
    for serial in ("5CD805DVNV", "5CD805ABCD"):
        lotes.guardar_equipo_general(lote, datos_equipo(serial), "", False, "", "2016", [])
    otra = lotes.abrir_lote(lotes.hacer_lote("Retiro", "BETA", "77"))
    lotes.guardar_equipo_general(otra, datos_equipo("ZZ99887"), "", False, "", "2016", [])
    cerrada = lotes.abrir_lote(lotes.hacer_lote("Retiro", "BETA", "10"))
    lotes.cerrar_lote(cerrada)

    reglas = [{"tipo": "Notebook", "nombre": "HP", "re": re.compile("^5CD")}]
    api = ApiCelular(token="tok", reglas=reglas)
    cab = {"authorization": "Bearer tok"}

    def pedir(metodo, ruta, datos=None, cabeceras=cab):
        cuerpo = json.dumps(datos).encode() if datos is not None else b""
        codigo, r = api.atender(metodo, ruta, cabeceras, cuerpo)
        return {"codigo": codigo, "cuerpo": r}

    def escaneo(*textos, **extra):
        lecturas = [
            {"texto": t[0], "formato": t[1]} if isinstance(t, tuple) else {"texto": t}
            for t in textos
        ]
        return pedir("POST", "/api/v1/escaneo", {"lote": LOTE, "lecturas": lecturas, **extra})

    casos = {
        "estado": pedir("GET", "/api/v1/estado"),
        "no_autorizado": pedir("GET", "/api/v1/estado", cabeceras={}),
        "lotes": pedir("GET", "/api/v1/lotes"),
        "clientes": pedir("GET", "/api/v1/clientes"),
        "lote": pedir("POST", "/api/v1/lote", {"lote": LOTE}),
        "lote_inexistente": pedir("POST", "/api/v1/lote", {"lote": {**LOTE, "numero": "999"}}),
        "crear_lote": pedir(
            "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "Gamma", "numero": "Guía 5"}
        ),
        "crear_lote_cerrado": pedir(
            "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "BETA", "numero": "10"}
        ),
        "crear_lote_invalido": pedir(
            "POST", "/api/v1/lotes", {"mov": "Retiro", "cliente": "", "numero": "1"}
        ),
        "escaneo_registrado": escaneo(
            ("7801234567890", "EAN_13"), "S/N: MON12345", esperado="Monitor"
        ),
        "escaneo_ya_estaba": escaneo("5CD805DVNV", esperado="Notebook"),
        "escaneo_en_otra_ot": escaneo("ZZ99887", esperado="Notebook"),
        "escaneo_asignado": escaneo(
            "TR-0001", esperado="Transformador", serial_equipo="5CD805DVNV"
        ),
        "escaneo_asignado_reemplazo": escaneo(
            "TR-0009", esperado="Transformador", serial_equipo="5CD805DVNV"
        ),
        "escaneo_transformador_ya_estaba": escaneo(
            "TR-0009", esperado="Transformador", serial_equipo="5CD805DVNV"
        ),
        "escaneo_duplicado": escaneo(
            "TR-0009", esperado="Transformador", serial_equipo="5CD805ABCD"
        ),
        "escaneo_equipo_no_encontrado": escaneo(
            "TR-0002", esperado="Transformador", serial_equipo="NOEXISTE1"
        ),
        "escaneo_rafaga": escaneo("TR-0003", esperado="Transformador"),
        "escaneo_sin_equipo_pendiente": escaneo("TR-0004", esperado="Transformador"),
        "escaneo_elegir": escaneo("ABC12345", "XYZ98765", esperado="Impresora"),
        "escaneo_sin_serial": escaneo(("7801234567890", "EAN_13"), esperado="Monitor"),
        "escaneo_otro_tipo": escaneo("5CD805XXXX", esperado="Transformador"),
        "escaneo_sin_tipo": escaneo("QWE12345"),
    }

    def equipo(serial):
        return pedir("POST", "/api/v1/equipo", {"lote": LOTE, "serial": serial})

    def editar(serial, version, cambios):
        datos = {"lote": LOTE, "serial": serial, "version": version, "cambios": cambios}
        return pedir("POST", "/api/v1/equipo/editar", datos)

    casos["equipo"] = equipo("5CD805DVNV")
    casos["equipo_sin_hardware"] = equipo("MON12345")
    casos["equipo_inexistente"] = equipo("NOEXISTE1")
    version = casos["equipo"]["cuerpo"]["version"]
    casos["equipo_editado"] = editar("5CD805DVNV", version, {"obs": "Rayón en tapa"})
    casos["equipo_cambiado"] = editar("5CD805DVNV", version, {"obs": "Otra cosa"})
    hw = {
        "host": "NB-01",
        "cpu": "Intel i7",
        "bateria": "80%",
        "ram": ["8GB | 2400 | PC4 | Kingston | KPN1"],
        "discos": [{"desc": "SSD 500GB", "serial": "AB1234"}],
        "red": ["Intel Wi-Fi | MAC: 00:11"],
    }
    casos["equipo_hardware_editado"] = editar(
        "5CD805DVNV", casos["equipo_editado"]["cuerpo"]["version"], {"hardware": hw}
    )
    # TR-0009 ya es de 5CD805DVNV (lo asignaron los escaneos de arriba).
    casos["equipo_transformador_duplicado"] = editar(
        "5CD805ABCD", equipo("5CD805ABCD")["cuerpo"]["version"], {"sn_transf": "TR-0009"}
    )
    return casos


def _forma(valor):
    """Estructura sin valores: claves de los objetos y forma del primer elemento de las listas."""
    if isinstance(valor, dict):
        return {k: _forma(v) for k, v in sorted(valor.items())}
    if isinstance(valor, list):
        return [_forma(valor[0])] if valor else []
    return type(valor).__name__


def test_contrato_con_la_app(carpeta):
    casos = _generar()
    estados = {c["cuerpo"].get("estado") for c in casos.values()}
    # Cada estado que la app sabe manejar tiene su ejemplo.
    assert {
        "registrado", "ya_estaba", "en_otra_ot", "asignado", "duplicado",
        "equipo_no_encontrado", "sin_equipo_pendiente", "elegir", "sin_serial",
        "otro_tipo", "sin_tipo",
    } <= estados

    if os.environ.get("REGENERAR_CONTRATO") == "1":
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVO.write_text(
            json.dumps(casos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    guardados = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    assert set(guardados) == set(casos), "Casos distintos: regenerar el contrato"
    for nombre, caso in casos.items():
        assert caso["codigo"] == guardados[nombre]["codigo"], nombre
        assert _forma(caso["cuerpo"]) == _forma(guardados[nombre]["cuerpo"]), (
            f"La respuesta '{nombre}' cambió de forma: regenerar el contrato "
            "(ver docstring) y adaptar data/Modelos.kt de la app."
        )
