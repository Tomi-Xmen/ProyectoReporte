"""
Configuración global: carpeta base del programa, servidor SCP y librerías
opcionales.

Los datos del servidor salen de 'servidor.json', junto al programa (ver
servidor.ejemplo.json). No van en el código: son de cada instalación, y el
archivo viaja con el .exe a los equipos clonados igual que la clave SSH.
"""

import json
import os
import sys

# --- SOLUCIÓN PYINSTALLER: el directorio de trabajo es siempre la carpeta real
# del programa. Todo lo que se guarda (Reportes_Guardados, la clave SSH que
# viaja al lado del .exe) cuelga de acá.
if getattr(sys, "frozen", False):
    # Compilado (.exe) con PyInstaller.
    ruta_base_proyecto = os.path.dirname(sys.executable)
else:
    # Script de Python normal: la raíz del repo, un nivel arriba del paquete.
    ruta_base_proyecto = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

os.chdir(ruta_base_proyecto)

# Librerías para el envío por SCP (SSH). Si faltan, el envío avisa en vez de
# reventar: el resto de la app (escaneo, reportes) no depende de ellas.
try:
    import paramiko  # noqa: F401
    from scp import SCPClient  # noqa: F401

    SCP_AVAILABLE = True
except ImportError:
    SCP_AVAILABLE = False

# Librería para hablar con la API de FOG (crear sesiones multicast). Igual que
# con paramiko/scp: si falta, avisa al usar el botón.
try:
    import requests  # noqa: F401

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ============================================================================
# ENVÍO AL SERVIDOR — por SCP sobre SSH.
#
# Al servidor viajan SOLO los archivos que son FUENTE DE VERDAD o entregables:
# los JSON individuales, el JSON FUSIONADO y el marcador '.cerrado'. El HTML
# NO se sube: es un derivado y se rearma allá con "RECONSTRUIR DESDE JSONs",
# que produce un reporte idéntico y 100% funcional.
# ============================================================================
ARCHIVO_SERVIDOR = "servidor.json"


def _leer_servidor():
    """Contenido de servidor.json, o {} si no está o no se puede leer."""
    try:
        with open(os.path.join(ruta_base_proyecto, ARCHIVO_SERVIDOR), encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


_servidor = _leer_servidor()
SCP_HOST = str(_servidor.get("host") or "")          # IP o nombre del servidor SSH
SCP_PUERTO = int(_servidor.get("puerto") or 22)     # puerto SSH
SCP_USUARIO = str(_servidor.get("usuario") or "")   # usuario SSH
# Clave privada SSH: el nombre del archivo junto al programa (o una ruta). Si
# no está se prueba con ~/.ssh del usuario (remoto.candidatas_clave_ssh).
SCP_CLAVE = str(_servidor.get("clave") or "")
SCP_CLAVE_PASSPHRASE = str(_servidor.get("passphrase") or "")  # vacío si no tiene
# Carpeta base REMOTA (ruta estilo Linux). Debajo se replica el árbol completo
# <GRUPO>/<CLIENTE>/<OT-553>, igual que en local: así lo que se baja del
# servidor se reconstruye como OT canónica y no como "carpeta suelta".
SCP_DESTINO = str(_servidor.get("destino") or "")
SCP_TIMEOUT = int(_servidor.get("timeout") or 20)   # segundos para conectar

# Sin host, usuario y carpeta no hay a dónde enviar: remoto lo avisa al conectar.
SERVIDOR_CONFIGURADO = bool(SCP_HOST and SCP_USUARIO and SCP_DESTINO)
