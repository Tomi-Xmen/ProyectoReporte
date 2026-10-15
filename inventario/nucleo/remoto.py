"""
Envío por SCP (SSH) y control central del flujo de clonación.

Sube al servidor solo lo que es fuente de verdad o entregable —JSON
individuales, JSON FUSIONADO y el marcador '.cerrado'— replicando el árbol
<GRUPO>/<CLIENTE>/<OT>. El HTML se deja fuera a propósito: es un derivado
pesado que allá se rearma desde los JSON con "RECONSTRUIR DESDE JSONs",
idéntico y con todas sus funcionalidades.
"""

import json
import os
import socket
import tempfile
from datetime import datetime

from . import config
from .config import (
    SCP_CLAVE,
    SCP_CLAVE_PASSPHRASE,
    SCP_DESTINO,
    SCP_HOST,
    SCP_PUERTO,
    SCP_TIMEOUT,
    SCP_USUARIO,
    ruta_base_proyecto,
)
from .lotes import (
    ARCHIVO_LOTE_ACTIVO,
    ARCHIVO_META_LOTE,
    MARCADOR_CERRADO,
    MARCADOR_ENVIADO,
    MOV_CFG,
    carpeta_lote,
    clave_orden,
    contar_equipos,
    crear_backup,
    guardar_meta_lote,
    hacer_lote,
    marcar_enviado,
    regenerar_lote,
)

if config.SCP_AVAILABLE:
    import paramiko
    from scp import SCPClient

# Extensiones/archivos que SÍ viajan. Todo lo demás (HTML, .enviado,
# .lote_activo) se queda en la máquina.
_SCP_EXTENSIONES = (".json",)


def archivos_a_enviar(ruta_ot):
    """
    Archivos de una OT que deben subir al servidor, ya ordenados.

    Se envían los JSON (individuales + FUSIONADO) y los marcadores de estado
    '.cerrado' y '.lote' (este último trae el número de documento que la ruta
    no codifica y sin él la OT se reconstruye sin su guía/OT secundaria).
    Quedan fuera el HTML —derivado, se rearma allá— y '.enviado', que es
    control local de sincronización.
    """
    archivos = []
    try:
        nombres = sorted(os.listdir(ruta_ot))
    except Exception:
        return archivos
    for nombre in nombres:
        ruta = os.path.join(ruta_ot, nombre)
        if not os.path.isfile(ruta):
            continue
        if nombre == MARCADOR_ENVIADO:
            continue
        if nombre in (MARCADOR_CERRADO, ARCHIVO_META_LOTE):
            archivos.append(ruta)
            continue
        if nombre.lower().endswith(_SCP_EXTENSIONES):
            archivos.append(ruta)
    return archivos


def candidatas_clave_ssh():
    """
    Dónde se busca la clave privada, en orden de prioridad.

    El ejecutable se copia a equipos recién clonados por FOG, donde el perfil
    de usuario es otro y C:\\Users\\<alguien>\\.ssh no existe. Por eso la clave
    que viaja AL LADO DEL EXE manda sobre la ruta fija: es la única que existe
    seguro en esa máquina. La ruta de SCP_CLAVE queda como respaldo para el
    equipo de escritorio donde se trabaja a diario.
    """
    nombre = os.path.basename(SCP_CLAVE) if SCP_CLAVE else "id_ed25519"
    candidatas = [
        os.path.join(ruta_base_proyecto, nombre),
        os.path.join(ruta_base_proyecto, "clave_scp"),
    ]
    if SCP_CLAVE:
        candidatas.append(SCP_CLAVE)
    candidatas.append(os.path.join(os.path.expanduser("~"), ".ssh", nombre))
    # Sin duplicados y respetando el orden.
    vistas, unicas = set(), []
    for c in candidatas:
        clave = os.path.normcase(os.path.abspath(c))
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(c)
    return unicas


def resolver_clave_ssh():
    """Primera clave privada que exista de verdad, o None si no hay ninguna."""
    for ruta in candidatas_clave_ssh():
        if os.path.isfile(ruta):
            return ruta
    return None


def ruta_remota(*partes):
    """
    Une un path remoto estilo POSIX. No se usa os.path.join: acá corre Windows
    y devolvería '\\', que el servidor Linux trata como parte del nombre.
    """
    absoluta = str(partes[0]).startswith("/")
    limpias = [str(p).replace("\\", "/").strip("/") for p in partes if p]
    unida = "/".join(limpias)
    return f"/{unida}" if absoluta else unida


