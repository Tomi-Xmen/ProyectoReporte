"""
Ficha de un equipo: lo que el celular muestra al tocar un equipo del lote, y
la edición de su JSON.

El JSON individual es la única fuente de verdad (ver lotes.py): editar acá es
reescribirlo y regenerar el HTML y el FUSIONADO, igual que cualquier guardado.

Se edita todo menos el serial, que da nombre al archivo del equipo. El
hardware (CPU, RAM, discos, red, batería) viaja como datos crudos y al
guardar se rearman sus filas HTML con las mismas funciones que el escaneo:
el export a Valida y "Copiar Filas" leen esas filas del reporte, así que
tienen que salir con el mismo formato que si se hubiera escaneado.
"""

import hashlib
import html
import json
import re

from .escaneos import ORIGEN_CELULAR, tipo_equipo
from .lotes import marcar_pendiente_envio, regenerar_lote
from .reporte_html import (
    TRANSF_PENDIENTE,
    filas_hardware_desde_json,
    render_filas_discos,
    render_filas_ram,
    render_filas_red,
    resumen_ram,
)
from .transformadores import (
    equipos_en_orden_de_escaneo,
    normalizar_sn_transf,
    transformador_actual,
)

COMPONENTES = [
    "Carcaza",
    "Pantalla",
    "Teclado",
    "Touchpad",
    "Puertos USB",
    "Puertos Video",
    "Ethernet/Wi-Fi",
    "Placa base",
    "Memoria",
    "Disco duro",
    "Batería",
]
ESTADOS = ["OK", "OBS", "MALO"]
VERSIONES_OFFICE = ["2013", "2016", "2019", "2021", "2024", "365"]

PENDIENTE = "PENDIENTE"
SIN_OBS = "Sin observaciones"
SIN_OFFICE = "No"

# Campo de la ficha → clave del JSON. Vaciar un campo lo devuelve a su valor
# "no cargado", el mismo con que nace un registro.
_CAMPOS = {
    "modelo": "MODELO",
    "sn_win": "SN_Win",
    "sn_transf": "SN_Transf",
    "office": "OFFICE",
    "sn_app": "SN_APP",
    "obs": "OBS",
}
_VACIOS = {
    "SN_Win": PENDIENTE,
    "SN_Transf": TRANSF_PENDIENTE,
    "SN_APP": PENDIENTE,
    "OBS": SIN_OBS,
    "OFFICE": SIN_OFFICE,
}
_LARGO_MAX = 500


class ErrorFicha(Exception):
    def __init__(self, codigo, error, mensaje):
        super().__init__(mensaje)
        self.codigo, self.error, self.mensaje = codigo, error, mensaje


def _clave(texto):
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def _buscar(lote, serial):
    """(ruta, jdata) del equipo con ese serial en el lote, o ErrorFicha 404."""
    clave = _clave(serial)
    for ruta, jdata in equipos_en_orden_de_escaneo(lote):
        if _clave(jdata.get("SERIAL", "")) == clave:
            return ruta, jdata
    raise ErrorFicha(404, "equipo", f"{serial} no está en el lote.")


def _version(ruta):
    """Huella del archivo: si cambió desde que el celular abrió la ficha, no se pisa."""
    with open(ruta, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:12]


def _texto_celda(celda):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", celda)).split())


def filas_tabla(html_filas):
    """[{"etiqueta", "valor"}] de filas '<tr><th>…</th><td>…</td></tr>' del reporte."""
    filas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_filas or "", re.S | re.I):
        celdas = [_texto_celda(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)]
        celdas = [c for c in celdas if c]
        if len(celdas) >= 2:
            filas.append({"etiqueta": celdas[0], "valor": " · ".join(celdas[1:])})
        elif celdas:
            filas.append({"etiqueta": "", "valor": celdas[0]})
    return filas


def _lista(valor):
    if isinstance(valor, str):
        valor = [valor]
    return [str(v).strip() for v in (valor or []) if str(v).strip()]


def _filas_de(html_filas, etiqueta):
    return [f["valor"] for f in filas_tabla(html_filas) if f["etiqueta"] == etiqueta]


