"""
Office por OT: la OT de entrega dice con qué Office van sus equipos y, en la
pantalla "Asignar Office", se elige qué caja va con cada notebook.

La app no elige por su cuenta: la caja física que acompaña a cada equipo la
decide quien arma la entrega (escaneándola en su fila). Al guardar, el
número de caja se escribe en el JSON (SN_APP, OFFICE, OFFICE_CAJA) como si se
hubiera cargado a mano, y el HTML y el FUSIONADO se regeneran con él: el
export a Valida lo toma igual. La key no va al reporte: se lee de la base
cuando hace falta (activar, copiarla en "Asignar Office").
"""

import json

from . import licencias_office
from .escaneos import TIPO_EQUIPO_DEFAULT, tipo_equipo
from .lotes import (
    carpeta_lote,
    marcar_pendiente_envio,
    office_en_disco,
    regenerar_lote,
)
from .transformadores import equipos_en_orden_de_escaneo

PENDIENTE = "PENDIENTE"


def version_de(lote):
    """Versión de Office con que va la OT, o '' (sin Office o no es entrega)."""
    if lote.get("mov") != "Entrega":
        return ""
    return office_en_disco(lote["ruta"])


def es_notebook(jdata):
    """Monitores e impresoras no llevan Office."""
    return tipo_equipo(jdata) == TIPO_EQUIPO_DEFAULT


def necesita_office(jdata):
    """Un notebook sin licencia: ni caja asignada ni key cargada a mano."""
    return (
        es_notebook(jdata)
        and not jdata.get("OFFICE_CAJA")
        and jdata.get("SN_APP") in (None, "", PENDIENTE)
    )


def equipos(lote):
    """(ruta, jdata) de los notebooks de la OT, del primero que se escaneó al último."""
    return [(r, j) for r, j in equipos_en_orden_de_escaneo(lote) if es_notebook(j)]


def revisar_codigo(codigo, serial, version_ot=""):
    """
    (estado, texto) de un código escrito en la fila de un equipo, para
    mostrarlo al momento: 'ok', 'aviso' (sirve, pero conviene mirar) o
    'error' (no se va a poder guardar). ('', '') si la celda está vacía.
    """
    if not licencias_office.normalizar_codigo(codigo):
        return "", ""
    lic = licencias_office.buscar(codigo)
    if not lic:
        return "error", "No está en la base"
    if lic["estado"] == licencias_office.DESHABILITADA:
        return "error", "Deshabilitada"
    nombre = f"Office {lic['version'] or '?'}"
    if lic["estado"] == licencias_office.ASIGNADA and lic["serial"] != serial:
        return "aviso", f"Hoy es de {lic['serial'] or lic['cliente'] or 'otro'}"
    if version_ot and lic["version"] != version_ot:
        return "aviso", f"{nombre} (la OT va con {version_ot})"
    # La versión solo se nombra si la OT no la dice: si no, es ruido.
    prefijo = "" if version_ot else f"{nombre} · "
    if lic["estado"] == licencias_office.ASIGNADA:
        return "ok", f"{prefijo}Guardada"
    return "ok", f"{prefijo}Disponible"


def guardar_cajas(lote, filas):
    """
    filas: [(ruta, jdata, código)] de la pantalla. Asigna las cajas elegidas
    (todo junto o nada: licencias_office.reasignar) y actualiza los JSON que
    cambian. Un código vacío deja al equipo sin caja; una key cargada a mano
    sin caja se respeta mientras no se elija una. Regenera HTML y FUSIONADO.
    Devuelve cuántos equipos cambiaron. Lanza ErrorLicencia si algo no se pudo.
    """
    version_ot = version_de(lote)
    pares = {j["SERIAL"]: codigo for _r, j, codigo in filas}
    asignadas = licencias_office.reasignar(
        pares,
        cliente=lote["cliente"],
        documento=carpeta_lote(lote["mov"], lote["numero"]),
        modelos={j["SERIAL"]: j.get("MODELO", "") for _r, j, _c in filas},
    )
    cambiados = 0
    for ruta, jdata, _codigo in filas:
        lic = asignadas.get(jdata["SERIAL"])
        antes = (jdata.get("OFFICE"), jdata.get("SN_APP"), jdata.get("OFFICE_CAJA"))
        if lic:
            jdata["OFFICE"] = f"Office {lic['version'] or version_ot}"
            jdata["SN_APP"] = lic["caja"]
            jdata["OFFICE_CAJA"] = lic["caja"]
        elif jdata.get("OFFICE_CAJA"):
            jdata.pop("OFFICE_CAJA")
            jdata["SN_APP"] = PENDIENTE
            jdata["OFFICE"] = f"Office {version_ot}" if version_ot else "No"
        if (jdata.get("OFFICE"), jdata.get("SN_APP"), jdata.get("OFFICE_CAJA")) == antes:
            continue
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(jdata, f, ensure_ascii=False, indent=4)
        cambiados += 1
    if cambiados:
        marcar_pendiente_envio(lote)
        regenerar_lote(lote)
    return cambiados


def estado(lote):
    """
    {"version", "con_office", "faltan", "disponibles"} para el menú, o None
    si la OT no va con Office. No escribe nada.
    """
    version = version_de(lote)
    if not version:
        return None
    notebooks = [j for _r, j in equipos(lote)]
    faltan = sum(1 for j in notebooks if necesita_office(j))
    return {
        "version": version,
        "con_office": len(notebooks) - faltan,
        "faltan": faltan,
        "disponibles": licencias_office.disponibles(version),
    }


def texto_estado(lote):
    """'Office 2016: 12 con caja · ⚠️ 3 sin caja', o '' si no va con Office."""
    try:
        est = estado(lote)
    except Exception:
        return ""
    if not est:
        return ""
    texto = f"Office {est['version']}: {est['con_office']} con caja"
    if est["faltan"]:
        texto += f" · ⚠️ {est['faltan']} sin caja"
    return texto + f" · quedan {est['disponibles']} disponibles"
