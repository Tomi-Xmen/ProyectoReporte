"""
Gestión de un lote desde el celular: lo que antes había que hacer en el PC
(o no se podía hacer). Elegir a qué equipo va un cargador y pasarlo de uno a
otro, mover o quitar equipos, completar el segundo documento del lote en
todos sus equipos, y cerrarlo.

Escribe con las funciones de lotes/transformadores tal como están; lo que
agrega es el control (que el equipo exista, que el destino no lo tenga ya) y
respuestas claras para el celular. Igual que el resto, todo termina en los
JSON del lote y en un HTML/FUSIONADO regenerado.
"""

import json
import os
import re
import shutil
from datetime import datetime

from .escaneos import TIPO_EQUIPO_DEFAULT, normalizar_lectura, tipo_equipo
from .lotes import (
    MOV_CFG,
    carpeta_lote,
    cerrar_lote,
    contar_equipos,
    crear_backup,
    es_activo,
    etiqueta_lote,
    guardar_lote_activo,
    guardar_meta_lote,
    leer_equipos_lote_con_ruta,
    marcar_pendiente_envio,
    mover_equipos_a_lote,
    normalizar_numero,
    numeros_lote,
    regenerar_lote,
    ruta_reportes,
    son_el_mismo_lote,
)
from .reporte_html import TRANSF_PENDIENTE
from .sincronizacion import registrar_quitado
from .transformadores import (
    equipos_en_orden_de_escaneo,
    guardar_transformadores,
    normalizar_sn_transf,
    transformador_actual,
)

# Lo quitado de un lote no se borra: va acá, fuera de ENTREGA/RETIROS para
# que ningún recorrido lo tome por un cliente u OT, igual que _BACKUPS.
CARPETA_PAPELERA = "_PAPELERA"


class ErrorGestion(Exception):
    def __init__(self, codigo, error, mensaje):
        super().__init__(mensaje)
        self.codigo, self.error, self.mensaje = codigo, error, mensaje


def _clave(texto):
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def _buscar(lote, serial):
    """(ruta, jdata) del equipo con ese serial en el lote, o None."""
    clave = _clave(serial)
    for ruta, jdata in equipos_en_orden_de_escaneo(lote):
        if _clave(jdata.get("SERIAL", "")) == clave:
            return ruta, jdata
    return None


def _equipo(lote, serial):
    encontrado = _buscar(lote, serial)
    if not encontrado:
        raise ErrorGestion(404, "equipo", f"{serial} no está en {etiqueta_lote(lote)}.")
    return encontrado


# ─────────────────────────────────────────────────────────
#  Cargadores
# ─────────────────────────────────────────────────────────
def _limpiar_sn(sn_transf):
    return normalizar_sn_transf(normalizar_lectura(sn_transf))


def portador(lote, sn_transf):
    """(ruta, jdata) del equipo que ya tiene ese cargador, o None."""
    clave = sn_transf.upper()
    return next(
        (par for par in equipos_en_orden_de_escaneo(lote) if transformador_actual(par[1]).upper() == clave),
        None,
    )


def leer_transformador(lote, sn_transf):
    """
    Primer paso de "escaneo el cargador y elijo el equipo": no asigna nada,
    solo dice qué serial se leyó y de qué equipo es hoy (None si de ninguno).
    """
    nuevo = _limpiar_sn(sn_transf)
    if not nuevo:
        return {"estado": "invalido", "motivo": "Serial de transformador vacío."}
    actual = portador(lote, nuevo)
    return {
        "estado": "leido",
        "sn_transf": nuevo,
        "equipo": actual[1].get("SERIAL", "?") if actual else None,
    }


def reasignar_transformador(lote, sn_transf, serial_equipo):
    """
    Pone el cargador en ESE equipo aunque hoy sea de otro: se lo saca al
    anterior (que queda sin cargador) en el mismo guardado. Si el equipo
    destino tenía otro cargador, ese queda libre ('reemplazo').
    """
    nuevo = _limpiar_sn(sn_transf)
    if not nuevo:
        return {"estado": "invalido", "motivo": "Serial de transformador vacío."}
    destino = _buscar(lote, serial_equipo)
    if not destino:
        return {"estado": "equipo_no_encontrado", "serial": serial_equipo}

    ruta_destino, jdata_destino = destino
    serial_destino = jdata_destino.get("SERIAL", "?")
    anterior = portador(lote, nuevo)
    if anterior and anterior[0] == ruta_destino:
        return {"estado": "ya_estaba", "sn_transf": nuevo, "equipo": serial_destino}

    cambios = []
    if anterior:
        cambios.append((anterior[0], anterior[1], TRANSF_PENDIENTE))
    reemplazo = transformador_actual(jdata_destino)
    cambios.append((ruta_destino, jdata_destino, nuevo))
    errores = guardar_transformadores(lote, cambios)
    if errores:
        raise OSError(errores[0])
    return {
        "estado": "asignado",
        "sn_transf": nuevo,
        "equipo": serial_destino,
        "reemplazo": None if reemplazo == TRANSF_PENDIENTE else reemplazo,
        "desde": anterior[1].get("SERIAL", "?") if anterior else None,
    }


