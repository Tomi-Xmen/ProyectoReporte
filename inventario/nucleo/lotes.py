"""
Persistencia — modelo de LOTES por OT / guía.

Un LOTE es (cliente, movimiento, número de documento) y vive en su propia
carpeta desde el PRIMER escaneo, no al final:

    Reportes_Guardados/ENTREGA/<CLIENTE>/OT-553/      (entregas: manda la OT)
    Reportes_Guardados/RETIROS/<CLIENTE>/GUIA-8891/   (retiros: manda la guía)

El movimiento lo define el lote, no cada equipo. Los JSON individuales se
escriben directo en esa carpeta; el HTML y el JSON FUSIONADO son DERIVADOS:
se regeneran completos desde los JSON en cada guardado. Por eso una OT puede
trabajarse durante varios días y el fusionado siempre queda con TODO adentro,
listo para subir al sistema.

Una OT está ABIERTA mientras no tenga el marcador '.cerrado'. Ese marcador es
lo que permite ignorar las miles de carpetas ya finalizadas sin abrir ni un
archivo: basta un stat por carpeta.

RESPALDO: crear_backup() comprime ENTREGA/ y RETIROS/ enteras en un ZIP con
fecha y hora bajo _BACKUPS/. Se dispara solo en los dos momentos críticos —
al cerrar una OT y antes de subir al NAS — y va fuera de ENTREGA/RETIROS para
no aparecer como un cliente/OT falso en los recorridos.

Nada de este módulo habla con la interfaz: devuelve datos o lanza, y la UI
decide qué preguntar y qué mostrar.
"""

import json
import os
import re
import zipfile
from datetime import datetime

from .reporte_html import (
    HTML_END,
    HTML_START,
    fijar_total_count,
    reconstruir_entry_desde_json,
    resumen_fusionado,
)


# Configuración por tipo de movimiento. Cada uno tiene su carpeta raíz, el
# rótulo del documento y el prefijo de la carpeta del lote.
MOV_CFG = {
    "Entrega": {
        "tipo_doc": "Entregas",
        "grupo": "ENTREGA",
        "prefijo": "OT",  # carpeta del lote: OT-553
        "etiqueta_id": "Orden",  # rótulo del ID en el nombre del HTML
        "etiqueta_campo": "N° de Orden de Trabajo (OT)",
        # El otro documento del lote, el que NO da nombre a la carpeta.
        "etiqueta_campo_sec": "N° de Guía de Despacho",
    },
    "Retiro": {
        "tipo_doc": "Retiros",
        "grupo": "RETIROS",
        "prefijo": "GUIA",
        "etiqueta_id": "Guia",
        "etiqueta_campo": "N° de Guía de Retiro",
        "etiqueta_campo_sec": "N° de Orden de Trabajo (OT)",
    },
}

# Marcador de lote finalizado. Su sola presencia significa "aquí no hay nada
# que procesar": los recorridos automáticos se saltan la carpeta sin leerla.
MARCADOR_CERRADO = ".cerrado"

# Marcador local (no se sube al NAS) que indica que la carpeta YA fue enviada a
# la red. Va por OT, no por cliente: así agregar un equipo a una OT no obliga a
# re-subir las miles de carpetas del cliente.
MARCADOR_ENVIADO = ".enviado"

# Puntero al lote activo (el que recibe los equipos escaneados).
ARCHIVO_LOTE_ACTIVO = ".lote_activo.json"

# Metadatos guardados DENTRO de la carpeta del lote. Existen porque la ruta
# codifica un solo número (el que nombra la carpeta) y el segundo documento
# —la guía de una entrega, la OT de un retiro— no se puede deducir de ella.
# Sin extensión .json a propósito: contar_equipos() cuenta los .json sueltos
# de la carpeta y este archivo no es un equipo.
ARCHIVO_META_LOTE = ".lote"

_RESERVADOS_WIN = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def ruta_reportes():
    return os.path.join(os.getcwd(), "Reportes_Guardados")


