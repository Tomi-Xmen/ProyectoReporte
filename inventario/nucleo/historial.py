"""
Buscador de series: dónde estuvo un equipo, en todas las OT y guías de esta
PC (abiertas, cerradas y lo quitado a mano), y su reporte HTML.

La historia sale de los JSON de siempre, no de un registro aparte: cada OT o
guía en que aparece un serial es un paso de su historial (entregado a un
cliente, retirado, vuelto a entregar). Por eso el historial es por OT y no
por escaneo: re-escanear un equipo dentro de la misma OT pisa su registro,
y moverlo de OT lo deja solo en la de destino.

Leer todos los JSON en cada búsqueda es instantáneo con cientos de equipos y
sigue en torno al segundo con miles; si algún día hiciera falta, un índice
se agrega acá sin cambiar quién llama.
"""

import html
import json
import os
import re
from datetime import datetime

from . import licencias_office
from .escaneos import normalizar_lectura
from .gestion_lote import CARPETA_PAPELERA
from .lotes import (
    MOV_CFG,
    clave_orden,
    esta_cerrado,
    hacer_lote,
    numero_sec_en_disco,
    ruta_reportes,
)
from .reporte_html import HTML_END, HTML_START, fijar_total_count, reconstruir_entry_desde_json

MINIMO_PARCIAL = 4
CARPETA_CONSULTAS = "_CONSULTAS"

ABIERTA = "abierta"
CERRADA = "cerrada"
QUITADO = "quitado"
SIN_OT = "sin OT"


def clave_serial(texto):
    """Serial para comparar: lo que se lee con la pistola, en mayúsculas y solo letras y números."""
    return re.sub(r"[^A-Z0-9]", "", normalizar_lectura(texto))


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            jdata = json.load(f)
    except (OSError, ValueError):
        return None
    return jdata if isinstance(jdata, dict) and jdata.get("SERIAL") else None


def _registros():
    """
    (ruta del JSON, jdata, contexto) de cada equipo guardado en esta PC:
    las OT y guías de ENTREGA y RETIROS, los registros del modelo viejo
    sueltos en la carpeta del cliente y lo quitado a _PAPELERA.
    """
    base = ruta_reportes()
    for mov, cfg in MOV_CFG.items():
        raiz = os.path.join(base, cfg["grupo"])
        if not os.path.isdir(raiz):
            continue
        pref = cfg["prefijo"] + "-"
        for cliente in sorted(os.listdir(raiz)):
            ruta_cliente = os.path.join(raiz, cliente)
            if not os.path.isdir(ruta_cliente):
                continue
            for nombre in sorted(os.listdir(ruta_cliente)):
                ruta = os.path.join(ruta_cliente, nombre)
                if os.path.isdir(ruta):
                    numero = nombre[len(pref):] if nombre.startswith(pref) else nombre
                    contexto = {
                        "mov": mov,
                        "cliente": cliente,
                        "documento": nombre,
                        "carpeta": ruta,
                        "estado": CERRADA if esta_cerrado(ruta) else ABIERTA,
                        "lote": hacer_lote(
                            mov, cliente, numero, ruta=ruta, numero_sec=numero_sec_en_disco(ruta)
                        ),
                    }
                    for archivo in sorted(os.listdir(ruta)):
                        if archivo.endswith(".json") and not archivo.endswith("_FUSIONADO.json"):
                            yield os.path.join(ruta, archivo), contexto
                elif nombre.endswith(".json") and not nombre.endswith("_FUSIONADO.json"):
                    yield ruta, {
                        "mov": mov, "cliente": cliente, "documento": "", "carpeta": ruta_cliente,
                        "estado": SIN_OT, "lote": None,
                    }

    # Lo quitado a mano: <_PAPELERA>/<GRUPO>/<CLIENTE>/<OT>/<archivo>.json.quitado-<fecha>
    papelera = os.path.join(base, CARPETA_PAPELERA)
    grupos = {cfg["grupo"]: mov for mov, cfg in MOV_CFG.items()}
    for raiz, _dirs, archivos in os.walk(papelera):
        partes = os.path.relpath(raiz, papelera).split(os.sep)
        if len(partes) != 3 or partes[0] not in grupos:
            continue
        for archivo in sorted(archivos):
            if ".json.quitado-" in archivo:
                yield os.path.join(raiz, archivo), {
                    "mov": grupos[partes[0]], "cliente": partes[1], "documento": partes[2],
                    "carpeta": raiz, "estado": QUITADO, "lote": None,
                    "quitado": archivo.rsplit(".quitado-", 1)[1],
                }


