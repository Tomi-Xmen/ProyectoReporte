"""
Carga masiva de transformadores (cargadores) sobre los equipos de la OT.

El transformador se etiqueta aparte del equipo y casi nunca aparece en el
mismo momento: llega después y en bloque, como una columna de Excel o como
una ráfaga de la pistola. De ahí que sea su propio módulo y no un campo del
formulario de escaneo.

La lista va en ORDEN DE ESCANEO (el más viejo arriba, al revés que el resto
de la app): es el orden en que se etiquetaron los equipos, así que es el que
trae la columna pegada y el pegado cae 1-a-1 sobre las filas.
"""

import json

from .lotes import (
    clave_orden,
    leer_equipos_lote_con_ruta,
    marcar_pendiente_envio,
    regenerar_lote,
)
from .reporte_html import TRANSF_PENDIENTE


def normalizar_sn_transf(valor):
    """Serial de transformador utilizable, o '' si la celda quedó vacía."""
    limpio = " ".join(str(valor or "").split())
    return "" if limpio.upper() in ("", TRANSF_PENDIENTE) else limpio


def seriales_del_portapapeles(texto):
    """
    Un serial por línea. Si la línea trae tabs (columna copiada de Excel con
    celdas vecinas) se usa la primera celda no vacía: pegar una columna nunca
    debe convertirse en varios transformadores para el mismo equipo.
    """
    seriales = []
    for linea in texto.replace("\r", "\n").split("\n"):
        celdas = (" ".join(c.split()) for c in linea.split("\t"))
        celda = next((c for c in celdas if c), "")
        if celda:
            seriales.append(celda)
    return seriales



def equipos_en_orden_de_escaneo(lote):
    """
    (ruta, jdata) del lote, el más viejo primero. No alcanza con dar vuelta la
    lista habitual: ESCANEADO tiene resolución de segundos, así que dos
    equipos del mismo segundo empatan y el reverso los deja invertidos entre
    sí. Ordenar ascendente respeta el empate en vez de darlo vuelta.
    """
    return sorted(leer_equipos_lote_con_ruta(lote), key=lambda par: clave_orden(par[1]))


def transformador_actual(jdata):
    return jdata.get("SN_Transf", TRANSF_PENDIENTE) or TRANSF_PENDIENTE


def calcular_cambios(filas):
    """
    filas: [(ruta, jdata, texto_ingresado)]. Devuelve (cambios, duplicados):
    cambios = [(ruta, jdata, nuevo)] solo de las filas que cambian, y
    duplicados = textos legibles de seriales repetidos en más de un equipo.

    Vaciar una celda es un cambio válido: devuelve el equipo a PENDIENTE
    cuando el transformador se cargó por error.
    """
    cambios, vistos, duplicados = [], {}, []
    for ruta, jdata, texto in filas:
        serial_eq = jdata.get("SERIAL", "?")
        nuevo = normalizar_sn_transf(texto) or TRANSF_PENDIENTE
        if nuevo != TRANSF_PENDIENTE:
            clave = nuevo.upper()
            if clave in vistos:
                duplicados.append(f"{nuevo} → {vistos[clave]} y {serial_eq}")
            vistos[clave] = serial_eq
        if nuevo != transformador_actual(jdata):
            cambios.append((ruta, jdata, nuevo))
    return cambios, duplicados


def guardar_transformadores(lote, cambios):
    """
    Escribe SN_Transf en cada JSON y regenera el lote. Devuelve la lista de
    errores (vacía si todo salió bien).

    Cada JSON se relee del disco por si el equipo se re-escaneó mientras la
    ventana estaba abierta: así se pisa solo SN_Transf y no se revierte el
    resto del registro a como estaba al abrir.
    """
    errores = []
    for ruta, jdata_previo, nuevo in cambios:
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                jdata = json.load(fh)
            if not isinstance(jdata, dict):
                jdata = jdata_previo
        except Exception:
            jdata = jdata_previo
        jdata["SN_Transf"] = nuevo
        try:
            with open(ruta, "w", encoding="utf-8") as fh:
                json.dump(jdata, fh, ensure_ascii=False, indent=4)
        except Exception as e:
            errores.append(f"{jdata.get('SERIAL', '?')}: {e}")

    marcar_pendiente_envio(lote)
    regenerar_lote(lote)
    return errores
