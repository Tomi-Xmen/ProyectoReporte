"""
Reconstrucción — rearmar el HTML y el FUSIONADO a partir de los JSON
guardados. Funciona recursivamente: se puede apuntar a una OT, a un cliente
(con todas sus OT) o a ENTREGA/ completo.
"""

import json
import os
from datetime import datetime

from .lotes import (
    MOV_CFG,
    clave_orden,
    etiqueta_lote,
    hacer_lote,
    numero_sec_en_disco,
    regenerar_lote,
)
from .reporte_html import (
    HTML_END,
    HTML_START,
    fijar_total_count,
    reconstruir_entry_desde_json,
    resumen_fusionado,
)


def _lote_desde_ruta(ruta):
    """
    Deduce el lote de una carpeta con forma de OT: <CLIENTE>/<PREFIJO-NUMERO>.
    Devuelve None si es una carpeta cualquiera con JSON sueltos.

    No se exige el nivel de grupo (ENTREGA/RETIROS): una OT bajada del servidor
    puede llegar sin sus carpetas padre, y el prefijo de la carpeta —OT- o
    GUIA-— ya identifica el movimiento sin ambigüedad. Sin esto una OT
    recuperada se reconstruía como "carpeta suelta": HTML aparte, sin FUSIONADO
    y sin quedar integrada al árbol.
    """
    ruta = os.path.normpath(os.path.abspath(ruta))
    nombre = os.path.basename(ruta)
    cliente = os.path.basename(os.path.dirname(ruta))
    if not cliente:
        return None

    for mov, cfg in MOV_CFG.items():
        pref = cfg["prefijo"] + "-"
        if nombre.startswith(pref) and nombre[len(pref):]:
            return hacer_lote(
                mov,
                cliente,
                nombre[len(pref):],
                ruta=ruta,
                numero_sec=numero_sec_en_disco(ruta),
            )
    return None


def _carpetas_con_equipos(raiz):
    """Carpetas que contienen JSON de equipos, recursivo (incluida la raíz)."""
    encontradas = []
    for actual, _dirs, archivos in os.walk(raiz):
        if any(
            a.endswith(".json")
            and not a.endswith("_FUSIONADO.json")
            and not a.startswith(".")
            for a in archivos
        ):
            encontradas.append(actual)
    return sorted(encontradas)


def _cliente_dominante(equipos):
    """
    Cliente que aparece en más JSON del grupo. El JS del reporte saca de ahí el
    nombre de los archivos que descarga (nombreBaseReporte lee el <title>), así
    que usar el cliente real y no el nombre de la carpeta hace que el CSV y el
    fusionado exportados salgan con el mismo nombre que si los hubiera generado
    el escaneo.
    """
    conteo = {}
    for eq in equipos:
        cli = (eq.get("CLIENTE") or "").strip()
        if cli:
            conteo[cli] = conteo.get(cli, 0) + 1
    return max(conteo, key=conteo.get) if conteo else ""


