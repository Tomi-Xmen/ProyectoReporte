"""
Cargar la key de una caja en el Office instalado y activarlo, con el
OSPP.VBS que trae el propio Office (cscript OSPP.VBS /inpkey: y /act).

Solo para las versiones que se activan por key (2013/2016/2019). Las
2021/2024 están ligadas a una cuenta outlook y se manejan aparte: la app
las asigna pero no toca el sistema.

OSPP necesita permisos de administrador. Si el programa no los tiene, se
pide elevación UNA vez para las dos órdenes: corren en un .cmd temporal que
deja su salida en un archivo, porque un proceso elevado no puede devolverla
por la consola. El .cmd lleva la key, así que se borra siempre al terminar.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

from .licencias_office import ACTIVADA, SOLO_CARGADA

VERSIONES_CON_KEY = ("2013", "2016", "2019")

# Carpeta de Office por versión (2016 y 2019 comparten Office16).
_CARPETAS = {"2013": "Office15", "2016": "Office16", "2019": "Office16"}

# Dónde deja OSPP.VBS cada tipo de instalación, dentro de Program Files: la
# MSI en 'Microsoft Office\OfficeNN'; la Click-to-Run (la de los zips del
# servidor de paquetes) también en '…\root\OfficeNN', y la 2013 C2R bajo
# 'Microsoft Office 15'.
_SUBRUTAS = (
    ("Microsoft Office", "{carpeta}"),
    ("Microsoft Office", "root", "{carpeta}"),
    ("Microsoft Office 15", "root", "{carpeta}"),
)

_MARCA_KEY = "===INPKEY==="
_MARCA_ACT = "===ACT==="
_TIMEOUT = 240  # /act habla con Microsoft: puede tardar


class ErrorActivacion(Exception):
    pass


def aplica(version):
    """True si esa versión se activa cargando la key en el equipo."""
    return version in VERSIONES_CON_KEY


def ruta_ospp(version):
    """OSPP.VBS del Office de esa versión instalado en este equipo, o ''."""
    carpeta = _CARPETAS.get(version)
    if not carpeta:
        return ""
    for variable, defecto in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        for subruta in _SUBRUTAS:
            ruta = os.path.join(
                os.environ.get(variable, defecto),
                *(p.format(carpeta=carpeta) for p in subruta),
                "OSPP.VBS",
            )
            if os.path.exists(ruta):
                return ruta
    return ""


def office_instalado(version):
    """True si en este equipo está el Office de esa versión (se ve por su OSPP)."""
    return bool(ruta_ospp(version))


def es_admin():
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def script_cmd(ospp, clave, salida, activar=True):
    """Contenido del .cmd: carga la key, activa y deja todo en 'salida'."""
    lineas = [
        "@echo off",
        "(",
        f"echo {_MARCA_KEY}",
        f'cscript //nologo "{ospp}" /inpkey:{clave}',
    ]
    if activar:
        lineas += [f"echo {_MARCA_ACT}", f'cscript //nologo "{ospp}" /act']
    lineas.append(f') > "{salida}" 2>&1')
    return "\r\n".join(lineas) + "\r\n"


def _startupinfo_oculto():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


def _correr_script(script, salida):
    """Corre el .cmd (elevado si hace falta) y devuelve lo que escribió."""
    if es_admin():
        subprocess.run(
            ["cmd", "/c", script],
            timeout=_TIMEOUT,
            startupinfo=_startupinfo_oculto(),
            check=False,
        )
    else:
        ruta_ps = script.replace("'", "''")
        resultado = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Start-Process -FilePath '{ruta_ps}' -Verb RunAs -Wait -WindowStyle Hidden",
            ],
            timeout=_TIMEOUT,
            startupinfo=_startupinfo_oculto(),
            capture_output=True,
            check=False,
        )
        if resultado.returncode != 0:
            raise ErrorActivacion(
                "No se dio el permiso de administrador: la key no se cargó.\n\n"
                "Para activar Office hay que aceptar el aviso de Windows."
            )
    try:
        with open(salida, "rb") as f:
            # cscript escribe en la página de códigos de la consola (850 en
            # un Windows en español); los mensajes de OSPP son ASCII igual.
            return f.read().decode("cp850", errors="replace")
    except OSError as e:
        raise ErrorActivacion(f"OSPP no dejó resultado: {e}") from e


def _error_ospp(texto):
    """'ERROR DESCRIPTION: …' o 'ERROR CODE: …' de la salida de OSPP, o el final."""
    for patron in (r"ERROR DESCRIPTION:\s*(.+)", r"ERROR CODE:\s*(.+)"):
        m = re.search(patron, texto)
        if m:
            return m.group(1).strip()
    lineas = [l.strip() for l in texto.splitlines() if l.strip() and "---" not in l]
    return lineas[-1] if lineas else "OSPP no respondió"


def interpretar(salida):
    """
    (estado, detalle) desde la salida del .cmd: ACTIVADA, SOLO_CARGADA (la
    key quedó pero /act falló, p. ej. sin internet) o 'error'.
    """
    _, _, despues = salida.partition(_MARCA_KEY)
    parte_key, _, parte_act = despues.partition(_MARCA_ACT)
    if "<Product key installation successful>" not in parte_key:
        return "error", f"Office no aceptó la key: {_error_ospp(parte_key or salida)}"
    if not parte_act:
        return SOLO_CARGADA, "Key cargada (sin activar)."
    if "<Product activation successful>" in parte_act:
        return ACTIVADA, "Office activado."
    return SOLO_CARGADA, f"Key cargada, pero no se pudo activar: {_error_ospp(parte_act)}"


def cargar_y_activar(clave, version, activar=True):
    """
    Carga la key en el Office de este equipo y lo activa. Devuelve
    (estado, detalle) como interpretar(); lanza ErrorActivacion si no se
    pudo ni intentar (no es Windows, no está ese Office, se negó el permiso).
    """
    if not aplica(version):
        raise ErrorActivacion(f"Office {version or '?'} no se activa por key desde la app.")
    if sys.platform != "win32":
        raise ErrorActivacion("Cargar la key solo se puede en Windows.")
    ospp = ruta_ospp(version)
    if not ospp:
        raise ErrorActivacion(
            f"No se encontró Office {version} instalado en este equipo "
            f"(falta {_CARPETAS[version]}\\OSPP.VBS)."
        )
    carpeta = tempfile.mkdtemp(prefix="office_")
    try:
        script = os.path.join(carpeta, "activar.cmd")
        salida = os.path.join(carpeta, "salida.txt")
        # cmd lee el .cmd en la página OEM: así una ruta con tildes
        # (C:\Users\Tomás\…) llega igual.
        with open(script, "w", encoding="oem") as f:
            f.write(script_cmd(ospp, clave, salida, activar))
        try:
            texto = _correr_script(script, salida)
        except subprocess.TimeoutExpired as e:
            raise ErrorActivacion("OSPP tardó demasiado y se cortó.") from e
        return interpretar(texto)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
