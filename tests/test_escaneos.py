import json
import os

import pytest

from inventario.nucleo import escaneos, lotes, reconstruccion

from conftest import datos_equipo


# ─── Lecturas ────────────────────────────────────────────
@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("  5cd805dvnv ", "5CD805DVNV"),
        ("S/N: 5CD805DVNV", "5CD805DVNV"),
        ("S/N5CD805DVNV", "5CD805DVNV"),
        ("Serial No. ABC12345", "ABC12345"),
        ("SN 5CD805DVNV", "5CD805DVNV"),
        ("SN12345", "SN12345"),  # sin separador puede ser un serial real
        ("\x1d5CD805DVNV\x04", "5CD805DVNV"),
        ("https://soporte.ejemplo.com/garantia?modelo=X&sn=5cd805dvnv", "5CD805DVNV"),
        ("MODEL: 840 G5\nS/N: 5CD805DVNV\nP/N: 5HH48LA", "5CD805DVNV"),
        ("MODEL=840;SERIAL=ABC12345", "ABC12345"),
    ],
)
def test_normalizar_lectura(crudo, esperado):
    assert escaneos.normalizar_lectura(crudo) == esperado


@pytest.mark.parametrize(
    "valor, formato, descartado",
    [
        ("5CD805DVNV", "CODE_128", False),
        ("7801234567890", "EAN_13", True),
        ("HTTPS://EJEMPLO.COM/X", "QR_CODE", True),
        ("AA:BB:CC:DD:EE:FF", "", True),
        ("5HH48LA#ABM", "", True),
        ("HOLA MUNDO", "", True),
        ("AB1", "", True),
        ("A" * 41, "", True),
        ("ABC*123", "", True),
        ("CN-0ABC12-74261", "", False),
    ],
)
def test_motivo_descarte(valor, formato, descartado):
    assert (escaneos.motivo_descarte(valor, formato) is not None) == descartado


def _reglas(tmp_path, crudas):
    ruta = tmp_path / "reglas.json"
    ruta.write_text(json.dumps(crudas), encoding="utf-8")
    return escaneos.cargar_reglas(str(ruta))


def test_cargar_reglas_salta_las_rotas(tmp_path, capsys):
    reglas = _reglas(
        tmp_path,
        [
            {"tipo": "Transformador", "patron": "^WDJ"},
            {"tipo": "Tostadora", "patron": "^X"},
            {"tipo": "Monitor", "patron": "(sin cerrar"},
        ],
    )
    assert [r["tipo"] for r in reglas] == ["Transformador"]
    assert "Regla ignorada" in capsys.readouterr().out
    assert escaneos.cargar_reglas(str(tmp_path / "no_existe.json")) == []


def test_elegir_codigo_descarta_ean_y_pn():
    eleccion = escaneos.elegir_codigo(
        [
            {"texto": "7801234567890", "formato": "EAN_13"},
            {"texto": "5HH48LA#ABM", "formato": "CODE_128"},
            {"texto": "S/N: 5CD805DVNV", "formato": "CODE_128"},
        ],
        esperado="Notebook",
    )
    assert (eleccion["valor"], eleccion["tipo"]) == ("5CD805DVNV", "Notebook")
    assert len(eleccion["descartes"]) == 2


def test_elegir_codigo_prefiere_alfanumerico():
    # Dell: service tag y express service code (solo dígitos) en la misma etiqueta.
    eleccion = escaneos.elegir_codigo(
        [{"texto": "12345678901"}, {"texto": "7XK2Q93"}], esperado="Notebook"
    )
    assert eleccion["valor"] == "7XK2Q93"


def test_elegir_codigo_empate_pide_elegir():
    eleccion = escaneos.elegir_codigo([{"texto": "ABC12345"}, {"texto": "XYZ98765"}])
    assert eleccion["valor"] is None
    assert set(eleccion["candidatos"]) == {"ABC12345", "XYZ98765"}