def abrir_conexion_scp():
    """
    Cliente SSH conectado y listo. Lanza una excepción con mensaje legible si
    la clave no existe, el host no responde o las credenciales fallan.
    """
    if not config.SCP_AVAILABLE:
        raise RuntimeError(
            "Falta la librería 'paramiko'/'scp'.\n\n"
            "Instalar con:  pip install paramiko scp"
        )

    ruta_clave = resolver_clave_ssh()
    clave = None
    if ruta_clave:
        # El tipo de clave (RSA/Ed25519/ECDSA) no se conoce de antemano: se
        # prueban todos y se usa el primero que la lea.
        ultimo = None
        for tipo in (
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey,
        ):
            try:
                clave = tipo.from_private_key_file(
                    ruta_clave, password=SCP_CLAVE_PASSPHRASE or None
                )
                break
            except Exception as e:
                ultimo = e
        if clave is None:
            raise RuntimeError(
                f"No se pudo leer la clave SSH:\n{ruta_clave}\n\n{ultimo}\n\n"
                "Si la clave tiene passphrase, cárgala en SCP_CLAVE_PASSPHRASE."
            )
    elif SCP_CLAVE:
        raise RuntimeError(
            "No se encontró la clave SSH en ninguna de estas ubicaciones:\n\n"
            + "\n".join(f"  • {r}" for r in candidatas_clave_ssh())
            + "\n\nEn un equipo clonado la clave tiene que viajar junto al "
            "ejecutable, en la misma carpeta."
        )

    cliente = paramiko.SSHClient()
    cliente.load_system_host_keys()
    # El servidor es de la empresa y su huella puede cambiar al reinstalarlo:
    # aceptarla evita que el envío se caiga por un host key desconocido.
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cliente.connect(
            hostname=SCP_HOST,
            port=SCP_PUERTO,
            username=SCP_USUARIO,
            pkey=clave,
            timeout=SCP_TIMEOUT,
            banner_timeout=SCP_TIMEOUT,
            auth_timeout=SCP_TIMEOUT,
            look_for_keys=clave is None,
            allow_agent=clave is None,
        )
    except paramiko.AuthenticationException:
        cliente.close()
        raise RuntimeError(
            f"El servidor rechazó las credenciales de '{SCP_USUARIO}'.\n\n"
            "Verifica el usuario y que la clave pública esté en el "
            "authorized_keys del servidor."
        )
    except Exception as e:
        cliente.close()
        raise RuntimeError(
            f"No se pudo conectar a {SCP_HOST}:{SCP_PUERTO}\n\n{e}\n\n"
            "Verifica la VPN/Wi-Fi y que el servicio SSH esté arriba."
        )
    return cliente


def correr_remoto(cliente, comando):
    """Ejecuta un comando en el servidor. Devuelve (código, stdout, stderr)."""
    _stdin, stdout, stderr = cliente.exec_command(comando, timeout=SCP_TIMEOUT)
    salida = stdout.read().decode("utf-8", "replace").strip()
    error = stderr.read().decode("utf-8", "replace").strip()
    return stdout.channel.recv_exit_status(), salida, error


def verificar_destino_remoto(cliente):
    """
    Comprueba que SCP_DESTINO exista y sea escribible ANTES de subir nada.

    La carpeta base debe existir de antes (la crea el NAS al publicar el
    recurso compartido); acá solo se crean las subcarpetas de cliente y OT. Si
    la ruta estuviera mal escrita, un 'mkdir -p' la crearía igual —en el disco
    de sistema y fuera del recurso compartido— y los reportes acabarían en un
    árbol fantasma que nadie ve por la red. Mejor fallar y decirlo.
    """
    codigo, _salida, _error = correr_remoto(cliente, f"test -d '{SCP_DESTINO}'")
    if codigo != 0:
        raise RuntimeError(
            f"La carpeta base remota no existe:\n{SCP_DESTINO}\n\n"
            "Tiene que ser la ruta ABSOLUTA de la carpeta compartida en el "
            "servidor. En OpenMediaVault no es el nombre del recurso: mirá la "
            "ruta real en Almacenamiento → Carpetas compartidas (suele ser "
            "/srv/dev-disk-by-uuid-…/<carpeta>).\n\n"
            "Corregí la constante SCP_DESTINO."
        )
    codigo, _salida, _error = correr_remoto(cliente, f"test -w '{SCP_DESTINO}'")
    if codigo != 0:
        raise RuntimeError(
            f"El usuario '{SCP_USUARIO}' no puede escribir en:\n{SCP_DESTINO}\n\n"
            "Dale permiso de lectura/escritura sobre la carpeta compartida "
            "(en OMV: Carpetas compartidas → ACL)."
        )