def normalizar_numero(valor, mov="Entrega"):
    """
    Sanea el número de OT/guía para usarlo como nombre de carpeta: mayúsculas,
    sin caracteres inválidos de ruta y sin el prefijo si el usuario lo escribió
    ("OT 553", "ot-553" y "553" dan todos "553"). Devuelve "" si no queda nada
    usable o si cae en un nombre reservado de Windows (CON, AUX, COM1…).
    """
    n = str(valor).strip().upper()
    n = re.sub(r"^(OT|GUIA|GUÍA)[\s\-_.:#]*", "", n)
    n = re.sub(r"[^A-Z0-9\-_]", "-", n)
    n = re.sub(r"-{2,}", "-", n).strip("-_")[:30]
    if not n or n in _RESERVADOS_WIN:
        return ""
    return n


def carpeta_lote(mov, numero):
    return f"{MOV_CFG[mov]['prefijo']}-{numero}"


def ruta_lote(mov, cliente, numero):
    return os.path.join(
        ruta_reportes(), MOV_CFG[mov]["grupo"], cliente, carpeta_lote(mov, numero)
    )


def hacer_lote(mov, cliente, numero, ruta=None, numero_sec=""):
    """
    Descriptor de lote que circula por toda la app.

    'numero' es el documento que identifica el lote y da nombre a la carpeta:
    la OT en una entrega, la guía en un retiro. 'numero_sec' es el OTRO
    documento, el que la ruta no codifica; puede ir vacío si aún no se conoce.
    """
    return {
        "mov": mov,
        "cliente": cliente,
        "numero": numero,
        "numero_sec": (numero_sec or "").strip(),
        "ruta": ruta or ruta_lote(mov, cliente, numero),
    }


def numeros_lote(lote):
    """
    (OT, guía) del lote como par explícito. Cuál de los dos nombra la carpeta
    depende del movimiento: una entrega se archiva por OT y un retiro por guía,
    así que el otro sale de 'numero_sec' y puede no estar cargado todavía.
    """
    otro = (lote.get("numero_sec") or "").strip()
    if lote["mov"] == "Entrega":
        return lote["numero"], otro or "Sin Guía"
    return otro or "Sin Orden", lote["numero"]


def guardar_meta_lote(lote):
    """Deja en la carpeta del lote el número que la ruta no puede codificar."""
    try:
        os.makedirs(lote["ruta"], exist_ok=True)
        ruta = os.path.join(lote["ruta"], ARCHIVO_META_LOTE)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"numero_sec": lote.get("numero_sec", "")}, f, ensure_ascii=False)
    except Exception:
        pass