def _hardware(jdata):
    """
    El hardware del equipo como datos editables. Se prefieren los crudos
    (ram_raw, disk_raw, net_raw); los JSON viejos solo traen las filas HTML y
    de ahí se sacan, con los mismos respaldos que usa el reporte.
    """
    data = jdata.get("DATA") or {}
    if _sin_hardware(jdata):
        return {"host": "", "cpu": "", "bateria": "", "ram": [], "discos": [], "red": []}

    ram_html, disk_html, net_html = filas_hardware_desde_json(jdata)

    ram = _lista(data.get("ram_raw") or data.get("ram_rows"))
    if not ram:
        ram = _filas_de(ram_html, "Módulo RAM")

    crudos = data.get("disk_raw") or data.get("disks_data")
    if isinstance(crudos, dict):
        crudos = [crudos]
    if crudos:
        discos = [
            {"desc": str(d.get("desc") or "").strip(), "serial": str(d.get("serial") or "").strip()}
            for d in crudos
            if isinstance(d, dict)
        ]
    else:
        # Las filas vienen de a pares: descripción y, debajo, su serie.
        discos = []
        for f in filas_tabla(disk_html):
            if f["etiqueta"] == "Discos Internos":
                discos.append({"desc": f["valor"], "serial": ""})
            elif f["etiqueta"] == "Serie Disco Duro":
                if discos and not discos[-1]["serial"]:
                    discos[-1]["serial"] = f["valor"]
                else:
                    discos.append({"desc": "", "serial": f["valor"]})

    red = _lista(data.get("net_raw"))
    if not red:
        red = _filas_de(net_html, "Red Activa")

    return {
        "host": str(data.get("host") or ""),
        "cpu": str(data.get("cpu") or ""),
        "bateria": str(data.get("Battery") or ""),
        "ram": ram,
        "discos": discos,
        "red": red,
    }


def _aplicar_hardware(jdata, hw):
    """Escribe el hardware editado y rearma sus filas HTML como lo haría el escaneo."""
    if not isinstance(hw, dict):
        raise ErrorFicha(400, "dato", "'hardware' tiene que ser un objeto.")
    data = jdata.get("DATA")
    if not isinstance(data, dict):
        data = jdata["DATA"] = {}

    for campo, clave in (("host", "host"), ("cpu", "cpu"), ("bateria", "Battery")):
        if campo in hw:
            valor = _texto(hw[campo], campo)
            if valor:
                data[clave] = valor
            else:
                data.pop(clave, None)

    if "ram" in hw:
        ram = [_texto(r, "ram") for r in _lista_de_textos(hw["ram"], "ram")]
        ram = [r for r in ram if r]
        data["ram_raw"] = ram
        data["ram_html"] = render_filas_ram(ram)
        data["Manufacturer"], data["Partnumber"] = resumen_ram(ram)
        data.pop("ram_rows", None)

    if "discos" in hw:
        if not isinstance(hw["discos"], list):
            raise ErrorFicha(400, "dato", "'discos' tiene que ser una lista.")
        discos = []
        for d in hw["discos"]:
            if not isinstance(d, dict):
                raise ErrorFicha(400, "dato", "Cada disco necesita 'desc' y 'serial'.")
            desc = _texto(d.get("desc", ""), "desc")
            serial = _texto(d.get("serial", ""), "serial")
            if desc or serial:
                discos.append({"desc": desc or "Disco interno", "serial": serial})
        disk_html, seriales = render_filas_discos(discos)
        data["disk_raw"] = discos
        data["disk_html"] = disk_html
        data["disk_serials"] = seriales
        data.pop("disks_data", None)
        # SN_HDD es lo que viaja en el FUSIONADO: sigue a los discos.
        jdata["SN_HDD"] = "_".join(s for s in seriales if s) or PENDIENTE

    if "red" in hw:
        red = [_texto(r, "red") for r in _lista_de_textos(hw["red"], "red")]
        red = [r for r in red if r]
        filas = render_filas_red(red)
        data["net_raw"] = red
        data["net_rows"] = filas
        data["net_html"] = filas


def _lista_de_textos(valor, campo):
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise ErrorFicha(400, "dato", f"'{campo}' tiene que ser una lista de textos.")
    return valor


def _sin_hardware(jdata):
    """Leído solo por su código y sin hardware cargado a mano después."""
    data = jdata.get("DATA") or {}
    cargado = any(data.get(k) for k in ("host", "cpu", "Battery", "ram_raw", "disk_raw", "net_raw"))
    return jdata.get("ORIGEN") == ORIGEN_CELULAR and not cargado


def _sin_vacio(jdata, clave):
    valor = jdata.get(clave)
    return "" if valor in (None, _VACIOS.get(clave), "N/A") else str(valor)


def ficha(lote, serial):
    """La ficha completa de un equipo del lote."""
    ruta, jdata = _buscar(lote, serial)
    componentes = jdata.get("DETALLE_COMPONENTES") or []
    return {
        "serial": jdata.get("SERIAL", serial),
        "tipo": tipo_equipo(jdata),
        "version": _version(ruta),
        "sin_hardware": _sin_hardware(jdata),
        "tiene_fallas": bool(jdata.get("TIENE_FALLAS")),
        "datos": {campo: _sin_vacio(jdata, clave) for campo, clave in _CAMPOS.items()},
        # Un equipo leído solo por el celular no tiene revisión: se ofrece la
        # grilla en OK para cargarla, y 'revisado' dice si ya existía.
        "revisado": bool(componentes),
        "componentes": [
            {"nombre": str(c.get("nombre", "")), "estado": str(c.get("estado", "OK")), "obs": str(c.get("obs", ""))}
            for c in componentes
        ]
        or [{"nombre": n, "estado": "OK", "obs": ""} for n in COMPONENTES],
        "fecha": (jdata.get("DATA") or {}).get("fecha") or str(jdata.get("ESCANEADO", "")),
        "hardware": _hardware(jdata),
        "opciones": {"estados": ESTADOS, "office": VERSIONES_OFFICE},
    }


