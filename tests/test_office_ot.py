"""Office por OT: la OT dice con qué Office va y se elige qué caja va con cada notebook."""

import itertools
import json

import pytest

from inventario.nucleo import escaneos, gestion_lote, licencias_office as L, lotes, office_ot

from conftest import datos_equipo
from test_sincronizacion import Servidor, json_remoto, nombre

# Keys inventadas: tienen la forma de una key, nada más.
_numeros = itertools.count(1)


def key():
    return f"AAAAA-BBBBB-CCCCC-DDDDD-{next(_numeros):05d}"


def cargar_cajas(*cajas, version="2016"):
    """Cajas disponibles: (código, ubicación)."""
    licencias = []
    for caja, ubicacion in cajas:
        lic = L._licencia_vacia(caja, key(), version)
        lic["ubicacion"] = ubicacion
        licencias.append(lic)
    assert L.importar(licencias)["nuevas"] == len(cajas)


@pytest.fixture
def ot_office(carpeta):
    """OT de entrega que va con Office 2016, con tres notebooks y un monitor."""
    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["office"] = "2016"
    lote = lotes.abrir_lote(lote)
    for serial in ("SN1", "SN2", "SN3"):
        guardar(lote, serial)
    escaneos.registrar_equipo(lote, "MON12345", tipo="Monitor")
    return lote


_segundos = itertools.count(10)


def guardar(lote, serial, **office):
    lotes.guardar_equipo_general(
        lote, datos_equipo(serial), "", office.get("tiene", False),
        office.get("key", ""), "2016", [],
    )
    # Un segundo distinto por equipo, como en la vida real: si no, el orden
    # de escaneo empata y queda al azar.
    ruta = lotes.ruta_json_equipo(lote, serial)
    with open(ruta, encoding="utf-8") as f:
        jdata = json.load(f)
    jdata["ESCANEADO"] = f"2026-11-03T10:00:{next(_segundos):02d}"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f)


def equipo(lote, serial):
    return next(j for j in lotes.leer_equipos_lote(lote) if j["SERIAL"] == serial)


def filas(lote, codigos):
    """Lo que manda la pantalla: cada notebook con el código escrito en su fila."""
    return [(r, j, codigos.get(j["SERIAL"], "")) for r, j in office_ot.equipos(lote)]


def test_disponibles_por_ubicacion_y_codigo(carpeta):
    cargar_cajas(("C-30", "2"), ("C-20", "10"), ("C-10", "2"), ("C-05", ""))
    cargar_cajas(("D-1", "1"), version="2013")
    assert [l["caja"] for l in L.listar_disponibles("2016")] == ["C-10", "C-30", "C-20", "C-05"]
    assert L.disponibles("2016") == 4


def test_equipos_son_los_notebooks_en_orden_de_escaneo(ot_office):
    assert [j["SERIAL"] for _r, j in office_ot.equipos(ot_office)] == ["SN1", "SN2", "SN3"]


def test_llegar_a_la_ot_no_asigna_nada(ot_office):
    cargar_cajas(("C-1", "1"))
    servidor = Servidor(lotes.hacer_lote("Entrega", "ACME", "553"), {nombre("CL1"): json_remoto("CL1")})
    servidor.vuelta()
    assert "OFFICE_CAJA" not in equipo(ot_office, "CL1")
    assert L.disponibles("2016") == 1
    assert office_ot.estado(ot_office) == {
        "version": "2016", "con_office": 0, "faltan": 4, "disponibles": 1,
    }


def test_guardar_las_cajas_elegidas(ot_office):
    cargar_cajas(("C-1", "1"), ("C-2", "1"), ("C-3", "1"))
    # Se elige a mano: SN1 se lleva la C-3 y SN2 la C-1, por su código de caja.
    assert office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-3", "SN2": "c-1"})) == 2

    sn1 = equipo(ot_office, "SN1")
    assert (sn1["OFFICE"], sn1["OFFICE_CAJA"], sn1["SN_APP"]) == (
        "Office 2016", "C-3", L.buscar("C-3")["clave"]
    )
    assert equipo(ot_office, "SN3").get("OFFICE_CAJA") is None
    lic = L.buscar("C-3")
    assert (lic["serial"], lic["cliente"], lic["documento"]) == ("SN1", "ACME", "OT-553")

    # El HTML y el FUSIONADO salen con la key.
    with open(lotes.ruta_html_lote(ot_office), encoding="utf-8") as f:
        assert f"(Key: {sn1['SN_APP']}) · Caja C-3" in f.read()
    with open(lotes.ruta_fusionado(ot_office), encoding="utf-8") as f:
        fusionado = {e["SERIAL"]: e for e in json.load(f)}
    assert fusionado["SN1"]["SN_APP"] == sn1["SN_APP"]

    assert "1 sin caja" in office_ot.texto_estado(ot_office)
    # Guardar lo mismo otra vez no cambia nada.
    assert office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-3", "SN2": "C-1"})) == 0


