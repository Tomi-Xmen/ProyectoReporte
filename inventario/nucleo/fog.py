"""
API de FOG — crear sesiones multicast desde el Panel de clonación.

Reemplaza el formulario "Image Management → Multicast Image" de la web de
FOG por una llamada a su API. El resto del flujo no cambia: los equipos se
siguen booteando por PXE y uniéndose a la sesión a mano, esto solo evita
tener que ir a la web y completar el formulario ahí.

Los tokens de la API NUNCA viven en este archivo ni al lado del .exe: esa
carpeta es exactamente la que fog_postscript.bat copia a TODOS los equipos
recién clonados (ver remoto.candidatas_clave_ssh). Un token de FOG puede
crear tareas de imaging sobre cualquier equipo del inventario, así que
filtrarlo ahí sería mucho más grave que filtrar la clave SSH de solo-subida.
Por eso se leen de un archivo externo (_candidatas_config_fog) que solo
existe en la PC central donde se abre el Panel de clonación.
"""

import json
import os

from . import config

if config.REQUESTS_AVAILABLE:
    import requests

FOG_TIMEOUT = 10  # segundos para conectar antes de fallar

# El API de creación genérico de FOG (/fog/multicastsession/create) no asigna
# puerto solo -eso lo hace únicamente la página web, ver multicastPost() en
# FOG-, así que hay que calcularlo acá igual que el server: arranca en este
# puerto de reserva (el mismo fallback que usa FOG cuando no hay
# FOG_UDPCAST_STARTINGPORT configurado) y salta de a 2, porque udp-sender usa
# el puerto base y base+1 por sesión.
_FOG_PUERTO_BASE_MULTICAST = 63100
_FOG_PUERTOS_POR_SESION = 2


def _candidatas_config_fog():
    """
    Dónde se busca el archivo con los tokens de la API de FOG, en orden de
    prioridad. A propósito nunca se busca al lado del ejecutable — ver el
    comentario del banner de esta sección.
    """
    candidatas = []
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        candidatas.append(os.path.join(programdata, "Reporte3", "fog_api.json"))
    candidatas.append(
        os.path.join(os.path.expanduser("~"), ".reporte3", "fog_api.json")
    )
    return candidatas


def resolver_credenciales_fog():
    """
    Carga {"host": ..., "api_token": ..., "user_token": ...} desde el primer
    archivo que exista. Lanza RuntimeError con instrucciones si no hay
    ninguno o si está incompleto.
    """
    for ruta in _candidatas_config_fog():
        if not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
            return {
                "host": datos["host"],
                "api_token": datos["api_token"],
                "user_token": datos["user_token"],
            }
        except Exception as e:
            raise RuntimeError(
                f"El archivo de configuración de FOG está corrupto o le "
                f"faltan campos:\n{ruta}\n\n{e}\n\n"
                'Formato esperado: {"host": "IP", "api_token": "...", '
                '"user_token": "..."}'
            )
    raise RuntimeError(
        "Falta el archivo de configuración de la API de FOG.\n\n"
        'Creá uno con {"host": "IP", "api_token": "...", '
        '"user_token": "..."} en alguna de estas rutas:\n\n'
        + "\n".join(f"  • {r}" for r in _candidatas_config_fog())
    )


def _fog_request(metodo, ruta, cuerpo=None):
    """POST/GET/DELETE a /fog/<ruta>. Devuelve el JSON ya decodificado."""
    if not config.REQUESTS_AVAILABLE:
        raise RuntimeError(
            "Falta la librería 'requests'.\n\nInstalar con:  pip install requests"
        )
    cred = resolver_credenciales_fog()
    headers = {
        "fog-api-token": cred["api_token"],
        "fog-user-token": cred["user_token"],
    }
    url = f"http://{cred['host']}/fog/{ruta.lstrip('/')}"
    try:
        resp = requests.request(
            metodo, url, headers=headers, json=cuerpo, timeout=FOG_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"No se pudo conectar al servidor FOG ({cred['host']}):\n\n{e}"
        )
    if not resp.ok:
        raise RuntimeError(
            f"FOG respondió {resp.status_code} en '{ruta}':\n\n{resp.text[:500]}"
        )
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def fog_get(ruta):
    return _fog_request("GET", ruta)


def fog_post(ruta, cuerpo):
    return _fog_request("POST", ruta, cuerpo)


def fog_delete(ruta):
    return _fog_request("DELETE", ruta)


def _fog_puerto_multicast_libre():
    """Primer puerto libre del pool de multicast (mismo cálculo que el server)."""
    activas = (fog_get("multicastsession/current") or {}).get(
        "multicastsessions", []
    )
    ocupados = {int(s["port"]) for s in activas if s.get("port")}
    puerto = _FOG_PUERTO_BASE_MULTICAST
    while puerto in ocupados:
        puerto += _FOG_PUERTOS_POR_SESION
    return puerto


def fog_crear_sesion_multicast(nombre, image_id, cantidad):
    """
    Crea una sesión multicast igual que "Image Management → Multicast Image"
    en la web de FOG. Los equipos se siguen uniendo a mano por PXE — esto
    solo reemplaza el formulario.

    Devuelve el dict de la sesión creada (trae 'id' y 'port').
    """
    imagen = fog_get(f"image/{image_id}")
    if not imagen:
        raise RuntimeError(f"No existe la imagen {image_id} en FOG.")

    storagegroups = (fog_get("storagegroup") or {}).get("storagegroups", [])
    if not storagegroups:
        raise RuntimeError("El servidor FOG no tiene ningún storage group.")
    storagegroup_id = storagegroups[0]["id"]

    nodos = (fog_get("storagenode") or {}).get("storagenodes", [])
    nodo = next(
        (n for n in nodos if str(n.get("storagegroupID")) == str(storagegroup_id)),
        nodos[0] if nodos else None,
    )
    if not nodo:
        raise RuntimeError("El servidor FOG no tiene ningún storage node.")

    cuerpo = {
        "name": nombre,
        "image": int(image_id),
        "sessclients": int(cantidad),
        "clients": -2,  # sesión con nombre, unión manual por PXE — no tocar
        "stateID": 0,
        "isDD": imagen.get("imageTypeID"),
        "interface": nodo.get("interface"),
        "logpath": imagen.get("path"),
        "storagegroupID": storagegroup_id,
        "port": _fog_puerto_multicast_libre(),
    }
    return fog_post("multicastsession/create", cuerpo)


def fog_cancelar_sesion_multicast(sesion_id):
    """Cancela una sesión multicast (igual que 'Stop' en la web de FOG)."""
    return fog_delete(f"multicastsession/{sesion_id}/cancel")



def imagenes_habilitadas():
    """Imágenes habilitadas de FOG, ordenadas por nombre."""
    imagenes = (fog_get("image") or {}).get("images", [])
    return sorted(
        (i for i in imagenes if str(i.get("isEnabled")) == "1"),
        key=lambda i: i.get("name", ""),
    )
