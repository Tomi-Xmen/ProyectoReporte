"""
Traer automático de la OT publicada para clonación.

Los equipos clonados suben su JSON al servidor y nada más; el HTML y el
FUSIONADO de la OT se arman en esta PC. Antes había que apretar "Traer y
reconstruir"; acá el panel lo hace solo cada pocos segundos, y por eso tiene
que ser más cuidadoso que ese botón, que baja TODO y pisa lo local:

- Solo baja lo nuevo o lo que CAMBIÓ en el servidor desde la última vez. Si
  en esta PC se le cargó el transformador a un equipo (a mano o desde el
  celular), la copia vieja del servidor no lo pisa en la vuelta siguiente.
- Lo que se quitó del lote a mano no vuelve, salvo que el equipo mande algo
  nuevo (otro escaneo).
- Lo que trae lo re-etiqueta con los documentos del lote LOCAL: si la guía se
  completó acá después de publicar la OT, los equipos que siguen llegando con
  la guía vieja quedan con la correcta.

Para decidir usa la huella (sha1) de cada archivo en el servidor y dos
archivos de control en la carpeta del lote, sin extensión .json para que
nadie los cuente como equipos ni viajen al servidor:

    .sincronizado   {archivo: huella del servidor la última vez que se trajo}
    .quitados       {archivo: [huellas]} quitados a mano: con esa huella no vuelven

Las funciones que hablan con el servidor corren en un hilo de trabajo y no
escriben nada local; aplicar() escribe y corre en el hilo de la interfaz,
igual que el servidor del celular, así los dos nunca escriben a la vez.
"""

import hashlib
import json
import os
from datetime import datetime

from .lotes import (
    ARCHIVO_META_LOTE,
    esta_cerrado,
    guardar_meta_lote,
    hacer_lote,
    marcar_pendiente_envio,
    numero_sec_en_disco,
    numeros_lote,
    regenerar_lote,
)

ARCHIVO_SINCRONIZADO = ".sincronizado"
ARCHIVO_QUITADOS = ".quitados"
_SEPARADOR = "===ARCHIVO:"


def huella(contenido):
    """sha1 de los bytes, igual que el 'sha1sum' del servidor."""
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")
    return hashlib.sha1(contenido).hexdigest()