def test_intercambiar_y_vaciar(ot_office):
    cargar_cajas(("C-1", "1"), ("C-2", "1"))
    office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-1", "SN2": "C-2"}))
    # Intercambiar dos cajas entre equipos de la OT vale.
    office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-2", "SN2": "C-1"}))
    assert (equipo(ot_office, "SN1")["OFFICE_CAJA"], equipo(ot_office, "SN2")["OFFICE_CAJA"]) == (
        "C-2", "C-1"
    )
    # Vaciar la fila devuelve la caja y deja al equipo esperando la suya.
    office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-2"}))
    sn2 = equipo(ot_office, "SN2")
    assert ("OFFICE_CAJA" not in sn2, sn2["SN_APP"], sn2["OFFICE"]) == (True, "PENDIENTE", "Office 2016")
    assert L.buscar("C-1")["estado"] == "disponible"


def test_todo_o_nada(ot_office):
    cargar_cajas(("C-1", "1"), ("C-2", "1"))
    L.asignar("C-2", "SN-DE-AFUERA")
    with pytest.raises(L.ErrorLicencia) as e:
        office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-1", "SN2": "C-2", "SN3": "NO-EXISTE"}))
    assert "SN2: la caja C-2 es de otro equipo" in e.value.mensaje
    assert "SN3: el código NO-EXISTE no está en la base" in e.value.mensaje
    # Nada cambió: ni la base ni los JSON.
    assert L.buscar("C-1")["estado"] == "disponible"
    assert "OFFICE_CAJA" not in equipo(ot_office, "SN1")

    with pytest.raises(L.ErrorLicencia, match="SN2: la caja C-1 también está en SN1"):
        office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-1", "SN2": "C-1"}))


def test_respeta_la_key_cargada_a_mano(carpeta):
    cargar_cajas(("C-1", "1"))
    lote = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "1"))
    guardar(lote, "SN1", tiene=True, key="ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ")
    assert not office_ot.necesita_office(equipo(lote, "SN1"))
    assert office_ot.guardar_cajas(lote, filas(lote, {})) == 0
    assert equipo(lote, "SN1")["SN_APP"] == "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ"


def test_revisar_codigo(ot_office):
    cargar_cajas(("C-1", "1"), ("C-2", "1"))
    cargar_cajas(("D-1", "1"), version="2013")
    L.asignar("C-2", "OTRO")
    assert office_ot.revisar_codigo("", "SN1", "2016") == ("", "")
    assert office_ot.revisar_codigo("C-1", "SN1", "2016") == ("ok", "Disponible")
    assert office_ot.revisar_codigo("C-1", "SN1") == ("ok", "Office 2016 · Disponible")
    assert office_ot.revisar_codigo("C-2", "SN1", "2016") == ("aviso", "Hoy es de OTRO")
    assert office_ot.revisar_codigo("D-1", "SN1", "2016") == ("aviso", "Office 2013 (la OT va con 2016)")
    assert office_ot.revisar_codigo("X", "SN1", "2016") == ("error", "No está en la base")


def test_ot_sin_office_o_retiro(carpeta):
    sin = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "1"))
    assert office_ot.version_de(sin) == "" and office_ot.estado(sin) is None
    retiro = lotes.hacer_lote("Retiro", "ACME", "G1")
    retiro["office"] = "2016"
    lotes.abrir_lote(retiro)
    assert office_ot.version_de(retiro) == ""


def test_el_office_de_la_ot_no_se_pierde_al_reabrir(ot_office):
    # Un lote sin el dato (el puntero al activo, la ruta) no lo borra…
    lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G1"))
    assert lotes.office_en_disco(ot_office["ruta"]) == "2016"
    # …pero elegir "Sin Office" sí.
    sin = lotes.hacer_lote("Entrega", "ACME", "553")
    sin["office"] = ""
    lotes.abrir_lote(sin)
    assert lotes.office_en_disco(ot_office["ruta"]) == ""


def test_quitar_el_equipo_libera_su_caja(ot_office):
    cargar_cajas(("C-1", "1"))
    office_ot.guardar_cajas(ot_office, filas(ot_office, {"SN1": "C-1"}))
    gestion_lote.quitar_equipo(ot_office, "SN1")
    assert L.buscar("C-1")["estado"] == "disponible"
    assert "quitado de ACME · OT-553" in L.historial("C-1")[0]["detalle"]
