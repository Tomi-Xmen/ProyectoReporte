"""
Modo clonación (sin menú) — para el post-script de FOG.

Se invoca como:  REPORTE3.exe --clonacion [--sin-ui]

Corre solo en el equipo recién clonado: pregunta al servidor a qué OT
pertenece, escanea, pide las observaciones y manda el JSON por SCP. No hay
menú ni OT que elegir, y el envío se manda solo cuando el operador lo
confirma: no hay envío automático por tiempo.

Este módulo no conoce la interfaz gráfica: la ventana de observaciones y los
avisos llegan como funciones (ver inventario.ui.clonacion). Con --sin-ui no se
carga Qt en absoluto, que es lo que necesita el post-script de FOG: ahí no hay
nadie para cerrar un aviso y el proceso se quedaría colgado sin devolver el
código de salida.

Que no haya ventanas no quiere decir que no haya operador: si el programa
corre en un cmd, las observaciones se piden por consola, y recién después se
hace el SCP. Sin consola (post-script de FOG de verdad) se manda directo.
"""

import os
import socket
import sys
import tempfile

from . import config
from .config import (
    SCP_DESTINO,
    SCP_HOST,
    SCP_PUERTO,
    SCP_TIMEOUT,
    SCP_USUARIO,
    ruta_base_proyecto,
)
from .escaner import get_inventory_fast
from .lotes import etiqueta_lote, guardar_equipo_general, ruta_json_equipo
from .remoto import (
    abrir_conexion_scp,
    candidatas_clave_ssh,
    correr_remoto,
    enviar_equipo_por_scp,
    leer_lote_activo_remoto,
    mkdir_remoto,
    resolver_clave_ssh,
    ruta_remota,
    verificar_destino_remoto,
)

if config.SCP_AVAILABLE:
    from scp import SCPClient


def _log_clon(texto):
    """Traza para el post-script de FOG, que se queda con la salida estándar."""
    print(f"[REPORTE3] {texto}", flush=True)