def test_elegir_codigo_con_reglas(tmp_path):
    reglas = _reglas(
        tmp_path,
        [
            {"tipo": "Transformador", "patron": "^WDJ"},
            {"tipo": "Notebook", "patron": "^5CD"},
        ],
    )
    lecturas = [{"texto": "5CD805DVNV"}, {"texto": "WDJTH0A9ZFP0B4"}]
    assert escaneos.elegir_codigo(lecturas, "Transformador", reglas)["valor"] == "WDJTH0A9ZFP0B4"
    assert escaneos.elegir_codigo(lecturas, "Notebook", reglas)["valor"] == "5CD805DVNV"

    # Se esperaba un transformador pero solo se leyó un notebook: vuelve con su tipo real.
    sola = escaneos.elegir_codigo([{"texto": "5CD805DVNV"}], "Transformador", reglas)
    assert (sola["valor"], sola["tipo"]) == ("5CD805DVNV", "Notebook")

    # Sin esperado, las reglas deciden el tipo.
    assert escaneos.elegir_codigo([{"texto": "WDJTH0A9ZFP0B4"}], None, reglas)["tipo"] == "Transformador"


def test_elegir_codigo_sin_lecturas_validas():
    eleccion = escaneos.elegir_codigo([{"texto": "", "formato": "QR_CODE"}])
    assert eleccion["valor"] is None and eleccion["candidatos"] == []


# ─── Lote ────────────────────────────────────────────────
def test_lote_desde_formulario():
    lote = escaneos.lote_desde_formulario("Entrega", "Acme Ltda.", "OT 553", "guía 9")
    assert (lote["cliente"], lote["numero"], lote["numero_sec"]) == ("ACME_LTDA", "553", "9")
    for args, titulo in [
        (("Entrega", "  ", "553"), "Falta el cliente"),
        (("Entrega", "ACME", "CON"), "Número inválido"),
        (("Envio", "ACME", "553"), "Movimiento inválido"),
    ]:
        with pytest.raises(escaneos.LoteInvalido) as e:
            escaneos.lote_desde_formulario(*args)
        assert e.value.titulo == titulo


def test_registros_del_celular_pasan_por_los_flujos_existentes(lote_con_equipos):
    """Lo que crea el celular son JSON comunes: reconstrucción y mover OT los manejan igual."""
    lote = lote_con_equipos
    escaneos.registrar_equipo(lote, "MON12345", tipo="Monitor")
    escaneos.asignar_transformador(lote, "TR-0001", serial_equipo="SN1")
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        antes = f.read()

    os.remove(lotes.ruta_html_lote(lote))
    os.remove(lotes.ruta_fusionado(lote))
    carpetas = reconstruccion.carpetas_a_reconstruir(lotes.ruta_reportes())
    total, _regenerados, sueltos, errores = reconstruccion.reconstruir_carpetas(carpetas)
    assert (total, sueltos, errores) == (3, [], [])
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert f.read() == antes

    destino = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "600"))
    assert lotes.mover_equipos_a_lote(lote, ["MON12345"], destino) == 1
    (movido,) = lotes.leer_equipos_lote(destino)
    assert (movido["OT_ID"], movido["TIPO_EQUIPO"]) == ("600", "Monitor")


def test_resolver_lote(lote_con_equipos):
    lote = escaneos.resolver_lote("Entrega", "ACME", "553")
    assert lote["ruta"] == lote_con_equipos["ruta"] and lote["numero_sec"] == "G-9"

    for args in [
        ("Envio", "ACME", "553"),
        ("Entrega", "../ACME", "553"),
        ("Entrega", "ACME", "../../x"),
        ("Entrega", "acme", "553"),  # sin normalizar
        ("Entrega", "ACME", "999"),  # no existe
    ]:
        with pytest.raises(escaneos.LoteInvalido):
            escaneos.resolver_lote(*args)

    lotes.cerrar_lote(lote)
    with pytest.raises(escaneos.LoteInvalido, match="cerrado"):
        escaneos.resolver_lote("Entrega", "ACME", "553")


def test_registrar_equipo_nuevo_regenera_derivados(lote_con_equipos):
    lote = lote_con_equipos
    r = escaneos.registrar_equipo(lote, "s/n: mon12345", tipo="Monitor", modelo="Dell P2419H")
    assert r == {"estado": "registrado", "serial": "MON12345", "tipo": "Monitor", "total": 3}

    (eq,) = [e for e in lotes.leer_equipos_lote(lote) if e["SERIAL"] == "MON12345"]
    assert eq["TIPO_EQUIPO"] == "Monitor" and eq["ORIGEN"] == "celular"
    assert (eq["OT_ID"], eq["GUIA_ID"], eq["SN_Win"]) == ("553", "G-9", "N/A")

    with open(lotes.ruta_fusionado(lote), encoding="utf-8") as f:
        assert "MON12345" in {e["SERIAL"] for e in json.load(f)}
    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        html = f.read()
    assert "MON12345" in html and '<span id="total-count">3</span>' in html
    # Sin discos: no debe aparecer una fila de disco inventada.
    assert "Serie Disco Duro</th><td class='serial-tag'>PENDIENTE" not in html


