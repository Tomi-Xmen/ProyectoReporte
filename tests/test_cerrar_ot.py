"""
Cerrar OT: un solo cierre que, si la OT está publicada para clonación, la
cierra en el servidor, trae lo que llegó y recién después la cierra en la PC.
"""

import json

import pytest

from inventario.nucleo import gestion_lote, lotes, remoto, sincronizacion

from test_sincronizacion import json_remoto, nombre


class ServidorFalso:
    """La OT en el servidor: sus JSON, si está publicada y si está cerrada."""

    def __init__(self, lote, publicada=True, esperados=()):
        self.lote = lote
        self.archivos = {}
        self.publicada = publicada
        self.cerrada = False
        self.esperados = list(esperados)

    def enviar(self, serial):
        """Lo que hace un notebook clonado: no puede si la OT ya se cerró."""
        if self.cerrada:
            return False
        self.archivos[nombre(serial)] = json_remoto(serial)
        return True

    def instalar(self, monkeypatch):
        monkeypatch.setattr(
            remoto, "leer_lote_activo_remoto",
            lambda _c: self.lote if self.publicada and not self.cerrada else None,
        )
        monkeypatch.setattr(
            remoto, "equipos_remotos", lambda _c, _l: [json.loads(t) for t in self.archivos.values()]
        )
        monkeypatch.setattr(remoto, "leer_esperados", lambda _c, _l: list(self.esperados))
        monkeypatch.setattr(remoto, "cerrar_lote_remoto", lambda _c, _l, _t: self._cerrar())
        monkeypatch.setattr(
            sincronizacion, "huellas_remotas",
            lambda _c, _l: {n: sincronizacion.huella(t) for n, t in self.archivos.items()},
        )
        monkeypatch.setattr(
            sincronizacion, "bajar", lambda _c, _l, nombres: {n: self.archivos[n] for n in nombres}
        )

    def _cerrar(self):
        self.cerrada = True
        self.publicada = False


@pytest.fixture
def ot(carpeta):
    lote = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-1"))
    return lote


def seriales(lote):
    with open(lotes.ruta_fusionado(lote), encoding="utf-8") as f:
        return sorted(e["SERIAL"] for e in json.load(f))


# ─────────────────────────────────────────────────────────
#  Núcleo
# ─────────────────────────────────────────────────────────
def test_anotar_la_ot_publicada(ot):
    assert not lotes.es_publicada(ot)
    lotes.anotar_publicada(ot)
    assert lotes.es_publicada(ot)
    assert not lotes.es_publicada(lotes.hacer_lote("Entrega", "ACME", "999"))
    lotes.anotar_publicada(None)
    assert not lotes.es_publicada(ot)


def test_estado_para_cerrar(ot, monkeypatch):
    servidor = ServidorFalso(ot, esperados=["CL1", "CL2", "CL3"])
    servidor.instalar(monkeypatch)
    servidor.enviar("CL1")
    assert sincronizacion.estado_para_cerrar(None, ot) == {
        "publicada": True, "recibidos": ["CL1"], "faltan": ["CL2", "CL3"],
    }
    servidor.publicada = False
    assert sincronizacion.estado_para_cerrar(None, ot) == {"publicada": False}


def test_cerrar_en_servidor_cierra_antes_de_traer(ot, monkeypatch):
    servidor = ServidorFalso(ot)
    servidor.instalar(monkeypatch)
    servidor.enviar("CL1")
    res = sincronizacion.cerrar_en_servidor(None, ot, publicada=True)
    assert servidor.cerrada and not servidor.enviar("TARDE")
    assert sincronizacion.aplicar(res["lote"], res["huellas"], res["contenidos"]) == 1
    assert seriales(ot) == ["CL1"]


def test_sin_publicar_trae_igual_pero_no_cierra_el_servidor(ot, monkeypatch):
    # El caso del panel cerrado: hay JSON en el servidor que nunca se trajeron.
    servidor = ServidorFalso(ot, publicada=False)
    servidor.instalar(monkeypatch)
    servidor.archivos[nombre("CL1")] = json_remoto("CL1")
    res = sincronizacion.cerrar_en_servidor(None, ot, publicada=False)
    assert not servidor.cerrada
    assert sincronizacion.aplicar(res["lote"], res["huellas"], res["contenidos"]) == 1


def test_el_celular_no_cierra_una_ot_publicada(ot):
    from inventario.nucleo.api_celular import ApiCelular

    lotes.anotar_publicada(ot)
    with pytest.raises(gestion_lote.ErrorGestion) as e:
        gestion_lote.cerrar(ot)
    assert (e.value.codigo, e.value.error) == (409, "publicada")
    assert not lotes.esta_cerrado(ot["ruta"])

    api = ApiCelular(token="secreto", reglas=[], al_evento=lambda _e: None)
    codigo, cuerpo = api.atender(
        "POST", "/api/v1/lote/cerrar", {"authorization": "Bearer secreto"},
        json.dumps({"lote": {"mov": "Entrega", "cliente": "ACME", "numero": "553"}}).encode(),
    )
    assert codigo == 409 and "Cerrala desde el PC" in cuerpo["mensaje"]

    lotes.anotar_publicada(None)
    assert gestion_lote.cerrar(ot)["estado"] == "cerrado"