def _aparicion(ruta, jdata, contexto):
    fecha = clave_orden(jdata)
    if not fecha and contexto.get("quitado"):
        fecha = datetime.strptime(contexto["quitado"], "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
    return {
        **contexto,
        "serial": str(jdata["SERIAL"]).strip(),
        "fecha": fecha,
        "ruta": ruta,
        "jdata": jdata,
    }


def buscar(texto):
    """
    Series que coinciden con lo buscado, la exacta primero:
    [{"serial", "registros", "ultima" (fecha ISO), "cliente"}].
    Con menos de MINIMO_PARCIAL caracteres solo vale la serie exacta.
    """
    buscado = clave_serial(texto)
    if not buscado:
        return []
    parcial = len(buscado) >= MINIMO_PARCIAL
    series = {}
    for ruta, contexto in _registros():
        jdata = _leer(ruta)
        if jdata is None:
            continue
        clave = clave_serial(jdata["SERIAL"])
        if clave != buscado and not (parcial and buscado in clave):
            continue
        a = _aparicion(ruta, jdata, contexto)
        s = series.setdefault(clave, {"serial": a["serial"], "registros": 0, "ultima": "", "cliente": ""})
        s["registros"] += 1
        if a["fecha"] >= s["ultima"]:
            s["ultima"], s["cliente"] = a["fecha"], a["cliente"].replace("_", " ")
    return sorted(
        series.values(),
        key=lambda s: (clave_serial(s["serial"]) != buscado, -_orden(s["ultima"]), s["serial"]),
    )


def _orden(fecha):
    """Fecha ISO como número para ordenar de la más nueva a la más vieja ('' al final)."""
    return int(re.sub(r"\D", "", fecha)[:14] or 0)


def historial(serial):
    """
    Cada aparición del equipo, de la más reciente a la más vieja: contexto
    (movimiento, cliente, OT/guía, estado, carpeta), fecha, ruta y su JSON.
    """
    buscado = clave_serial(serial)
    apariciones = []
    for ruta, contexto in _registros():
        jdata = _leer(ruta)
        if jdata is not None and clave_serial(jdata["SERIAL"]) == buscado:
            apariciones.append(_aparicion(ruta, jdata, contexto))
    apariciones.sort(key=lambda a: _orden(a["fecha"]), reverse=True)
    return apariciones


def office_del_equipo(serial):
    """
    Cajas de Office que tuvo el equipo según la base de licencias, la actual
    primero: [{"caja", "version", "estado", "desde"}]. [] si no hay base.
    """
    if not licencias_office.existe_base():
        return []
    serial = str(serial).strip()
    cajas = []
    actual = licencias_office.caja_de_equipo(serial)
    if actual:
        cajas.append(
            {"caja": actual["caja"], "version": actual["version"], "estado": "actual",
             "desde": (actual["asignada"] or "")[:10]}
        )
    for caja, fecha in licencias_office.cajas_del_serial(serial):
        if actual and caja == actual["caja"]:
            continue
        lic = licencias_office.buscar(caja) or {"version": ""}
        cajas.append({"caja": caja, "version": lic["version"], "estado": "anterior", "desde": fecha[:10]})
    return cajas


# ─────────────────────────────────────────────────────────
#  Reporte HTML del equipo
# ─────────────────────────────────────────────────────────
def _fecha_legible(fecha):
    try:
        return datetime.fromisoformat(fecha).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return fecha or "—"


def _documentos(a):
    j = a["jdata"]
    return j.get("OT_ID", "—"), j.get("GUIA_ID", "—")


def _linea_de_tiempo(apariciones):
    filas = "".join(
        "<tr>"
        f"<td>{html.escape(_fecha_legible(a['fecha']))}</td>"
        f"<td><b>{html.escape(a['mov'])}</b></td>"
        f"<td>{html.escape(a['cliente'].replace('_', ' '))}</td>"
        f"<td>{html.escape(str(_documentos(a)[0]))}</td>"
        f"<td>{html.escape(str(_documentos(a)[1]))}</td>"
        f"<td>{html.escape(a['estado'])}</td>"
        "</tr>"
        for a in apariciones
    )
    return (
        '<div style="margin:0 0 18px;padding:14px 18px;background:#fff;border-radius:12px;'
        'border:1px solid #e2e8f0">'
        '<h3 style="margin:0 0 10px;font-size:15px;color:#1a3c6e">🕓 Historial</h3>'
        "<table><tr><th>Fecha</th><th>Movimiento</th><th>Cliente</th><th>N° de OT</th>"
        f"<th>N° de Guía</th><th>Estado</th></tr>{filas}</table></div>"
    )


def html_equipo(serial, apariciones):
    """
    Reporte HTML con el historial del equipo: la línea de tiempo y, debajo,
    el bloque de siempre por cada aparición. Usa la misma plantilla que las
    OT, así que copiar a Valida, el CSV y las etiquetas funcionan igual.
    """
    titulo = f"Historial {serial}"
    contenido = HTML_START.replace(
        "Inventario Maestro de Equipos", f"Historial del equipo {html.escape(serial)}"
    ).replace("<title>Inventario Maestro</title>", f"<title>{html.escape(titulo)}</title>")
    contenido += _linea_de_tiempo(apariciones)
    for i, a in enumerate(apariciones, start=1):
        entrada = reconstruir_entry_desde_json(a["jdata"])
        # El mismo serial aparece varias veces: sin numerar, los botones de
        # quitar y de etiqueta de un bloque actuarían sobre otro.
        safe_id = f"dev-{re.sub(r'[^a-zA-Z0-9]', '', str(a['jdata'].get('SERIAL', ''))) or 'DESCONOCIDO'}"
        contenido += entrada.replace(safe_id, f"{safe_id}-{i}") + "\n"
    contenido += HTML_END
    return fijar_total_count(contenido, len(apariciones))


def guardar_html(serial, apariciones):
    """
    Escribe el reporte en Reportes_Guardados/_CONSULTAS (fuera de ENTREGA y
    RETIROS: no es una OT, no se envía ni entra en los respaldos) y devuelve
    su ruta.
    """
    carpeta = os.path.join(ruta_reportes(), CARPETA_CONSULTAS)
    os.makedirs(carpeta, exist_ok=True)
    limpio = re.sub(r"[^A-Za-z0-9]", "", serial) or "SINSERIE"
    ruta = os.path.join(
        carpeta, f"Historial_{limpio}_{datetime.now():%Y%m%d-%H%M%S}.html"
    )
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(html_equipo(serial, apariciones))
    return ruta
