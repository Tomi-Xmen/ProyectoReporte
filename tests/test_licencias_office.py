import csv
import zipfile

import pytest

from inventario.nucleo import activacion_office, licencias_office as L

# Keys inventadas: tienen la forma de una key, nada más.
K1 = "AAAAA-BBBBB-CCCCC-DDDDD-11111"
K2 = "AAAAA-BBBBB-CCCCC-DDDDD-22222"
K3 = "AAAAA-BBBBB-CCCCC-DDDDD-33333"
K4 = "AAAAA-BBBBB-CCCCC-DDDDD-44444"

ENCABEZADO = [
    "N°", "FECHA", "MODELO", "SERIAL", "LICENCIA", "CODIGO CAJA", "LICENCIA COD. BARRA",
    "ESTADO", "REASIGNACION", "FECHA EVENTO", "GUIA", "CLIENTE", "Rental", "Columna1",
    "CAJA", "PRODUCTO", "",
]


def maestra():
    """Filas con la forma de la planilla 'OFFICE ARRIENDA'."""
    return [
        ENCABEZADO,
        ["1", "04/08/2015", "", "", K1, "88880811420680", "1000000798904", "DISPONIBLE", "",
         "11/03/2026", "3160", "", "0", "1", "1", "Office 2013 Hogar y Empresas", ""],
        ["5", "04/08/2015", "4300 SFF", "MXL0DEMO01", K2, "88880811759930", "1000000798657",
         "ASIGNADA", "MXL0DEMO02 => MXL0DEMO01", "", "", "CLIENTE DEMO", "0", "1", "2",
         "Office 2016 Hogar y Empresas", ""],
        ["", "02/26/2026", "450 G9", "5CD0DEMO02", K3, "A1B-12345-6789",
         "cuenta-demo@example.com", "DISPONIBLE", "", "", "", "", "", "", "",
         "Office Home and Business 2021", ""],
        ["8", "04/08/2015", "", "", K4, "88880811759927", "1000000798727", "DESHABILITADA",
         "", "11/10/2023", "", "", "0", "1", "1", "Office 2013 Hogar y Empresas",
         "POSIBLEMENTE DADO DE BAJA"],
    ]


@pytest.fixture
def base(carpeta):
    licencias, invalidas = L.interpretar_filas(maestra())
    assert invalidas == []
    L.importar(licencias)
    return carpeta


def test_normalizaciones():
    assert L.normalizar_clave("aaaaa bbbbb ccccc ddddd 11111") == K1
    assert L.normalizar_clave("AAAAA-BBBBB") == ""
    assert L.normalizar_codigo(" 1.962630798904E+12 ") == "1000000798904"
    assert L.normalizar_codigo("123.0") == "123"
    assert L.normalizar_version("Office Home and Business 2021") == "2021"
    assert L.normalizar_version("Office 2016 Hogar y Empresas") == "2016"
    assert L.normalizar_version("Microsoft 365") == "365"
    assert L.normalizar_version("Office") == ""
    assert L.enmascarar(K1) == "•••••-•••••-•••••-•••••-11111"


def test_interpreta_la_planilla_maestra():
    licencias, invalidas = L.interpretar_filas(maestra())
    assert invalidas == []
    por_caja = {l["caja"]: l for l in licencias}

    libre = por_caja["88880811420680"]
    assert (libre["estado"], libre["version"], libre["codigo_barra"]) == (
        "disponible", "2013", "1000000798904"
    )
    assert libre["ubicacion"] == "1" and libre["anterior"] == "guía 3160 · 11/03/2026"

    asignada = por_caja["88880811759930"]
    assert (asignada["estado"], asignada["serial"], asignada["cliente"]) == (
        "asignada", "MXL0DEMO01", "CLIENTE DEMO"
    )
    assert "MXL0DEMO02 => MXL0DEMO01" in asignada["nota"]

    # En las 2021/2024 la segunda columna es la cuenta, no un código de barras.
    cuenta = por_caja["A1B-12345-6789"]
    assert (cuenta["cuenta"], cuenta["codigo_barra"]) == ("cuenta-demo@example.com", "")

    deshab = por_caja["88880811759927"]
    assert deshab["estado"] == "deshabilitada" and deshab["nota"] == "POSIBLEMENTE DADO DE BAJA"