def mkdir_remoto(cliente, ruta):
    """Crea la carpeta remota (y sus padres). Falla ruidosamente si no puede."""
    codigo, _salida, error = correr_remoto(cliente, f"mkdir -p '{ruta}'")
    if codigo != 0:
        raise RuntimeError(f"No se pudo crear la carpeta remota {ruta}: {error}")


def enviar_ot_por_scp(cliente, grupo, cliente_folder, nombre_ot, ruta_origen):
    """
    Sube los archivos de UNA OT. Devuelve la cantidad de archivos subidos.
    Sobrescribe lo que ya esté allá: una OT abierta se re-envía varias veces y
    cada envío debe dejar el servidor al día.
    """
    archivos = archivos_a_enviar(ruta_origen)
    if not archivos:
        return 0
    destino = ruta_remota(SCP_DESTINO, grupo, cliente_folder, nombre_ot)
    mkdir_remoto(cliente, destino)
    with SCPClient(cliente.get_transport(), socket_timeout=SCP_TIMEOUT) as scp:
        # De a uno y no en bloque: si un archivo falla se sabe cuál fue.
        for ruta in archivos:
            scp.put(ruta, remote_path=ruta_remota(destino, os.path.basename(ruta)))
    return len(archivos)


# ============================================================================
#  CONTROL CENTRAL POR SSH — OT activa compartida y seguimiento del lote
# ----------------------------------------------------------------------------
#  El servidor hace de pizarra común: no corre ningún servicio nuevo, solo
#  guarda los archivos de control en <SCP_DESTINO>/_control. El equipo de
#  escritorio publica la OT activa y los equipos recién clonados la leen para
#  saber a qué OT mandar lo que escanean.
#
#      _control/lote_activo.json     OT que recibe lo que se escanea
#      <GRUPO>/<CLIENTE>/<OT>/       equipos que fueron llegando
#      <GRUPO>/<CLIENTE>/<OT>/.esperados   seriales que se esperan del lote
# ============================================================================
_CONTROL_REMOTO = "_control"
_ARCHIVO_ESPERADOS = ".esperados"


def _ruta_control_remota(*partes):
    return ruta_remota(SCP_DESTINO, _CONTROL_REMOTO, *partes)


def ruta_remota_lote(lote):
    """Carpeta de la OT en el servidor, con el mismo árbol que en local."""
    cfg = MOV_CFG[lote["mov"]]
    return ruta_remota(
        SCP_DESTINO,
        cfg["grupo"],
        lote["cliente"],
        carpeta_lote(lote["mov"], lote["numero"]),
    )


def _subir_texto(cliente, texto, ruta_destino_remota):
    """
    Escribe un archivo de texto en el servidor pasando por un temporal local.

    No se hace con 'echo' por SSH a propósito: los nombres de cliente y las
    observaciones traen tildes, comillas y espacios, y armar ese comando a mano
    es una fuente segura de archivos corruptos.
    """
    mkdir_remoto(cliente, os.path.dirname(ruta_destino_remota).replace("\\", "/"))
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(texto)
        tmp.close()
        with SCPClient(cliente.get_transport(), socket_timeout=SCP_TIMEOUT) as scp:
            scp.put(tmp.name, remote_path=ruta_destino_remota)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _leer_texto_remoto(cliente, ruta):
    """Contenido de un archivo del servidor, o None si no existe."""
    codigo, salida, _error = correr_remoto(cliente, f"cat '{ruta}' 2>/dev/null")
    return salida if codigo == 0 else None


def publicar_lote_activo(cliente, lote):
    """
    Deja en el servidor cuál es la OT que recibe lo escaneado.

    Es el mismo contenido que el '.lote_activo.json' local, pero compartido:
    un equipo recién clonado no tiene historia ni archivos previos, así que la
    única forma de que sepa a qué OT pertenece es preguntárselo al servidor.
    """
    datos = {k: lote.get(k, "") for k in ("mov", "cliente", "numero", "numero_sec")}
    datos["publicado"] = datetime.now().isoformat(timespec="seconds")
    datos["publicado_por"] = socket.gethostname()
    _subir_texto(
        cliente,
        json.dumps(datos, ensure_ascii=False, indent=2),
        _ruta_control_remota(ARCHIVO_LOTE_ACTIVO),
    )


