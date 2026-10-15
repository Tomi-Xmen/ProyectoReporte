"""
Configuración global: carpeta base del programa, servidor SCP y librerías
opcionales.

Cambiar cualquiera de estas constantes exige recompilar el .exe: son la única
fuente de verdad de la conexión.
"""

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
SCP_HOST = "192.168.10.15"         # IP o nombre del servidor SSH
SCP_PUERTO = 22                    # puerto SSH
SCP_USUARIO = "Reporte"            # usuario SSH
# Clave privada SSH. Si queda vacía se intenta con las claves del agente o de
# ~/.ssh del usuario de Windows.
SCP_CLAVE = "/home/tomi/ProyectoReporte/id_clonado"
SCP_CLAVE_PASSPHRASE = ""          # vacío si la clave no tiene passphrase
# Carpeta base REMOTA (ruta estilo Linux). Debajo se replica el árbol completo
# <GRUPO>/<CLIENTE>/<OT-553>, igual que en local: así lo que se baja del
# servidor se reconstruye como OT canónica y no como "carpeta suelta".
SCP_DESTINO = (
    "/srv/dev-disk-by-uuid-50e34ae9-5743-420d-b093-89dfd29299cd"
    "/DocumentosLab/Reportes_Guardados"
)
SCP_TIMEOUT = 20                   # segundos para conectar antes de fallar