def _hay_consola():
    """
    ¿Hay alguien del otro lado del teclado? Con el .exe lanzado desde un cmd
    sys.stdin es la consola; lanzado por el post-script de FOG o con la entrada
    redirigida, no hay a quién preguntarle nada.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _observaciones_consola(data, lote):
    """
    La ventana de observaciones, pero en la consola. Mismo contrato que
    _ventana_observaciones: devuelve (observaciones, detalle_componentes,
    enviar, tiene_office, office_key, version_office), y todo esto pasa ANTES
    del SCP. Espera a que el operador conteste, sin envío automático por
    tiempo.

    Sin consola no tiene sentido pedir componente por componente como en la
    ventana: si hay fallas, quedan anotadas en un único ítem "Estado general"
    con la observación que dé el operador.
    """
    print("")
    print("=" * 64)
    print(f"  EQUIPO ESCANEADO - {etiqueta_lote(lote)}")
    print("=" * 64)
    for etiqueta, valor in (
        ("Modelo", data.get("model", "?")),
        ("N de Serie", data.get("serial", "?")),
        ("Procesador", data.get("cpu", "?")),
        ("Licencia Windows", data.get("key", "N/A")),
    ):
        print(f"  {etiqueta:<18}{valor}")
    print("-" * 64)
    print("  Ctrl+C cancela el registro.")
    print("")

    try:
        obs = input("Observaciones (Enter = ninguna): ").strip()
        resp = input("¿El equipo tiene fallas? [s/N]: ").strip()
        tiene_fallas = resp.lower().startswith("s")
        componentes = (
            [{"nombre": "Estado general", "estado": "MALO", "obs": obs}]
            if tiene_fallas
            else []
        )
        resp_office = input("¿Va con Office? [s/N]: ").strip()
        tiene_office = resp_office.lower().startswith("s")
        version_office, office_key = "", ""
        if tiene_office:
            version_office = (
                input("Versión de Office (Enter = 2016): ").strip() or "2016"
            )
            office_key = input("Key de Office (Enter = sin key): ").strip()
        return obs, componentes, True, tiene_office, office_key, version_office
    except KeyboardInterrupt:
        print("\n[REPORTE3] Cancelado por el operador.", flush=True)
        return "", [], False, False, "", ""



def _sin_aviso(*_args):
    pass


def modo_clonacion(
    sin_ui=False,
    pedir_observaciones=None,
    avisar_error=_sin_aviso,
    avisar_ok=_sin_aviso,
):
    """
    Flujo completo del equipo clonado. Devuelve el código de salida del proceso
    (0 = enviado), pensado para que el post-script de FOG sepa si funcionó.

    pedir_observaciones(data, lote) es la ventana gráfica; devuelve la misma
    tupla que _observaciones_consola. avisar_error(titulo, detalle) y
    avisar_ok(data, lote) muestran el resultado. Con sin_ui=True no se usa
    ninguna: si corre en un cmd las observaciones se piden por consola antes
    del SCP, y si no hay consola el equipo se manda sin observaciones. Los
    errores quedan solo en el log.
    """
    if sin_ui:
        avisar_error = avisar_ok = _sin_aviso
    _log_clon(f"Modo clonación en {socket.gethostname()}")

    try:
        cliente = abrir_conexion_scp()
    except Exception as e:
        _log_clon(f"ERROR de conexión: {e}")
        avisar_error("No se pudo conectar al servidor", str(e))
        return 2

    try:
        lote = leer_lote_activo_remoto(cliente)
        if not lote:
            msg = (
                "No hay ninguna OT activa publicada en el servidor.\n\n"
                "Activá una OT desde el panel central antes de clonar."
            )
            _log_clon("ERROR: sin OT activa publicada")
            avisar_error("Sin OT activa", msg)
            return 3
        _log_clon(f"OT activa: {etiqueta_lote(lote)}")

        _log_clon("Escaneando hardware…")
        data = get_inventory_fast()
        if not data:
            _log_clon("ERROR: el escaneo falló")
            avisar_error(
                "No se pudo escanear",
                "El escaneo de hardware falló. Revisá el registro y reintentá.",
            )
            return 4
        _log_clon(f"Equipo: {data.get('model')} / {data.get('serial')}")

        if sin_ui and _hay_consola():
            respuesta = _observaciones_consola(data, lote)
        elif sin_ui or pedir_observaciones is None:
            _log_clon("Sin UI y sin consola: se envía sin observaciones.")
            respuesta = ("", [], True, False, "", "")
        else:
            respuesta = pedir_observaciones(data, lote)
        (
            obs,
            detalle_componentes,
            enviar,
            tiene_office,
            office_key,
            version_office,
        ) = respuesta
        if not enviar:
            _log_clon("Cancelado por el operador.")
            return 1

        # Se guarda con la misma función que el flujo normal: el JSON queda
        # idéntico al de un escaneo manual, así el panel y la reconstrucción
        # no tienen que distinguir de dónde vino.
        guardar_equipo_general(
            lote, data, obs, tiene_office, office_key, version_office, detalle_componentes
        )
        ruta_json = ruta_json_equipo(lote, data["serial"])
        _log_clon(f"JSON local: {ruta_json}")

        destino = enviar_equipo_por_scp(cliente, lote, ruta_json)
        _log_clon(f"ENVIADO -> {destino}")
        avisar_ok(data, lote)
        return 0
    except Exception as e:
        _log_clon(f"ERROR inesperado: {e}")
        avisar_error("Falló el envío", str(e))
        return 5
    finally:
        try:
            cliente.close()
        except Exception:
            pass


def diagnostico_scp():
    """
    Chequeo completo del envío, corriendo DESDE ESTE equipo. Código 0 = todo OK.

    Va dentro del ejecutable a propósito: el equipo que importa verificar es el
    clonado, y ahí no hay Python ni código fuente, solo el .exe. Verificar desde
    el servidor de FOG no sirve —FOG nunca habla con el NAS, solo copia archivos
    al disco de Windows—, y verificar desde la PC de escritorio tampoco prueba
    que el equipo clonado tenga la clave donde corresponde.
    """
    ok, mal = "  [OK]   ", "  [FALLA] "
    print("\n=== Configuración ===")
    print(f"  Ejecutable : {ruta_base_proyecto}")
    print(f"  Servidor   : {SCP_USUARIO}@{SCP_HOST}:{SCP_PUERTO}")
    print(f"  Destino    : {SCP_DESTINO}")

    if not config.SCP_AVAILABLE:
        print(f"\n{mal}Falta paramiko/scp en el ejecutable.")
        print("       Recompilá con el .spec (trae los hiddenimports).")
        return 1

    print("\n=== 1. Clave privada ===")
    ruta = resolver_clave_ssh()
    for candidata in candidatas_clave_ssh():
        marca = "  <-- se usa esta" if candidata == ruta else ""
        print(f"    {candidata}{marca}")
    if not ruta:
        print(f"{mal}No hay clave en ninguna de esas rutas.")
        print("       En un equipo clonado la clave va JUNTO al .exe.")
        return 1
    print(f"{ok}Clave encontrada")

    print("\n=== 2. Conexión ===")
    try:
        cliente = abrir_conexion_scp()
    except Exception as e:
        print(f"{mal}{e}")
        return 1
    print(f"{ok}Conectado y autenticado")

    try:
        print("\n=== 3. Permisos en el servidor ===")
        codigo, salida, _ = correr_remoto(cliente, "id")
        if codigo != 0 or not salida:
            print(f"{mal}El usuario no puede ejecutar comandos (¿shell nologin?)")
            return 1
        print(f"{ok}{salida}")
        try:
            verificar_destino_remoto(cliente)
        except Exception as e:
            print(f"{mal}{e}")
            return 1
        print(f"{ok}Carpeta de destino escribible")

        print("\n=== 4. OT activa publicada ===")
        lote = leer_lote_activo_remoto(cliente)
        if lote:
            print(f"{ok}{etiqueta_lote(lote)}")
        else:
            # No es un fallo del equipo: es que en la central todavía no
            # publicaron la OT. Se distingue para no mandar a revisar la red.
            print("  [AVISO] No hay OT publicada.")
            print("       En la PC central: PANEL DE CLONACIÓN → Publicar OT activa.")

        print("\n=== 5. Subida real de prueba ===")
        local = os.path.join(tempfile.mkdtemp(), "prueba_scp.txt")
        with open(local, "w", encoding="utf-8") as f:
            f.write(f"prueba desde {socket.gethostname()}\n")
        carpeta = ruta_remota(SCP_DESTINO, "_prueba_scp")
        remoto = ruta_remota(carpeta, "prueba_scp.txt")
        try:
            mkdir_remoto(cliente, carpeta)
            with SCPClient(cliente.get_transport(), socket_timeout=SCP_TIMEOUT) as scp:
                scp.put(local, remote_path=remoto)
            codigo, salida, _ = correr_remoto(cliente, f"cat '{remoto}'")
            if codigo != 0 or socket.gethostname() not in salida:
                print(f"{mal}El archivo no llegó o no se pudo leer de vuelta")
                return 1
            print(f"{ok}Archivo subido y leído de vuelta")
        finally:
            correr_remoto(cliente, f"rm -rf '{carpeta}'")

        print("\n" + "=" * 56)
        print("  TODO LISTO — este equipo puede enviar.")
        print("=" * 56 + "\n")
        return 0
    finally:
        try:
            cliente.close()
        except Exception:
            pass