def test_interpreta_lista_sin_encabezado_y_reporta_lo_malo():
    filas = [
        ["CAJA-1", K1, "Office 2016"],
        [K2, "CAJA-2"],
        ["CAJA-3", "no es una key"],
        ["", ""],
        ["CAJA-1", K3],
    ]
    licencias, invalidas = L.interpretar_filas(filas, version_por_defecto="2013")
    assert [(l["caja"], l["version"]) for l in licencias] == [("CAJA-1", "2016"), ("CAJA-2", "2013")]
    assert all(l["estado"] == "disponible" for l in licencias)
    assert [n for n, _ in invalidas] == [3, 5]


def test_lee_xlsx_y_csv(tmp_path):
    ruta_csv = tmp_path / "lic.csv"
    with open(ruta_csv, "w", encoding="cp1252", newline="") as f:
        csv.writer(f, delimiter=";").writerows(maestra())
    assert L.leer_planilla(str(ruta_csv))[2][3] == "MXL0DEMO01"

    # Un .xlsx mínimo: strings compartidos, número y celda saltada.
    ruta_xlsx = tmp_path / "lic.xlsx"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(ruta_xlsx, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}><si><t>CODIGO CAJA</t></si><si><t>{K1}</t></si></sst>")
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet {ns}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
            '<row r="2"><c r="A2"><v>88880811420680</v></c><c r="C2" t="s"><v>1</v></c></row>'
            "</sheetData></worksheet>",
        )
    assert L.leer_planilla(str(ruta_xlsx)) == [["CODIGO CAJA"], ["88880811420680", "", K1]]

    with pytest.raises(L.ErrorLicencia, match="xlsx"):
        L.leer_planilla(str(tmp_path / "viejo.xls"))


def test_importar_no_pisa_y_resume(base):
    assert L.resumen() == {
        "2013": {"disponible": 1, "asignada": 0, "deshabilitada": 1},
        "2016": {"disponible": 0, "asignada": 1, "deshabilitada": 0},
        "2021": {"disponible": 1, "asignada": 0, "deshabilitada": 0},
    }
    # La misma planilla de nuevo no cambia nada; una caja con otra key es conflicto.
    otra = [{**L._licencia_vacia("88880811420680", "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ", "2013")}]
    licencias, _ = L.interpretar_filas(maestra())
    assert L.importar(licencias) == {"nuevas": 0, "repetidas": 4, "conflictos": []}
    assert L.importar(otra)["conflictos"] == [
        ("88880811420680", "la caja ya está en la base con otra key")
    ]
    # Lo que la planilla recordaba de una libre queda en el historial.
    assert any("guía 3160" in e["detalle"] for e in L.historial("88880811420680"))


def test_busca_por_cualquiera_de_los_codigos(base):
    assert L.buscar("88880811420680")["clave"] == K1
    assert L.buscar("1000000798904")["clave"] == K1
    assert L.buscar("a1b1234567 89")["clave"] == K3  # sin guiones ni mayúsculas
    assert L.buscar("NO-EXISTE") is None


def test_asignar_es_exclusivo_y_reemplazar_libera(base):
    lic = L.asignar("1000000798904", "SN-NUEVO", modelo="HP 440", cliente="ACME", documento="OT-553")
    assert (lic["caja"], lic["estado"], lic["serial"]) == ("88880811420680", "asignada", "SN-NUEVO")
    assert L.caja_de_equipo("SN-NUEVO")["caja"] == "88880811420680"
    # Repetir con el mismo equipo no cambia nada.
    assert L.asignar("88880811420680", "SN-NUEVO")["documento"] == "OT-553"

    with pytest.raises(L.ErrorLicencia) as e:
        L.asignar("88880811420680", "OTRO-SN")
    assert e.value.codigo == "asignada" and "SN-NUEVO" in e.value.mensaje
    with pytest.raises(L.ErrorLicencia) as e:
        L.asignar("88880811759927", "OTRO-SN")
    assert e.value.codigo == "deshabilitada"
    with pytest.raises(L.ErrorLicencia) as e:
        L.asignar("NO-EXISTE", "OTRO-SN")
    assert e.value.codigo == "no_existe"

    # El equipo ya tiene una caja: pide confirmación, y reemplazar libera la vieja.
    with pytest.raises(L.ErrorLicencia) as e:
        L.asignar("A1B-12345-6789", "SN-NUEVO")
    assert e.value.codigo == "otra_caja"
    L.asignar("A1B-12345-6789", "SN-NUEVO", reemplazar=True)
    assert L.buscar("88880811420680")["estado"] == "disponible"
    assert L.caja_de_equipo("SN-NUEVO")["caja"] == "A1B-12345-6789"