# ─────────────────────────────────────────────────────────
#  Archivos de control
# ─────────────────────────────────────────────────────────
def _leer_control(ruta_lote, archivo):
    try:
        with open(os.path.join(ruta_lote, archivo), "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except Exception:
        return {}


def _guardar_control(ruta_lote, archivo, datos):
    with open(os.path.join(ruta_lote, archivo), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def registrar_quitado(ruta_lote, nombre, ruta_archivo):
    """
    Anota que 'nombre' se quitó a mano. Se guardan las huellas con que puede
    estar en el servidor: la de la última vez que se trajo y la del archivo
    local (si se subió desde acá con "Enviar", el servidor tiene esos bytes).
    """
    huellas = []
    previa = _leer_control(ruta_lote, ARCHIVO_SINCRONIZADO).get(nombre)
    if previa:
        huellas.append(previa)
    try:
        with open(ruta_archivo, "rb") as f:
            huellas.append(huella(f.read()))
    except OSError:
        pass
    quitados = _leer_control(ruta_lote, ARCHIVO_QUITADOS)
    quitados[nombre] = sorted(set(quitados.get(nombre, [])) | set(huellas))
    _guardar_control(ruta_lote, ARCHIVO_QUITADOS, quitados)


# ─────────────────────────────────────────────────────────
#  Qué traer
# ─────────────────────────────────────────────────────────
def _nombre_valido(nombre):
    """Un archivo de equipo del servidor, sin rutas ni nada raro."""
    return (
        bool(nombre)
        and nombre == os.path.basename(nombre)
        and not nombre.startswith(".")
        and nombre.endswith(".json")
        and not nombre.endswith("_FUSIONADO.json")
        and "/" not in nombre
        and "\\" not in nombre
    )


def a_traer(huellas_remotas, ruta_lote):
    """
    (traer, anotar) para las huellas {archivo: sha1} del servidor:

      traer   archivos a bajar: no existen acá, o cambiaron en el servidor
              desde la última vez que se trajeron;
      anotar  archivos que existen acá y nunca se trajeron: manda lo local
              (lo cargó esta PC o el celular) y solo se anota la huella para
              no volver a decidir.
    """
    registro = _leer_control(ruta_lote, ARCHIVO_SINCRONIZADO)
    quitados = _leer_control(ruta_lote, ARCHIVO_QUITADOS)
    traer, anotar = {}, {}
    for nombre, firma in huellas_remotas.items():
        if not _nombre_valido(nombre) or firma in quitados.get(nombre, []):
            continue
        if not os.path.exists(os.path.join(ruta_lote, nombre)):
            traer[nombre] = firma
            continue
        previa = registro.get(nombre)
        if previa is None:
            anotar[nombre] = firma
        elif previa != firma:
            traer[nombre] = firma
    return traer, anotar


def lote_local(lote):
    """El lote publicado, con la carpeta y el documento secundario de ESTA PC."""
    local = hacer_lote(lote["mov"], lote["cliente"], lote["numero"])
    local["numero_sec"] = numero_sec_en_disco(local["ruta"]) or lote.get("numero_sec", "")
    return local


def aplicar(lote, huellas_remotas, contenidos):
    """
    Escribe lo traído y regenera el lote. Corre en el hilo de la interfaz.

    Vuelve a decidir con a_traer() en vez de confiar en lo que se decidió en
    el hilo de trabajo: entre una cosa y otra el celular pudo haber escrito.
    Devuelve la cantidad de equipos escritos; 0 si el lote está cerrado acá.
    """
    local = lote_local(lote)
    if esta_cerrado(local["ruta"]):
        return 0
    os.makedirs(local["ruta"], exist_ok=True)
    if not os.path.exists(os.path.join(local["ruta"], ARCHIVO_META_LOTE)):
        guardar_meta_lote(local)

    traer, anotar = a_traer(huellas_remotas, local["ruta"])
    num_ot, num_guia = numeros_lote(local)
    registro = _leer_control(local["ruta"], ARCHIVO_SINCRONIZADO)
    escritos = 0
    for nombre, firma in traer.items():
        if nombre not in contenidos:
            continue
        try:
            jdata = json.loads(contenidos[nombre])
        except ValueError:
            continue
        if not isinstance(jdata, dict) or not jdata.get("SERIAL"):
            continue
        jdata["CLIENTE"] = local["cliente"]
        jdata["TIPO_MOVIMIENTO"] = local["mov"]
        jdata["GUIA_ID"] = num_guia
        jdata["OT_ID"] = num_ot
        with open(os.path.join(local["ruta"], nombre), "w", encoding="utf-8") as f:
            json.dump(jdata, f, ensure_ascii=False, indent=4)
        registro[nombre] = firma
        escritos += 1

    registro.update(anotar)
    if escritos or anotar:
        _guardar_control(local["ruta"], ARCHIVO_SINCRONIZADO, registro)
    if escritos:
        # El FUSIONADO local ahora tiene más que el del servidor: queda
        # pendiente de "Enviar" para que allá también esté completo.
        marcar_pendiente_envio(local)
        regenerar_lote(local)
    return escritos


def equipos_locales(lote, huellas_remotas):
    """Los equipos que están en el servidor, leídos de la copia local ya sincronizada."""
    ruta = lote_local(lote)["ruta"]
    equipos = []
    for nombre in sorted(huellas_remotas):
        try:
            with open(os.path.join(ruta, nombre), "r", encoding="utf-8") as f:
                jdata = json.load(f)
        except Exception:
            continue
        if isinstance(jdata, dict) and jdata.get("SERIAL"):
            equipos.append(jdata)
    return equipos


# ─────────────────────────────────────────────────────────
#  Servidor (hilo de trabajo: no escribe nada local)
# ─────────────────────────────────────────────────────────
def _comillas(texto):
    return "'" + str(texto).replace("'", "'\\''") + "'"


def huellas_remotas(cliente, lote):
    """{archivo: sha1} de los JSON de equipos de la OT en el servidor."""
    from .remoto import correr_remoto, ruta_remota_lote

    comando = (
        f"cd {_comillas(ruta_remota_lote(lote))} 2>/dev/null || exit 0; "
        "for f in *.json; do [ -e \"$f\" ] || continue; "
        'case "$f" in *_FUSIONADO.json) continue;; esac; '
        'sha1sum -- "$f"; done'
    )
    codigo, salida, _error = correr_remoto(cliente, comando)
    huellas = {}
    if codigo != 0:
        return huellas
    for linea in salida.splitlines():
        firma, _, nombre = linea.strip().partition("  ")
        if len(firma) == 40 and _nombre_valido(nombre):
            huellas[nombre] = firma
    return huellas


def bajar(cliente, lote, nombres):
    """{archivo: texto} de esos JSON del servidor, en una sola vuelta."""
    from .remoto import correr_remoto, ruta_remota_lote

    nombres = [n for n in nombres if _nombre_valido(n)]
    if not nombres:
        return {}
    comando = (
        f"cd {_comillas(ruta_remota_lote(lote))} || exit 1; "
        f"for f in {' '.join(_comillas(n) for n in nombres)}; do "
        f'echo "{_SEPARADOR}$f"; cat -- "$f"; echo; done'
    )
    codigo, salida, _error = correr_remoto(cliente, comando)
    if codigo != 0:
        return {}
    contenidos = {}
    for bloque in salida.split(_SEPARADOR):
        nombre, _, cuerpo = bloque.partition("\n")
        nombre = nombre.strip()
        if nombre in nombres and cuerpo.strip():
            contenidos[nombre] = cuerpo
    return contenidos


def consultar(cliente):
    """
    Una vuelta de sincronización contra el servidor, sin escribir nada local.
    None si no hay OT publicada; si no, un dict para aplicar() y el panel.
    """
    from .remoto import leer_esperados, leer_lote_activo_remoto

    lote = leer_lote_activo_remoto(cliente)
    if not lote:
        return None
    huellas = huellas_remotas(cliente, lote)
    traer, _anotar = a_traer(huellas, lote_local(lote)["ruta"])
    return {
        "lote": lote,
        "huellas": huellas,
        "contenidos": bajar(cliente, lote, list(traer)),
        "esperados": leer_esperados(cliente, lote),
        "hora": datetime.now().strftime("%H:%M:%S"),
    }