def _reconstruir_carpeta_suelta(carpeta):
    """
    Rearma el HTML de una carpeta que NO pertenece al árbol de OT (por ejemplo
    JSON bajados del servidor a un directorio cualquiera). Agrupa por movimiento
    y escribe archivos '_RECONSTRUIDO.html' sin tocar nada más.
    Devuelve (generados, equipos, errores).

    El HTML sale con las mismas funcionalidades que el original: mismos
    HTML_START/HTML_END (copiar filas, CSV, fusionado, etiquetas), cada equipo
    con su data-comps y data-fusion, y un <title> con el cliente real para que
    las descargas salgan con el nombre correcto.
    """
    equipos_por_tipo = {"Entregas": [], "Retiros": []}
    errores = []

    for archivo in sorted(os.listdir(carpeta)):
        if not archivo.endswith(".json") or archivo.startswith("."):
            continue
        try:
            with open(os.path.join(carpeta, archivo), "r", encoding="utf-8") as f:
                jdata = json.load(f)
            # El fusionado (lista de equipos) ya está cubierto por los JSON
            # individuales; se ignora para no duplicar.
            if isinstance(jdata, list):
                continue
            # Basta el SERIAL: un registro sin DATA todavía sirve —el resto de
            # las filas se rearman desde el nivel superior del JSON— y
            # descartarlo dejaría al equipo fuera del reporte, que es justo lo
            # que hay que evitar al reconstruir.
            if not isinstance(jdata, dict) or not jdata.get("SERIAL"):
                errores.append(f"{archivo}: sin SERIAL, no es un JSON de equipo")
                continue
            if not jdata.get("DATA"):
                errores.append(
                    f"{archivo}: sin DATA — reconstruido desde el nivel superior "
                    "(puede faltar detalle de hardware)"
                )
            mov = jdata.get("TIPO_MOVIMIENTO", "Entrega")
            equipos_por_tipo["Entregas" if mov == "Entrega" else "Retiros"].append(jdata)
        except Exception as e:
            errores.append(f"{archivo}: {e}")

    nombre_carpeta = os.path.basename(os.path.normpath(carpeta))
    fecha_hoy = datetime.now().strftime("%Y%m%d")
    generados = []
    total = 0

    for tipo, equipos in equipos_por_tipo.items():
        if not equipos:
            continue
        equipos.sort(key=clave_orden, reverse=True)
        etiqueta = (_cliente_dominante(equipos) or nombre_carpeta).replace("_", " ")
        titulo = f"{tipo} - {etiqueta}"
        contenido = HTML_START.replace("Inventario Maestro de Equipos", titulo).replace(
            "<title>Inventario Maestro</title>", f"<title>{titulo}</title>"
        )

        entries = []
        for jdata in equipos:
            try:
                entries.append(reconstruir_entry_desde_json(jdata))
            except Exception as e:
                errores.append(f"S/N {jdata.get('SERIAL', '?')}: {e}")

        contenido += "\n".join(entries) + HTML_END
        contenido = fijar_total_count(contenido, len(entries))

        base = f"Reporte_{tipo}_{nombre_carpeta}_{fecha_hoy}_RECONSTRUIDO"
        with open(os.path.join(carpeta, base + ".html"), "w", encoding="utf-8") as f:
            f.write(contenido)
        generados.append(base + ".html")

        # El fusionado también se deja en disco: es lo que se sube a los
        # sistemas y no debería depender de que alguien abra el HTML y aprete
        # el botón de descarga.
        with open(
            os.path.join(carpeta, base + "_FUSIONADO.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                [resumen_fusionado(eq) for eq in equipos],
                f,
                ensure_ascii=False,
                indent=4,
            )
        generados.append(base + "_FUSIONADO.json")

        total += len(entries)

    return generados, total, errores



def carpetas_a_reconstruir(raiz):
    """Carpetas con JSON de equipos dentro de 'raiz' (incluida ella misma)."""
    return _carpetas_con_equipos(raiz)


def reconstruir_carpetas(carpetas):
    """
    Si la carpeta pertenece al árbol de reportes se regenera el lote CANÓNICO
    (mismo HTML y mismo FUSIONADO que produce el escaneo, sin archivos
    sueltos); si es una carpeta cualquiera, se escribe un '_RECONSTRUIDO.html'
    aparte.

    Aquí sí se leen carpetas cerradas: el usuario las eligió a propósito. El
    marcador '.cerrado' gobierna los recorridos automáticos, no esto.

    Devuelve (total, regenerados, sueltos, errores).
    """
    regenerados, sueltos, errores, total = [], [], [], 0
    for sub in carpetas:
        lote = _lote_desde_ruta(sub)
        try:
            if lote:
                n = regenerar_lote(lote)
                total += n
                regenerados.append(f"{etiqueta_lote(lote)} — {n} equipo(s)")
            else:
                generados, n, errs = _reconstruir_carpeta_suelta(sub)
                total += n
                errores.extend(errs)
                sueltos.extend(generados)
        except Exception as e:
            errores.append(f"{os.path.basename(sub)}: {e}")
    return total, regenerados, sueltos, errores