def test_liberar_y_activacion_quedan_en_historial(base):
    L.asignar("88880811420680", "SN1", cliente="ACME", documento="OT-1")
    L.registrar_activacion("88880811420680", L.ACTIVADA, "Office activado.")
    assert L.buscar("88880811420680")["activacion"] == "activada"
    L.liberar("88880811420680", "retiro ACME GUIA-9")
    lic = L.buscar("88880811420680")
    assert (lic["estado"], lic["serial"], lic["activacion"]) == ("disponible", "", "")
    eventos = [e["evento"] for e in L.historial("88880811420680")]
    assert eventos[:3] == ["liberada", "activacion", "asignada"]
    assert "SN SN1" in L.historial("88880811420680")[0]["detalle"]


def test_exportar_csv(base, tmp_path):
    ruta = tmp_path / "export.csv"
    assert L.exportar_csv(str(ruta)) == 4
    with open(ruta, encoding="utf-8-sig") as f:
        filas = list(csv.reader(f, delimiter=";"))
    assert filas[0][:4] == ["CODIGO CAJA", "COD. BARRA", "CUENTA", "LICENCIA"]
    assert {f[3] for f in filas[1:]} == {K1, K2, K3, K4}


def test_listar_filtra(base):
    assert [l["caja"] for l in L.listar("cliente demo")] == ["88880811759930"]
    assert len(L.listar()) == 4


# ─────────────────────────────────────────────────────────
#  Activación (sin Windows: se prueba lo que no depende de él)
# ─────────────────────────────────────────────────────────
SALIDA_OK = """===INPKEY===
---Processing--------------------------
<Product key installation successful>
---Exiting-----------------------------
===ACT===
---Processing--------------------------
<Product activation successful>
---Exiting-----------------------------
"""

SALIDA_SIN_RED = """===INPKEY===
<Product key installation successful>
===ACT===
ERROR CODE: 0x8007232B
ERROR DESCRIPTION: The Software Licensing Service reported that DNS name does not exist.
"""

SALIDA_KEY_MALA = """===INPKEY===
ERROR CODE: 0xC004F069
ERROR DESCRIPTION: The Software Licensing Service reported that the product SKU is not found.
===ACT===
"""


def test_interpretar_salida_de_ospp():
    assert activacion_office.interpretar(SALIDA_OK) == ("activada", "Office activado.")
    estado, detalle = activacion_office.interpretar(SALIDA_SIN_RED)
    assert estado == "cargada" and "DNS name does not exist" in detalle
    estado, detalle = activacion_office.interpretar(SALIDA_KEY_MALA)
    assert estado == "error" and "SKU is not found" in detalle


def test_script_cmd_carga_y_activa_en_un_solo_paso():
    script = activacion_office.script_cmd(r"C:\Office16\OSPP.VBS", K1, r"C:\t\salida.txt")
    assert f'/inpkey:{K1}' in script and "/act" in script
    assert script.rstrip().endswith(r') > "C:\t\salida.txt" 2>&1')
    assert "/act" not in activacion_office.script_cmd("o", K1, "s", activar=False)


def test_solo_2013_2016_se_activan_por_key():
    assert activacion_office.aplica("2013") and activacion_office.aplica("2016")
    assert not activacion_office.aplica("2021") and not activacion_office.aplica("2024")
    with pytest.raises(activacion_office.ErrorActivacion, match="no se activa por key"):
        activacion_office.cargar_y_activar(K1, "2021")


def test_ospp_de_una_instalacion_click_to_run(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    assert not activacion_office.office_instalado("2016")
    ospp = tmp_path / "Microsoft Office" / "root" / "Office16" / "OSPP.VBS"
    ospp.parent.mkdir(parents=True)
    ospp.write_text("")
    assert activacion_office.ruta_ospp("2016") == str(ospp)
    assert not activacion_office.office_instalado("2013")