def test_registrar_equipo_ya_estaba_no_lo_toca(lote_con_equipos):
    # Escaneado antes en el PC, con hardware: el celular solo lo confirma.
    lotes.guardar_equipo_general(
        lote_con_equipos, datos_equipo("5CD805DVNV"), "", False, "", "2016", []
    )
    antes = lotes.leer_equipos_lote(lote_con_equipos)
    r = escaneos.registrar_equipo(lote_con_equipos, "S/N: 5cd805dvnv")
    assert r["estado"] == "ya_estaba" and r["serial"] == "5CD805DVNV" and r["total"] == 3
    assert lotes.leer_equipos_lote(lote_con_equipos) == antes


def test_registrar_equipo_en_otra_ot(lote_con_equipos):
    otra = lotes.abrir_lote(lotes.hacer_lote("Retiro", "BETA", "77"))
    lotes.guardar_equipo_general(otra, datos_equipo("ZZ99887"), "", False, "", "2016", [])

    r = escaneos.registrar_equipo(lote_con_equipos, "ZZ99887")
    assert r["estado"] == "en_otra_ot" and "BETA" in r["otro"]
    assert lotes.contar_equipos(lote_con_equipos["ruta"]) == 2

    r = escaneos.registrar_equipo(lote_con_equipos, "ZZ99887", forzar=True)
    assert r["estado"] == "registrado"


def test_registrar_equipo_invalido(lote_con_equipos):
    r = escaneos.registrar_equipo(lote_con_equipos, "5HH48LA#ABM")
    assert r["estado"] == "invalido" and "P/N" in r["motivo"]
    with pytest.raises(ValueError):
        escaneos.registrar_equipo(lote_con_equipos, "ABC12345", tipo="Transformador")


def test_transformadores_en_rafaga(lote_con_equipos):
    lote = lote_con_equipos
    escaneos.registrar_equipo(lote, "MON12345", tipo="Monitor")  # no lleva transformador
    orden = [
        e["SERIAL"]
        for _, e in escaneos.equipos_en_orden_de_escaneo(lote)
        if escaneos.tipo_equipo(e) == "Notebook"
    ]

    r1 = escaneos.asignar_transformador(lote, "TR-0001")
    r2 = escaneos.asignar_transformador(lote, "TR-0002")
    assert (r1["estado"], r1["equipo"]) == ("asignado", orden[0])
    assert (r2["estado"], r2["equipo"]) == ("asignado", orden[1])

    # La misma lectura otra vez no consume un equipo.
    assert escaneos.asignar_transformador(lote, "tr-0001")["estado"] == "ya_estaba"
    # Ya no quedan notebooks sin transformador: el monitor no cuenta.
    assert escaneos.asignar_transformador(lote, "TR-0003")["estado"] == "sin_equipo_pendiente"


def test_rafaga_sigue_con_los_equipos_que_llegan_del_pc(lote_con_equipos):
    lote = lote_con_equipos
    escaneos.asignar_transformador(lote, "TR-0001")
    escaneos.asignar_transformador(lote, "TR-0002")
    assert escaneos.asignar_transformador(lote, "TR-0003")["estado"] == "sin_equipo_pendiente"

    # Llega un notebook nuevo escaneado en el PC: el próximo cargador es suyo.
    lotes.guardar_equipo_general(lote, datos_equipo("SN3"), "", False, "", "2016", [])
    r = escaneos.asignar_transformador(lote, "TR-0003")
    assert (r["estado"], r["equipo"]) == ("asignado", "SN3")