# ─────────────────────────────────────────────────────────
#  Equipos
# ─────────────────────────────────────────────────────────
def mover_equipo(origen, serial, destino):
    """Pasa un equipo a otro lote abierto, con su cargador y todo lo cargado."""
    _ruta, jdata = _equipo(origen, serial)
    serial_real = jdata.get("SERIAL", serial)
    if son_el_mismo_lote(origen, destino):
        raise ErrorGestion(400, "mismo_lote", "El destino es el mismo lote.")
    if _buscar(destino, serial_real):
        raise ErrorGestion(409, "ya_esta", f"{serial_real} ya está en {etiqueta_lote(destino)}.")
    mover_equipos_a_lote(origen, [serial_real], destino)
    return {
        "estado": "movido",
        "serial": serial_real,
        "destino": etiqueta_lote(destino),
        "total": contar_equipos(origen["ruta"]),
    }


def ruta_papelera(lote):
    return os.path.join(
        ruta_reportes(),
        CARPETA_PAPELERA,
        MOV_CFG[lote["mov"]]["grupo"],
        lote["cliente"],
        carpeta_lote(lote["mov"], lote["numero"]),
    )


def quitar_equipo(lote, serial):
    """
    Saca un equipo del lote. No lo borra: su JSON va a _PAPELERA con la fecha
    en el nombre (y sin extensión .json, para que nada lo tome por un
    equipo). Para devolverlo basta copiarlo de vuelta sacándole ese final.
    """
    ruta, jdata = _equipo(lote, serial)
    papelera = ruta_papelera(lote)
    os.makedirs(papelera, exist_ok=True)
    nombre = os.path.basename(ruta)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Antes de moverlo: el traer automático de clonación no lo tiene que
    # volver a bajar del servidor.
    registrar_quitado(lote["ruta"], nombre, ruta)
    shutil.move(ruta, os.path.join(papelera, f"{nombre}.quitado-{sello}"))
    marcar_pendiente_envio(lote)
    return {
        "estado": "quitado",
        "serial": jdata.get("SERIAL", serial),
        "total": regenerar_lote(lote),
    }


# ─────────────────────────────────────────────────────────
#  Lote
# ─────────────────────────────────────────────────────────
def fijar_documento_secundario(lote, numero_sec):
    """
    Carga o corrige el documento que la carpeta no codifica (la guía de una
    entrega, la OT de un retiro) y lo aplica a TODOS los equipos del lote, no
    solo a los que se escaneen después. Vacío lo borra. Devuelve el lote.
    """
    texto = str(numero_sec or "").strip()
    sec = normalizar_numero(texto, lote["mov"]) if texto else ""
    if texto and not sec:
        raise ErrorGestion(
            400, "dato", "Número inválido.\n\nSolo letras, números, '-' y '_'."
        )
    lote = dict(lote, numero_sec=sec)
    guardar_meta_lote(lote)

    num_ot, num_guia = numeros_lote(lote)
    for ruta, jdata in leer_equipos_lote_con_ruta(lote):
        if (jdata.get("OT_ID"), jdata.get("GUIA_ID")) == (num_ot, num_guia):
            continue
        jdata["OT_ID"], jdata["GUIA_ID"] = num_ot, num_guia
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(jdata, f, ensure_ascii=False, indent=4)

    # Si es la OT activa del PC, lo que se escanee ahí también tiene que
    # salir con el número nuevo.
    if es_activo(lote):
        guardar_lote_activo(lote)
    marcar_pendiente_envio(lote)
    regenerar_lote(lote)
    return lote


def resumen_cierre(lote):
    """Lo que conviene mirar antes de cerrar: cargadores, fallas y el segundo documento."""
    equipos = [jdata for _, jdata in leer_equipos_lote_con_ruta(lote)]
    sin_cargador = [
        jdata.get("SERIAL", "?")
        for jdata in equipos
        if tipo_equipo(jdata) == TIPO_EQUIPO_DEFAULT
        and transformador_actual(jdata) == TRANSF_PENDIENTE
    ]
    falta = None
    if not (lote.get("numero_sec") or "").strip():
        falta = "guía" if lote["mov"] == "Entrega" else "OT"
    return {
        "etiqueta": etiqueta_lote(lote),
        "equipos": len(equipos),
        "sin_cargador": sin_cargador,
        "con_fallas": sum(1 for jdata in equipos if jdata.get("TIENE_FALLAS")),
        "falta_documento": falta,
    }


def cerrar(lote):
    """Lo mismo que "Cerrar OT" del PC: cierre y backup."""
    total, _malos = cerrar_lote(lote)
    backup = crear_backup("cierre")
    return {
        "estado": "cerrado",
        "etiqueta": etiqueta_lote(lote),
        "total": total,
        "backup": os.path.basename(backup) if backup else None,
    }