def _texto(valor, campo):
    if not isinstance(valor, str):
        raise ErrorFicha(400, "dato", f"'{campo}' tiene que ser texto.")
    limpio = " ".join(valor.split()) if campo != "obs" else valor.strip()
    if len(limpio) > _LARGO_MAX:
        raise ErrorFicha(400, "dato", f"'{campo}' es demasiado largo.")
    return limpio


def _office(valor):
    """'' / 'No' → sin Office; '2024' u 'Office 2024' → 'Office 2024'."""
    v = valor.removeprefix("Office").strip()
    if v in ("", SIN_OFFICE):
        return SIN_OFFICE
    if v not in VERSIONES_OFFICE:
        raise ErrorFicha(400, "dato", f"Versión de Office desconocida: {valor!r}")
    return f"Office {v}"


def _componentes(valor):
    if not isinstance(valor, list) or not valor:
        raise ErrorFicha(400, "dato", "'componentes' tiene que ser una lista.")
    limpios = []
    for c in valor:
        if not isinstance(c, dict) or not isinstance(c.get("nombre"), str):
            raise ErrorFicha(400, "dato", "Cada componente necesita 'nombre'.")
        estado = c.get("estado", "OK")
        if estado not in ESTADOS:
            raise ErrorFicha(400, "dato", f"Estado desconocido: {estado!r}")
        # Como en el PC: la observación solo vale si el estado no es OK.
        obs = _texto(c.get("obs", ""), "obs") if estado != "OK" else ""
        limpios.append({"nombre": c["nombre"], "estado": estado, "obs": obs})
    return limpios


def editar(lote, serial, cambios, version):
    """
    Aplica 'cambios' (solo los campos tocados) al JSON del equipo y regenera
    el lote. 'version' es la de la ficha que se editó: si el archivo cambió
    desde entonces (re-escaneo, otro celular, el PC) se rechaza con 409 en vez
    de pisar lo nuevo. Devuelve la ficha actualizada.
    """
    if not isinstance(cambios, dict) or not cambios:
        raise ErrorFicha(400, "dato", "No hay cambios para guardar.")
    desconocidos = set(cambios) - set(_CAMPOS) - {"componentes", "hardware"}
    if desconocidos:
        raise ErrorFicha(400, "dato", f"No se puede editar: {', '.join(sorted(desconocidos))}")

    ruta, _ = _buscar(lote, serial)
    if version != _version(ruta):
        raise ErrorFicha(
            409, "cambiado", "El equipo cambió en el PC mientras lo editabas. Volvé a abrirlo."
        )
    with open(ruta, "r", encoding="utf-8") as f:
        jdata = json.load(f)
    data = jdata.get("DATA") if isinstance(jdata.get("DATA"), dict) else None

    for campo, clave in _CAMPOS.items():
        if campo not in cambios:
            continue
        valor = _texto(cambios[campo], campo)
        if campo == "modelo":
            if not valor:
                raise ErrorFicha(400, "dato", "El modelo no puede quedar vacío.")
        elif campo == "office":
            valor = _office(valor)
        elif campo == "sn_transf":
            valor = normalizar_sn_transf(valor) or TRANSF_PENDIENTE
            _sin_transformador_repetido(lote, ruta, valor)
        valor = valor or _VACIOS[clave]
        jdata[clave] = valor
        # El HTML lee primero DATA (model, key): se actualiza a la par para
        # que la corrección se vea en el reporte.
        if data is not None and campo == "modelo":
            data["model"] = valor
        if data is not None and campo == "sn_win" and "key" in data:
            data["key"] = valor

    if "hardware" in cambios:
        _aplicar_hardware(jdata, cambios["hardware"])

    if "componentes" in cambios:
        jdata["DETALLE_COMPONENTES"] = _componentes(cambios["componentes"])
        jdata["TIENE_FALLAS"] = any(c["estado"] != "OK" for c in jdata["DETALLE_COMPONENTES"])

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(jdata, f, ensure_ascii=False, indent=4)
    marcar_pendiente_envio(lote)
    regenerar_lote(lote)
    return ficha(lote, jdata.get("SERIAL", serial))


def _sin_transformador_repetido(lote, ruta, sn_transf):
    if sn_transf == TRANSF_PENDIENTE:
        return
    for otra, jdata in equipos_en_orden_de_escaneo(lote):
        if otra != ruta and transformador_actual(jdata).upper() == sn_transf.upper():
            raise ErrorFicha(
                409,
                "duplicado",
                f"El transformador {sn_transf} ya es de {jdata.get('SERIAL', '?')}.",
            )