def test_reescanear_en_el_pc_no_pierde_el_cargador_ni_el_orden(lote_con_equipos):
    lote = lote_con_equipos
    orden = [e["SERIAL"] for _, e in escaneos.equipos_en_orden_de_escaneo(lote)]
    primero = escaneos.asignar_transformador(lote, "TR-0001")["equipo"]
    assert primero == orden[0]

    # El primero se vuelve a pasar por el PC (p. ej. para leer el hardware).
    lotes.guardar_equipo_general(lote, datos_equipo(primero), "otra vez", False, "", "2016", [])

    assert [e["SERIAL"] for _, e in escaneos.equipos_en_orden_de_escaneo(lote)] == orden
    assert escaneos.estado_lote(lote)["equipos"][0]["sn_transf"] == "TR-0001"
    # El próximo cargador sigue yendo al segundo, no al re-escaneado.
    r = escaneos.asignar_transformador(lote, "TR-0002")
    assert (r["estado"], r["equipo"]) == ("asignado", orden[1])


def test_completar_en_el_pc_un_equipo_leido_por_el_celular(lote_con_equipos):
    lote = lote_con_equipos
    escaneos.registrar_equipo(lote, "CEL12345")
    escaneos.guardar_cargadores(lote, [{"serial": "CEL12345", "sn_transf": "TR-0009"}])

    lotes.guardar_equipo_general(lote, datos_equipo("CEL12345"), "", False, "", "2016", [])

    (eq,) = [e for e in lotes.leer_equipos_lote(lote) if e["SERIAL"] == "CEL12345"]
    assert eq["SN_Transf"] == "TR-0009"
    assert eq.get("ORIGEN") != escaneos.ORIGEN_CELULAR  # ya tiene hardware


def test_la_etiqueta_de_un_equipo_no_se_guarda_como_cargador(lote_con_equipos):
    lote = lote_con_equipos
    primero = escaneos.asignar_transformador(lote, "TR-0001")["equipo"]
    segundo = "SN2" if primero == "SN1" else "SN1"

    assert escaneos.asignar_transformador(lote, segundo.lower())["estado"] == "es_equipo"
    assert escaneos.asignar_transformador(lote, primero, serial_equipo=segundo)["estado"] == "es_equipo"
    # No consumió ni pisó nada.
    r = escaneos.asignar_transformador(lote, "TR-0002")
    assert (r["estado"], r["equipo"]) == ("asignado", segundo)


def test_transformador_guiado(lote_con_equipos):
    lote = lote_con_equipos
    r = escaneos.asignar_transformador(lote, "TR-0001", serial_equipo="SN2")
    assert (r["estado"], r["equipo"], r["reemplazo"]) == ("asignado", "SN2", None)

    r = escaneos.asignar_transformador(lote, "TR-0001", serial_equipo="SN1")
    assert (r["estado"], r["equipo"]) == ("duplicado", "SN2")

    r = escaneos.asignar_transformador(lote, "TR-0009", serial_equipo="SN2")
    assert (r["estado"], r["reemplazo"]) == ("asignado", "TR-0001")

    assert escaneos.asignar_transformador(lote, "TR-0005", serial_equipo="NOEXISTE")["estado"] == (
        "equipo_no_encontrado"
    )
    assert escaneos.asignar_transformador(lote, "  ")["estado"] == "invalido"

    with open(lotes.ruta_html_lote(lote), encoding="utf-8") as f:
        assert "TR-0009" in f.read()


def test_estado_lote(lote_con_equipos):
    escaneos.registrar_equipo(lote_con_equipos, "IMP12345", tipo="Impresora")
    escaneos.asignar_transformador(lote_con_equipos, "TR-0001", serial_equipo="SN1")
    estado = escaneos.estado_lote(lote_con_equipos)
    assert estado["numero"] == "553" and estado["numero_sec"] == "G-9"
    por_serial = {e["serial"]: e for e in estado["equipos"]}
    assert por_serial["SN1"]["sn_transf"] == "TR-0001" and not por_serial["SN1"]["sin_hardware"]
    assert por_serial["IMP12345"] == {
        "serial": "IMP12345",
        "tipo": "Impresora",
        "modelo": "Impresora",
        "sn_transf": None,
        "sin_hardware": True,
    }


# ─── Lista de cargadores del celular (guardar con botón) ────────────────
def _transf_en_disco(lote):
    return {
        e["SERIAL"]: escaneos.transformador_actual(e)
        for _, e in escaneos.equipos_en_orden_de_escaneo(lote)
    }