def leer_lote_activo_remoto(cliente):
    """OT activa publicada en el servidor, o None si no hay ninguna."""
    crudo = _leer_texto_remoto(cliente, _ruta_control_remota(ARCHIVO_LOTE_ACTIVO))
    if not crudo:
        return None
    try:
        cfg = json.loads(crudo)
        lote = hacer_lote(
            cfg["mov"], cfg["cliente"], cfg["numero"], numero_sec=cfg.get("numero_sec", "")
        )
    except Exception:
        return None
    # Una OT ya cerrada no debe seguir recibiendo equipos aunque el puntero
    # haya quedado publicado.
    codigo, _s, _e = correr_remoto(
        cliente, f"test -e '{ruta_remota(ruta_remota_lote(lote), MARCADOR_CERRADO)}'"
    )
    return None if codigo == 0 else lote


def despublicar_lote_activo(cliente):
    correr_remoto(cliente, f"rm -f '{_ruta_control_remota(ARCHIVO_LOTE_ACTIVO)}'")


def enviar_equipo_por_scp(cliente, lote, ruta_json):
    """
    Sube el JSON de UN equipo a la OT del servidor.

    Es lo único que manda un equipo clonado, y es deliberado: su carpeta local
    contiene un solo equipo, así que su FUSIONADO y su HTML describen ese
    equipo nada más. Subirlos pisaría los del servidor —que acumulan todo el
    lote— y el reporte de la OT quedaría con un solo equipo. Los derivados se
    rehacen en el panel central, que sí ve el lote completo.
    """
    destino = ruta_remota_lote(lote)
    mkdir_remoto(cliente, destino)
    with SCPClient(cliente.get_transport(), socket_timeout=SCP_TIMEOUT) as scp:
        scp.put(ruta_json, remote_path=ruta_remota(destino, os.path.basename(ruta_json)))
    return ruta_remota(destino, os.path.basename(ruta_json))


_SEPARADOR_REMOTO = "===ARCHIVO:"


def equipos_remotos(cliente, lote):
    """
    Equipos que ya llegaron a la OT en el servidor: [{SERIAL, MODELO, ...}].

    Se traen todos los JSON en UNA sola vuelta (un 'cat' encadenado) en vez de
    un comando por archivo: con un lote de decenas de equipos la diferencia
    entre una conexión y decenas es la diferencia entre un panel usable y uno
    que tarda medio minuto en refrescar.
    """
    carpeta = ruta_remota_lote(lote)
    comando = (
        f"for f in '{carpeta}'/*.json; do "
        f'[ -e "$f" ] || continue; '
        f'case "$f" in *_FUSIONADO.json) continue;; esac; '
        f'echo "{_SEPARADOR_REMOTO}$(basename "$f")"; cat "$f"; '
        f"done"
    )
    codigo, salida, _error = correr_remoto(cliente, comando)
    if codigo != 0 or not salida:
        return []

    equipos = []
    for bloque in salida.split(_SEPARADOR_REMOTO):
        if not bloque.strip():
            continue
        nombre, _, cuerpo = bloque.partition("\n")
        try:
            jdata = json.loads(cuerpo)
        except Exception:
            continue
        if isinstance(jdata, dict) and jdata.get("SERIAL"):
            jdata["_archivo"] = nombre.strip()
            equipos.append(jdata)
    equipos.sort(key=clave_orden, reverse=True)
    return equipos


def leer_esperados(cliente, lote):
    """Seriales que se esperan en el lote. Lista vacía si no se cargó ninguna."""
    crudo = _leer_texto_remoto(
        cliente, ruta_remota(ruta_remota_lote(lote), _ARCHIVO_ESPERADOS)
    )
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
        return [str(s).strip().upper() for s in datos if str(s).strip()]
    except Exception:
        return []


def guardar_esperados(cliente, lote, seriales):
    """Fija la lista de seriales que deben llegar antes de dar el lote por cerrado."""
    limpios = []
    for s in seriales:
        s = str(s).strip().upper()
        if s and s not in limpios:
            limpios.append(s)
    _subir_texto(
        cliente,
        json.dumps(limpios, ensure_ascii=False, indent=2),
        ruta_remota(ruta_remota_lote(lote), _ARCHIVO_ESPERADOS),
    )
    return limpios