# ─────────────────────────────────────────────────────────
#  "Cerrar OT" de la PC
# ─────────────────────────────────────────────────────────
pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def pc(ot, monkeypatch):
    """Servidor configurado, conexión directa y avisos registrados en vez de mostrarse."""
    from PySide6.QtWidgets import QApplication

    from inventario.nucleo import config
    from inventario.ui import avisos

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "SERVIDOR_CONFIGURADO", True)
    monkeypatch.setattr(config, "SCP_AVAILABLE", True)
    monkeypatch.setattr(remoto, "con_conexion", lambda tarea: tarea(None))
    mostrados = []
    for tipo in ("info", "aviso", "error"):
        monkeypatch.setattr(avisos, tipo, lambda *a, _t=tipo, **k: mostrados.append((_t, a[1], a[2])))
    respuestas = []
    monkeypatch.setattr(
        avisos, "confirmar",
        lambda *a, **k: (mostrados.append(("confirmar", a[1], a[2])), respuestas.pop(0) if respuestas else True)[1],
    )
    return {"lote": ot, "mostrados": mostrados, "respuestas": respuestas}


def test_cerrar_ot_publicada_trae_al_tardio_y_cierra_en_los_dos_lados(pc, monkeypatch):
    from inventario.ui import acciones

    ot = pc["lote"]
    servidor = ServidorFalso(ot, esperados=["CL1", "CL2", "TARDE"])
    servidor.instalar(monkeypatch)
    servidor.enviar("CL1")
    servidor.enviar("CL2")
    lotes.anotar_publicada(ot)
    # El tardío manda su JSON después de abrir el diálogo, antes de confirmar.
    respuestas = pc["respuestas"]
    original = remoto.cerrar_lote_remoto
    monkeypatch.setattr(
        remoto, "cerrar_lote_remoto", lambda c, l, t: (servidor.enviar("TARDE"), original(c, l, t))
    )

    assert acciones.cerrar_ot(None, ot)
    confirmacion = next(m for m in pc["mostrados"] if m[0] == "confirmar")
    assert "publicada para clonación" in confirmacion[2] and "• TARDE" in confirmacion[2]
    assert servidor.cerrada and not servidor.publicada
    assert seriales(ot) == ["CL1", "CL2", "TARDE"]
    assert lotes.esta_cerrado(ot["ruta"]) and not lotes.es_publicada(ot)
    final = pc["mostrados"][-1]
    assert final[0] == "info" and "cerrada en el servidor" in final[2]
    assert "Se trajeron 3 equipo(s)" in final[2]
    assert respuestas == []


def test_sin_conexion_pregunta_y_puede_cerrar_solo_aca(pc, monkeypatch):
    from inventario.ui import acciones

    def caida(_tarea):
        raise RuntimeError("No se pudo conectar a 192.168.1.10:22")

    monkeypatch.setattr(remoto, "con_conexion", caida)
    ot = pc["lote"]
    pc["respuestas"].extend([False])
    assert not acciones.cerrar_ot(None, ot)
    assert not lotes.esta_cerrado(ot["ruta"])

    pc["respuestas"].extend([True, True])
    assert acciones.cerrar_ot(None, ot)
    assert lotes.esta_cerrado(ot["ruta"])
    assert "sin revisar el servidor" in pc["mostrados"][-1][2]


def test_si_el_servidor_falla_al_cerrar_no_se_cierra_nada_aca(pc, monkeypatch):
    from inventario.ui import acciones

    ot = pc["lote"]
    servidor = ServidorFalso(ot)
    servidor.instalar(monkeypatch)

    def falla(*_):
        raise RuntimeError("se cortó la conexión")

    monkeypatch.setattr(sincronizacion, "bajar", falla)
    assert not acciones.cerrar_ot(None, ot)
    assert not lotes.esta_cerrado(ot["ruta"])
    assert pc["mostrados"][-1][0] == "error" and "sigue abierta" in pc["mostrados"][-1][2]


def test_sin_servidor_configurado_cierra_aca_sin_avisos_de_red(pc, monkeypatch):
    from inventario.nucleo import config
    from inventario.ui import acciones

    monkeypatch.setattr(config, "SERVIDOR_CONFIGURADO", False)
    monkeypatch.setattr(remoto, "con_conexion", lambda _t: pytest.fail("no debía conectarse"))
    ot = pc["lote"]
    assert acciones.cerrar_ot(None, ot)
    assert lotes.esta_cerrado(ot["ruta"])
    final = pc["mostrados"][-1][2]
    assert "sin revisar" not in final and "clonación" not in final