def test_revisar_transformador_no_escribe(lote_con_equipos):
    lote = lote_con_equipos
    antes = _transf_en_disco(lote)
    assert escaneos.revisar_transformador(lote, " tr-0001 ") == {
        "estado": "propuesto", "sn_transf": "TR-0001",
    }
    assert escaneos.revisar_transformador(lote, "SN1")["estado"] == "es_equipo"
    assert escaneos.revisar_transformador(lote, "")["estado"] == "invalido"
    assert _transf_en_disco(lote) == antes

    escaneos.guardar_cargadores(lote, [{"serial": "SN1", "sn_transf": "TR-0001"}])
    r = escaneos.revisar_transformador(lote, "TR-0001")
    assert (r["estado"], r["equipo"]) == ("duplicado", "SN1")


def test_guardar_cargadores_escribe_y_verifica_json_y_fusionado(lote_con_equipos):
    lote = lote_con_equipos
    r = escaneos.guardar_cargadores(
        lote,
        [{"serial": "SN1", "sn_transf": "TR-0001"}, {"serial": "sn2", "sn_transf": "tr-0002"}],
    )
    assert r["estado"] == "guardado"
    assert r["guardados"] == [
        {"serial": "SN1", "sn_transf": "TR-0001"},
        {"serial": "SN2", "sn_transf": "TR-0002"},
    ]
    assert (r["nuevos"], r["sin_cargador"]) == (2, 0)
    assert _transf_en_disco(lote) == {"SN1": "TR-0001", "SN2": "TR-0002"}
    assert escaneos._fusionados(lote) == {"SN1": "TR-0001", "SN2": "TR-0002"}

    # El mismo pedido otra vez (reintento tras un corte) confirma sin reescribir.
    r = escaneos.guardar_cargadores(lote, [{"serial": "SN1", "sn_transf": "TR-0001"}])
    assert (r["estado"], r["nuevos"]) == ("guardado", 0)


@pytest.mark.parametrize(
    "pares, motivo",
    [
        ([{"serial": "NOEXISTE", "sn_transf": "TR-1"}], "no está en el lote"),
        ([{"serial": "SN1", "sn_transf": "  "}], "vacío"),
        ([{"serial": "SN1", "sn_transf": "SN2"}], "serial de un equipo"),
        ([{"serial": "SN1", "sn_transf": "TR-1"}, {"serial": "SN1", "sn_transf": "TR-2"}], "dos veces"),
        ([{"serial": "SN1", "sn_transf": "TR-1"}, {"serial": "SN2", "sn_transf": "tr-1"}], "dos veces"),
        (["basura"], "no está en el lote"),
    ],
)
def test_guardar_cargadores_todo_o_nada(lote_con_equipos, pares, motivo):
    lote = lote_con_equipos
    antes = _transf_en_disco(lote)
    r = escaneos.guardar_cargadores(lote, [{"serial": "SN2", "sn_transf": "TR-OK"}] + pares)
    assert r["estado"] == "rechazado"
    assert any(motivo in e["motivo"] for e in r["errores"])
    assert _transf_en_disco(lote) == antes  # ni el par bueno se escribió


def test_guardar_cargadores_no_pisa_lo_que_ya_tiene_otro_cargador(lote_con_equipos):
    lote = lote_con_equipos
    escaneos.guardar_cargadores(lote, [{"serial": "SN1", "sn_transf": "TR-0001"}])

    r = escaneos.guardar_cargadores(lote, [{"serial": "SN1", "sn_transf": "TR-0009"}])
    assert r["estado"] == "rechazado" and "ya tiene el cargador TR-0001" in r["errores"][0]["motivo"]
    r = escaneos.guardar_cargadores(lote, [{"serial": "SN2", "sn_transf": "TR-0001"}])
    assert r["estado"] == "rechazado" and "ya es de SN1" in r["errores"][0]["motivo"]
    assert escaneos.guardar_cargadores(lote, [])["estado"] == "rechazado"
    assert _transf_en_disco(lote)["SN1"] == "TR-0001"


def test_guardar_cargadores_avisa_si_la_verificacion_falla(lote_con_equipos, monkeypatch):
    lote = lote_con_equipos
    # Simula un disco que "acepta" la escritura pero no la guarda.
    monkeypatch.setattr(escaneos, "guardar_transformadores", lambda lote, cambios: [])
    r = escaneos.guardar_cargadores(lote, [{"serial": "SN1", "sn_transf": "TR-0001"}])
    assert r["estado"] == "error"
    assert "JSON del equipo" in r["errores"][0]["motivo"]
