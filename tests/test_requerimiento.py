import pytest

from inventario.nucleo import lotes, requerimiento

from conftest import datos_equipo


def equipo(cpu="Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz", ram=None, discos=None):
    data = datos_equipo()
    data["cpu"] = cpu
    data["ram_raw"] = ram or ["8GB|2400|PC4|Kingston|PN1", "8GB|2400|PC4|Kingston|PN1"]
    data["disk_raw"] = discos or [{"desc": "SAMSUNG MZVLB512 512GB SSD M.2", "serial": "D1"}]
    return data


def test_normalizar_descarta_lo_no_pedido():
    assert requerimiento.normalizar(
        {
            "cpu": "Cualquiera",
            "generacion": 0,
            "ram_gb": "Cualquiera",
            "disco_gb": "1 TB",
            "disco_tipo": "ssd",
            "office": "Sí",
            "nota": "  ",
        }
    ) == {"disco_gb": 1000, "disco_tipo": "SSD", "office": True}
    assert requerimiento.normalizar(None) == {}
    assert requerimiento.normalizar({"office": "Cualquiera"}) == {}


@pytest.mark.parametrize(
    "cpu, gen",
    [
        ("Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz", 8),
        ("Intel(R) Core(TM) i5-10210U CPU @ 1.60GHz", 10),
        ("11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz", 11),
        ("12th Gen Intel(R) Core(TM) i7-1255U", 12),
        ("Intel(R) Core(TM) i5 CPU M 520 @ 2.40GHz", 1),
        ("AMD Ryzen 5 5500U with Radeon Graphics", 5),
        ("AMD Ryzen 7 PRO 4750U with Radeon Graphics", 4),
        ("Intel(R) Core(TM) Ultra 5 125U", 1),
        ("Intel(R) Celeron(R) N4020 CPU @ 1.10GHz", 0),
    ],
)
def test_generacion_cpu(cpu, gen):
    assert requerimiento.generacion_cpu(cpu) == gen


def test_cpu_coincide_por_palabras():
    cpu = "Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz"
    assert requerimiento.cpu_coincide("i5", cpu)
    assert requerimiento.cpu_coincide("Core i5-8350U", cpu)
    assert not requerimiento.cpu_coincide("i7", cpu)
    assert requerimiento.cpu_coincide("Ryzen 5", "AMD Ryzen 5 5500U")
    assert not requerimiento.cpu_coincide("Ryzen 7", "AMD Ryzen 5 5500U")


def test_equipo_igual_a_lo_pedido_no_avisa():
    req = {"cpu": "i5", "generacion": 8, "ram_gb": 16, "disco_gb": 512, "disco_tipo": "SSD"}
    assert requerimiento.comparar(req, equipo()) == []
    # El mismo disco leído en GB decimales distintos sigue siendo "de 512".
    data = equipo(discos=[{"desc": "WD 500GB SSD SATA", "serial": "D"}])
    assert requerimiento.comparar(req, data) == []


def test_avisa_cada_diferencia_tambien_si_es_mas():
    req = {"cpu": "i7", "generacion": 10, "ram_gb": 8, "disco_gb": 256, "disco_tipo": "HDD"}
    difs = requerimiento.comparar(req, equipo())
    assert len(difs) == 4
    assert any(d.startswith("Procesador:") and "i7" in d for d in difs)
    assert "Generación: es 8ª, se pidió 10ª (más vieja)" in difs
    assert "RAM: tiene 16 GB, se pidió 8 GB (más)" in difs
    assert "Disco: tiene 512 GB SSD, se pidió 256 GB HDD" in difs


def test_office_solo_se_compara_si_se_sabe():
    req = {"office": True}
    assert requerimiento.comparar(req, equipo()) == []
    assert requerimiento.comparar(req, equipo(), tiene_office=True) == []
    assert requerimiento.comparar(req, equipo(), tiene_office=False) == [
        "Office: se pidió con Office y no lo tiene"
    ]


def test_ram_ilegible_avisa():
    data = equipo()
    data["ram_raw"] = []
    assert requerimiento.comparar({"ram_gb": 16}, data) == [
        "RAM: no se pudo leer (se pidió 16 GB)"
    ]


def test_resumen():
    assert (
        requerimiento.resumen(
            {"cpu": "i5", "generacion": 8, "ram_gb": 16, "disco_gb": 512,
             "disco_tipo": "SSD", "office": False}
        )
        == "i5 · 8ª gen · 16 GB RAM · 512 GB SSD · sin Office"
    )
    assert requerimiento.resumen({}) == ""


# ─────────────────────────────────────────────────────────
#  Con el lote: se guarda en '.lote' y el HTML lo marca
# ─────────────────────────────────────────────────────────
def test_requerimiento_vive_en_el_lote_y_no_se_pierde(carpeta):
    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["requerimiento"] = {"ram_gb": 16}
    lotes.abrir_lote(lote)
    assert lotes.requerimiento_en_disco(lote["ruta"]) == {"ram_gb": 16}

    # Guardar el número secundario desde un lote sin requerimiento (como el
    # del puntero al lote activo) no lo borra.
    lotes.guardar_meta_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G1"))
    assert lotes.requerimiento_en_disco(lote["ruta"]) == {"ram_gb": 16}
    assert lotes.numero_sec_en_disco(lote["ruta"]) == "G1"

    # Reabrir la OT con el requerimiento vacío conserva el que tenía.
    reabierto = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553"))
    assert reabierto["requerimiento"] == {"ram_gb": 16}


def test_html_marca_el_equipo_distinto_y_sigue_al_requerimiento(carpeta):
    lote = lotes.hacer_lote("Entrega", "ACME", "553")
    lote["requerimiento"] = {"ram_gb": 16}
    lotes.abrir_lote(lote)
    lotes.guardar_equipo_general(lote, datos_equipo("SN1"), "", False, "", "2016", [])

    def html():
        with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
            return f.read()

    assert "DISTINTO A LO PEDIDO" in html()
    assert "RAM: tiene 8 GB, se pidió 16 GB (menos)" in html()
    # El JSON del equipo no guarda la diferencia: la calcula el reporte.
    assert "REQ" not in "".join(lotes.leer_equipos_lote(lote)[0])

    # Corregir el requerimiento rehace el HTML sin re-escanear.
    corregido = lotes.hacer_lote("Entrega", "ACME", "553")
    corregido["requerimiento"] = {"ram_gb": 8}
    lotes.abrir_lote(corregido)
    assert "DISTINTO A LO PEDIDO" not in html()