def leer_meta_lote(ruta):
    """Metadatos del lote guardados en su carpeta. {} si no hay o no se pudo."""
    try:
        with open(os.path.join(ruta, ARCHIVO_META_LOTE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def numero_sec_en_disco(ruta):
    return (leer_meta_lote(ruta).get("numero_sec") or "").strip()


def etiqueta_lote(lote):
    """Rótulo corto para la UI: 'ACME · OT-553 · ENTREGAS'."""
    cfg = MOV_CFG[lote["mov"]]
    return (
        f"{lote['cliente'].replace('_', ' ')} · "
        f"{carpeta_lote(lote['mov'], lote['numero'])} · {cfg['tipo_doc'].upper()}"
    )


# ─────────────────────────────────────────────────────────
#  Estado de un lote: abierto / cerrado
# ─────────────────────────────────────────────────────────
def esta_cerrado(ruta):
    return os.path.exists(os.path.join(ruta, MARCADOR_CERRADO))


def leer_cerrado(ruta):
    """Metadatos del cierre (cliente, número, nº de equipos, fecha). {} si no."""
    try:
        with open(os.path.join(ruta, MARCADOR_CERRADO), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def marcar_cerrado(lote, equipos):
    """
    Escribe '.cerrado' con un resumen. Lleva metadatos a propósito: permite
    saber qué hay en una OT (cliente, número, cuántos equipos) sin abrir
    ninguno de sus JSON.
    """
    meta = {
        "cliente": lote["cliente"],
        "movimiento": lote["mov"],
        "numero": lote["numero"],
        "numero_sec": lote.get("numero_sec", ""),
        "equipos": equipos,
        "cerrado": datetime.now().isoformat(timespec="seconds"),
    }
    with open(
        os.path.join(lote["ruta"], MARCADOR_CERRADO), "w", encoding="utf-8"
    ) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def reabrir_lote(lote):
    """
    Vuelve a poner en curso una OT ya cerrada: borra '.cerrado' y también
    '.enviado', para que lo que se agregue se re-sincronice con el NAS.
    """
    for marcador in (MARCADOR_CERRADO, MARCADOR_ENVIADO):
        ruta = os.path.join(lote["ruta"], marcador)
        if os.path.exists(ruta):
            try:
                os.remove(ruta)
            except Exception:
                pass


def contar_equipos(ruta):
    """Equipos de un lote = sus JSON individuales (el FUSIONADO no cuenta)."""
    try:
        return sum(
            1
            for a in os.listdir(ruta)
            if a.endswith(".json") and not a.endswith("_FUSIONADO.json")
        )
    except Exception:
        return 0


def listar_lotes_abiertos():
    """
    Lotes SIN '.cerrado', ordenados por actividad reciente. De las OT cerradas
    —que son la mayoría— no abre ningún archivo: solo hace stat de la carpeta.
    De las abiertas lee además su '.lote', que trae el número secundario.
    """
    base = ruta_reportes()
    abiertos = []
    for mov, cfg in MOV_CFG.items():
        raiz = os.path.join(base, cfg["grupo"])
        if not os.path.isdir(raiz):
            continue
        pref = cfg["prefijo"] + "-"
        try:
            with os.scandir(raiz) as clientes:
                for c in clientes:
                    if not c.is_dir():
                        continue
                    with os.scandir(c.path) as lotes:
                        for l in lotes:
                            if not l.is_dir() or esta_cerrado(l.path):
                                continue
                            numero = (
                                l.name[len(pref):] if l.name.startswith(pref) else l.name
                            )
                            lote = hacer_lote(
                                mov,
                                c.name,
                                numero,
                                ruta=l.path,
                                numero_sec=numero_sec_en_disco(l.path),
                            )
                            lote["equipos"] = contar_equipos(l.path)
                            lote["modificado"] = os.path.getmtime(l.path)
                            abiertos.append(lote)
        except Exception:
            continue
    abiertos.sort(key=lambda x: x["modificado"], reverse=True)
    return abiertos


# ─────────────────────────────────────────────────────────
#  Lote activo (el que recibe lo que se escanea)
# ─────────────────────────────────────────────────────────
def guardar_lote_activo(lote):
    os.makedirs(ruta_reportes(), exist_ok=True)
    with open(
        os.path.join(ruta_reportes(), ARCHIVO_LOTE_ACTIVO), "w", encoding="utf-8"
    ) as f:
        json.dump(
            {k: lote.get(k, "") for k in ("mov", "cliente", "numero", "numero_sec")},
            f,
            ensure_ascii=False,
        )


def cargar_lote_activo():
    """
    Lote activo, o None si no hay / desapareció la carpeta / ya fue cerrado
    (por ejemplo desde otro equipo o a mano en el explorador).
    """
    try:
        with open(
            os.path.join(ruta_reportes(), ARCHIVO_LOTE_ACTIVO), "r", encoding="utf-8"
        ) as f:
            cfg = json.load(f)
        lote = hacer_lote(
            cfg["mov"],
            cfg["cliente"],
            cfg["numero"],
            numero_sec=cfg.get("numero_sec", ""),
        )
    except Exception:
        return None
    if not os.path.isdir(lote["ruta"]) or esta_cerrado(lote["ruta"]):
        return None
    # Punteros escritos por versiones anteriores no traen el número secundario:
    # se recupera del '.lote' de la carpeta en vez de darlo por perdido.
    if not lote["numero_sec"]:
        lote["numero_sec"] = numero_sec_en_disco(lote["ruta"])
    return lote


def limpiar_lote_activo():
    ruta = os.path.join(ruta_reportes(), ARCHIVO_LOTE_ACTIVO)
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
#  Archivos del lote. El JSON individual es la ÚNICA fuente de verdad;
#  el HTML y el FUSIONADO se rehacen desde ellos en cada guardado.
# ─────────────────────────────────────────────────────────
def _nombre_base(lote):
    return (
        f"Reporte_{MOV_CFG[lote['mov']]['tipo_doc']}_"
        f"{lote['cliente']}_{lote['numero']}"
    )


def ruta_json_equipo(lote, serial):
    # Sin fecha en el nombre a propósito: si el equipo se re-escanea otro día
    # debe PISAR su registro anterior, no crear un duplicado en el fusionado.
    serial_clean = re.sub(r"[^a-zA-Z0-9]", "", str(serial)) or "SINSERIE"
    return os.path.join(lote["ruta"], f"{_nombre_base(lote)}_{serial_clean}.json")


def ruta_fusionado(lote):
    return os.path.join(lote["ruta"], f"{_nombre_base(lote)}_FUSIONADO.json")


def ruta_html_lote(lote):
    cfg = MOV_CFG[lote["mov"]]
    cliente_legible = lote["cliente"].replace("_", " ")
    return os.path.join(
        lote["ruta"],
        f"{cfg['tipo_doc']} - {cliente_legible} - "
        f"{cfg['etiqueta_id']} {lote['numero']}.html",
    )


def clave_orden(jdata):
    """Timestamp ordenable del escaneo (los JSON viejos no lo traen)."""
    ts = jdata.get("ESCANEADO", "")
    if ts:
        return ts
    fecha = (jdata.get("DATA") or {}).get("fecha", "")
    try:
        return datetime.strptime(fecha, "%d/%m/%Y %H:%M").isoformat(timespec="seconds")
    except Exception:
        return ""


def leer_equipos_lote_con_ruta(lote):
    """
    (ruta, jdata) de cada equipo del lote, del más reciente al más antiguo.

    La ruta real importa cuando hay que REESCRIBIR el JSON: los registros
    viejos pueden tener un nombre que ruta_json_equipo() ya no genera, y
    recalcularlo crearía un archivo nuevo en vez de actualizar el que existe.
    """
    equipos = []
    try:
        archivos = os.listdir(lote["ruta"])
    except Exception:
        return equipos
    for archivo in archivos:
        if not archivo.endswith(".json") or archivo.endswith("_FUSIONADO.json"):
            continue
        ruta = os.path.join(lote["ruta"], archivo)
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                jdata = json.load(f)
            if isinstance(jdata, dict) and "SERIAL" in jdata:
                equipos.append((ruta, jdata))
        except Exception:
            continue
    equipos.sort(key=lambda par: clave_orden(par[1]), reverse=True)
    return equipos


def leer_equipos_lote(lote):
    """JSON individuales del lote, del más reciente al más antiguo."""
    return [jdata for _, jdata in leer_equipos_lote_con_ruta(lote)]


def regenerar_lote(lote):
    """
    Rehace el HTML y el JSON FUSIONADO del lote a partir de sus JSON.
    Al ser derivados y no incrementales, el fusionado siempre sale completo
    (aunque la OT se haya trabajado en varios días) y sin duplicados.
    Devuelve el total de equipos.
    """
    equipos = leer_equipos_lote(lote)
    cfg = MOV_CFG[lote["mov"]]
    cliente_legible = lote["cliente"].replace("_", " ")

    contenido = HTML_START.replace(
        "Inventario Maestro de Equipos",
        f"{cfg['tipo_doc']} - {cliente_legible} · "
        f"{cfg['etiqueta_id']} {lote['numero']}",
    ).replace(
        "<title>Inventario Maestro</title>",
        f"<title>{cfg['tipo_doc']} - {lote['cliente']}</title>",
    )

    entries = []
    for jdata in equipos:
        try:
            entries.append(reconstruir_entry_desde_json(jdata))
        except Exception as e:
            print(f"No se pudo rearmar {jdata.get('SERIAL', '?')}: {e}")
    contenido += "\n".join(entries) + HTML_END
    contenido = fijar_total_count(contenido, len(entries))

    with open(ruta_html_lote(lote), "w", encoding="utf-8") as f:
        f.write(contenido)
    with open(ruta_fusionado(lote), "w", encoding="utf-8") as f:
        json.dump(
            [resumen_fusionado(eq) for eq in equipos], f, ensure_ascii=False, indent=4
        )
    return len(equipos)


def marcar_pendiente_envio(lote):
    """Contenido nuevo en la OT ⇒ vuelve a estar pendiente de subir al NAS."""
    ruta = os.path.join(lote["ruta"], MARCADOR_ENVIADO)
    if os.path.exists(ruta):
        try:
            os.remove(ruta)
        except Exception:
            pass


def guardar_registro_en_lote(lote, registro):
    """Escribe el JSON del equipo y regenera los derivados. Devuelve el total."""
    os.makedirs(lote["ruta"], exist_ok=True)
    guardar_meta_lote(lote)
    with open(ruta_json_equipo(lote, registro["SERIAL"]), "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=4)
    marcar_pendiente_envio(lote)
    return regenerar_lote(lote)


def pendientes_legacy():
    """
    Equipos escaneados con el modelo anterior (data_*.json sueltos en la raíz
    de Reportes_Guardados, sin carpeta de OT). Devuelve {mov: [rutas]}.
    """
    base = ruta_reportes()
    encontrados = {"Entrega": [], "Retiro": []}
    if os.path.isdir(base):
        for archivo in sorted(os.listdir(base)):
            if archivo.startswith("data_") and archivo.endswith(".json"):
                mov = "Retiro" if archivo.startswith("data_Retiro_") else "Entrega"
                encontrados[mov].append(os.path.join(base, archivo))
    return encontrados


def migrar_legacy_a_lote(rutas, lote):
    """
    Adopta los data_*.json sueltos dentro de una OT: los reescribe con el
    cliente/número del lote y regenera HTML y FUSIONADO. Devuelve cuántos entraron.
    """
    os.makedirs(lote["ruta"], exist_ok=True)
    guardar_meta_lote(lote)
    num_ot, num_guia = numeros_lote(lote)
    migrados = 0
    for ruta in rutas:
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                jdata = json.load(f)
            jdata["CLIENTE"] = lote["cliente"]
            jdata["TIPO_MOVIMIENTO"] = lote["mov"]
            jdata["GUIA_ID"] = num_guia
            jdata["OT_ID"] = num_ot
            destino = ruta_json_equipo(lote, jdata.get("SERIAL", ""))
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(jdata, f, ensure_ascii=False, indent=4)
            os.remove(ruta)
            migrados += 1
        except Exception as e:
            print(f"No se pudo migrar {os.path.basename(ruta)}: {e}")

    # El HTML acumulado del modelo viejo ya no aplica: el de la OT se regenera
    # desde los JSON. Se borra solo el del movimiento migrado.
    legacy_html = os.path.join(
        ruta_reportes(), f"Reporte_{MOV_CFG[lote['mov']]['tipo_doc']}.html"
    )
    if os.path.exists(legacy_html):
        try:
            os.remove(legacy_html)
        except Exception:
            pass

    marcar_pendiente_envio(lote)
    regenerar_lote(lote)
    return migrados

def _serial(valor):

    return str(valor or "").strip()
    
def son_el_mismo_lote(a,b):
    return os.path.normcase(a["ruta"]) == os.path.normcase(b["ruta"])

def reetiquetar_equipo(jdata,destino):
    num_ot, num_guia = numeros_lote(destino)
    jdata["CLIENTE"] = destino["cliente"]
    jdata["TIPO_MOVIMIENTO"] = destino["mov"]
    jdata["GUIA_ID"] = num_guia
    jdata["OT_ID"] = num_ot

def reasignar_json(jdata,ruta_origen,destino):
    reetiquetar_equipo(jdata,destino)
    ruta_destino = ruta_json_equipo(destino, jdata.get("SERIAL",""))
    with open(ruta_destino, "w", encoding="utf-8") as f:
        json.dump(jdata,f,ensure_ascii=False, indent=4)
    try:
        os.remove(ruta_origen)
    except Exception:
        pass

def mover_equipos_a_lote(origen,seriales,destino):
    if son_el_mismo_lote(origen,destino):
        return 0
    buscados = {_serial(s)for s in seriales}
    os.makedirs(destino["ruta"], exist_ok=True)
    guardar_meta_lote(destino)
    
    movidos = 0
    for ruta_origen, jdata in leer_equipos_lote_con_ruta(origen):
        if _serial(jdata.get("SERIAL")) in buscados:
            reasignar_json(jdata,ruta_origen,destino)
            movidos += 1
    if movidos:
        for lote in (origen,destino):
            marcar_pendiente_envio(lote)
            regenerar_lote(lote)
    return movidos


def buscar_serial_en_abiertos(serial, excluir_ruta=None):
    """
    Busca el serial en los demás lotes ABIERTOS. Con varias OT en curso el
    mismo equipo podría quedar registrado en dos, y eso hay que avisarlo.
    """
    for otro in listar_lotes_abiertos():
        if excluir_ruta and os.path.normcase(otro["ruta"]) == os.path.normcase(
            excluir_ruta
        ):
            continue
        if os.path.exists(ruta_json_equipo(otro, serial)):
            return otro
    return None



def guardar_equipo_general(
    lote, data, obs, tiene_office, office_key, version_office, detalle_componentes
):
    """
    Registra un equipo en el lote (OT/guía) activo: escribe su JSON individual
    y regenera el HTML y el FUSIONADO de la OT. El movimiento y el número de
    documento los aporta el lote, no el equipo. Devuelve el total del lote.
    """
    tiene_fallas = any(c["estado"] != "OK" for c in detalle_componentes)
    num_ot, num_guia = numeros_lote(lote)
    sn_hdd = "_".join(data.get("disk_serials", [])) or "PENDIENTE"
    sn_app = (
        office_key.strip()
        if (tiene_office and office_key and office_key.strip())
        else "PENDIENTE"
    )

    registro = {
        "CLIENTE": lote["cliente"],
        "SERIAL": data["serial"],
        "SN_Win": data["key"],
        "SN_HDD": sn_hdd,
        "SN_Transf": "PENDIENTE",
        "SN_APP": sn_app,
        "MODELO": data["model"],
        "TIPO_MOVIMIENTO": lote["mov"],
        "GUIA_ID": num_guia,
        "OT_ID": num_ot,
        "OBS": obs or "Sin observaciones",
        "DETALLE_COMPONENTES": detalle_componentes,
        "TIENE_FALLAS": tiene_fallas,
        "DATA": data,
        "OFFICE": f"Office {version_office}" if tiene_office else "No",
        # Timestamp ordenable: el HTML se rearma con el más reciente arriba.
        "ESCANEADO": datetime.now().isoformat(timespec="seconds"),
    }
    return guardar_registro_en_lote(lote, registro)


def _ruta_no_pisar(ruta):
    """
    Devuelve una ruta que NO exista aún: si el archivo ya está, agrega
    ' (2)', ' (3)'… antes de la extensión. Evita sobrescribir un HTML o
    FUSIONADO de un lote anterior del mismo cliente/día.
    """
    if not os.path.exists(ruta):
        return ruta
    raiz, ext = os.path.splitext(ruta)
    n = 2
    while os.path.exists(f"{raiz} ({n}){ext}"):
        n += 1
    return f"{raiz} ({n}){ext}"


def crear_backup(motivo=""):
    """
    Comprime ENTREGA/ y RETIROS/ (con todas sus OT) en un ZIP con fecha y hora,
    dentro de Reportes_Guardados/_BACKUPS/.

    El ZIP va FUERA de ENTREGA/RETIROS a propósito: esas carpetas se recorren
    para listar lotes, clientes y pendientes de envío, así que un backup adentro
    aparecería como un cliente/OT falso y se subiría al NAS.

    Devuelve la ruta del ZIP creado, o None si no había nada que respaldar.
    Nunca lanza: un fallo de backup no debe cortar el cierre ni el envío.
    """
    try:
        base = ruta_reportes()
        origenes = [
            (grupo, os.path.join(base, grupo))
            for grupo in ("ENTREGA", "RETIROS")
            if os.path.isdir(os.path.join(base, grupo))
        ]
        if not origenes:
            return None

        ruta_backups = os.path.join(base, "_BACKUPS")
        os.makedirs(ruta_backups, exist_ok=True)

        sello = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        sufijo = f"_{motivo}" if motivo else ""
        destino = _ruta_no_pisar(
            os.path.join(ruta_backups, f"Backup_{sello}{sufijo}.zip")
        )

        archivos = 0
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
            for grupo, ruta_grupo in origenes:
                for carpeta, _, nombres in os.walk(ruta_grupo):
                    for nombre in nombres:
                        completo = os.path.join(carpeta, nombre)
                        # Dentro del ZIP se respeta ENTREGA/<CLIENTE>/OT-553/...
                        interno = os.path.join(
                            grupo, os.path.relpath(completo, ruta_grupo)
                        )
                        zf.write(completo, interno)
                        archivos += 1

        if archivos == 0:  # nada dentro: no dejamos un ZIP vacío
            os.remove(destino)
            return None
        return destino
    except Exception as e:
        print(f"Error generando backup: {e}")
        return None


def cerrar_lote(lote):
    """
    Finaliza una OT/guía: regenera el fusionado con TODO lo escaneado (aunque
    se haya trabajado en varios días) y escribe el marcador '.cerrado'.

    No mueve ni renombra nada: los equipos viven en la carpeta de la OT desde
    el primer escaneo. Devuelve (total_equipos, equipos_malos): en una entrega
    equipos_malos queda vacío a propósito, porque el formulario ni siquiera
    muestra el panel de componentes.
    """
    # Hay que preguntarlo ANTES de marcar: cargar_lote_activo() descarta los
    # lotes cerrados, así que después del marcador siempre daría "no es activo"
    # y el puntero quedaría apuntando a una OT ya cerrada.
    era_activo = es_activo(lote)

    total = regenerar_lote(lote)
    equipos = leer_equipos_lote(lote)

    equipos_malos = (
        [e for e in equipos if e.get("TIENE_FALLAS")]
        if lote["mov"] == "Retiro"
        else []
    )

    marcar_cerrado(lote, total)
    if era_activo:
        limpiar_lote_activo()
    return total, equipos_malos


def es_activo(lote):
    activo = cargar_lote_activo()
    return bool(activo) and os.path.normcase(activo["ruta"]) == os.path.normcase(
        lote["ruta"]
    )


def clientes_existentes():
    """Clientes que ya tienen alguna OT/guía (carpetas dentro de ENTREGA/ y RETIROS/)."""
    ruta_base = os.path.join(os.getcwd(), "Reportes_Guardados")
    nombres = set()
    for grupo in ("ENTREGA", "RETIROS"):
        ruta_grupo = os.path.join(ruta_base, grupo)
        if os.path.isdir(ruta_grupo):
            for cli in os.listdir(ruta_grupo):
                if os.path.isdir(os.path.join(ruta_grupo, cli)):
                    nombres.add(cli)
    return sorted(nombres)


def normalizar_cliente(valor):
    """Normaliza el nombre de cliente a MAYÚSCULAS y sin espacios (para carpeta)."""
    return (
        re.sub(r"[^a-zA-Z0-9\s_\-]", "", valor).strip().replace(" ", "_").upper()
        or "GENERAL"
    )



def abrir_lote(lote):
    """
    Deja la carpeta del lote lista para recibir equipos. Si el lote ya existía
    y no se escribió el segundo número, se conserva el que tenga la carpeta en
    vez de borrarlo por dejar el campo vacío. Devuelve el mismo lote.
    """
    os.makedirs(lote["ruta"], exist_ok=True)
    if not lote["numero_sec"]:
        lote["numero_sec"] = numero_sec_en_disco(lote["ruta"])
    guardar_meta_lote(lote)
    return lote


def pendientes_envio():
    """
    Carpetas de OT que todavía no se subieron al servidor (sin '.enviado').

    El marcador va por OT, no por cliente: agregar un equipo a una sola OT no
    obliga a re-subir las demás carpetas de ese cliente, que pueden ser miles.
    Devuelve (pendientes, hay_carpetas), con pendientes como lista de
    (grupo, cliente, nombre_ot, ruta_ot, abierta).
    """
    base = ruta_reportes()
    pendientes = []
    hay_carpetas = False
    for grupo in ("ENTREGA", "RETIROS"):
        ruta_grupo = os.path.join(base, grupo)
        if not os.path.isdir(ruta_grupo):
            continue
        for cli in os.listdir(ruta_grupo):
            ruta_cli = os.path.join(ruta_grupo, cli)
            if not os.path.isdir(ruta_cli):
                continue
            for ot in os.listdir(ruta_cli):
                ruta_ot = os.path.join(ruta_cli, ot)
                if not os.path.isdir(ruta_ot):
                    continue
                hay_carpetas = True
                if not os.path.exists(os.path.join(ruta_ot, MARCADOR_ENVIADO)):
                    pendientes.append(
                        (grupo, cli, ot, ruta_ot, not esta_cerrado(ruta_ot))
                    )
    return pendientes, hay_carpetas


def marcar_enviado(ruta_ot):
    """Marca la OT como subida. Va DESPUÉS de subir: si falla, sigue pendiente."""
    with open(os.path.join(ruta_ot, MARCADOR_ENVIADO), "w", encoding="utf-8") as mf:
        mf.write(datetime.now().isoformat())