def descargar_equipos_remotos(cliente, lote):
    """
    Baja a la carpeta local de la OT los JSON que mandaron los equipos y rehace
    el HTML y el FUSIONADO. Devuelve (bajados, total_equipos).

    Es el paso que cierra el circuito: cada equipo clonado sube su JSON y nada
    más, así que el reporte completo del lote no existe en ningún lado hasta
    que alguien junta las partes. Acá se juntan.
    """
    carpeta = ruta_remota_lote(lote)
    codigo, salida, _error = correr_remoto(
        cliente,
        f"ls -1 '{carpeta}'/*.json 2>/dev/null | grep -v '_FUSIONADO.json$' || true",
    )
    remotos = [l.strip() for l in salida.splitlines() if l.strip()] if codigo == 0 else []
    if not remotos:
        return 0, contar_equipos(lote["ruta"])

    os.makedirs(lote["ruta"], exist_ok=True)
    bajados = 0
    with SCPClient(cliente.get_transport(), socket_timeout=SCP_TIMEOUT) as scp:
        for remoto in remotos:
            local = os.path.join(lote["ruta"], os.path.basename(remoto))
            try:
                scp.get(remoto, local_path=local)
                bajados += 1
            except Exception as e:
                print(f"No se pudo bajar {remoto}: {e}")
    guardar_meta_lote(lote)
    return bajados, regenerar_lote(lote)


def cerrar_lote_remoto(cliente, lote, total):
    """Marca la OT como cerrada en el servidor y baja el puntero de OT activa."""
    marca = json.dumps(
        {
            "cliente": lote["cliente"],
            "numero": lote["numero"],
            "equipos": total,
            "cerrado": datetime.now().isoformat(timespec="seconds"),
            "cerrado_por": socket.gethostname(),
        },
        ensure_ascii=False,
        indent=2,
    )
    _subir_texto(
        cliente, marca, ruta_remota(ruta_remota_lote(lote), MARCADOR_CERRADO)
    )
    activo = leer_lote_activo_remoto(cliente)
    if activo and os.path.normcase(activo["ruta"]) == os.path.normcase(lote["ruta"]):
        despublicar_lote_activo(cliente)



def enviar_pendientes(pendientes, progreso=lambda texto: None):
    """
    Sube las OT pendientes (ver lotes.pendientes_envio) y marca cada una como
    enviada. Pensado para correr en un hilo: 'progreso' recibe un texto por OT.

    Hace primero un backup (nunca lanza: si falla, el envío sigue). Conexión y
    destino se validan juntos y ANTES del primer archivo: si algo está mal,
    ninguna OT queda marcada como enviada y se lanza RuntimeError.

    Devuelve (enviados, subidos, errores, ruta_backup).
    """
    ruta_bk = crear_backup("envio")
    errores = []
    enviados = 0
    subidos = 0

    try:
        cliente = abrir_conexion_scp()
    except Exception as e:
        raise ErrorEnvio(str(e), ruta_bk) from e
    try:
        verificar_destino_remoto(cliente)
    except Exception as e:
        cliente.close()
        raise ErrorEnvio(str(e), ruta_bk) from e

    try:
        for i, (grupo, cli, nombre_ot, ruta_origen, _abierta) in enumerate(
            pendientes, 1
        ):
            progreso(f"[{i}/{len(pendientes)}] {cli} · {nombre_ot}")
            try:
                subidos += enviar_ot_por_scp(cliente, grupo, cli, nombre_ot, ruta_origen)
                marcar_enviado(ruta_origen)
                enviados += 1
            except Exception as e:
                errores.append(f"{cli}/{nombre_ot}: {e}")
                print(f"Error enviando {cli}/{nombre_ot}: {e}")
    finally:
        try:
            cliente.close()
        except Exception:
            pass
    return enviados, subidos, errores, ruta_bk


class ErrorEnvio(RuntimeError):
    """Fallo fatal del envío (conexión o destino). Lleva la ruta del backup."""

    def __init__(self, mensaje, ruta_backup=None):
        super().__init__(mensaje)
        self.ruta_backup = ruta_backup


def con_conexion(tarea):
    """Abre la conexión, corre tarea(cliente) y la cierra siempre."""
    cliente = abrir_conexion_scp()
    try:
        return tarea(cliente)
    finally:
        try:
            cliente.close()
        except Exception:
            pass
