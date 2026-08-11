"""
Diagnóstico del envío por SCP — corré esto ANTES de mandar OT reales.

Usa la MISMA configuración y las mismas funciones que el reporte (las lee de
REPORTE3.py), así que si esto pasa, el botón "ENVIAR OT AL SERVIDOR" también.
Revisa en orden lo que suele fallar al preparar el servidor:

    1. que la clave privada exista y se pueda leer,
    2. que el servidor acepte al usuario con esa clave,
    3. que el usuario tenga shell de verdad (sin shell no hay SCP),
    4. que la carpeta base remota exista y sea escribible,
    5. una subida real de ida y vuelta, que después se borra.

    python verificar_scp.py
"""

import importlib.util
import os
import sys
import tempfile


def _cargar_reporte3():
    """
    Carga REPORTE3.py por ruta explícita.

    No alcanza con 'import REPORTE3': el build onedir deja una CARPETA llamada
    REPORTE3 en dist\\, y si este script corre desde ahí Python la toma como
    paquete namespace —sin ninguna constante adentro— y todo falla con un
    AttributeError que no dice nada. Buscando el .py se elige siempre el
    archivo correcto, se corra desde donde se corra.
    """
    aqui = os.path.dirname(os.path.abspath(__file__))
    candidatos = [
        os.path.join(aqui, "REPORTE3.py"),
        os.path.join(os.getcwd(), "REPORTE3.py"),
        os.path.join(os.path.dirname(aqui), "REPORTE3.py"),
    ]
    for ruta in candidatos:
        if os.path.isfile(ruta):
            spec = importlib.util.spec_from_file_location("REPORTE3", ruta)
            modulo = importlib.util.module_from_spec(spec)
            sys.modules["REPORTE3"] = modulo
            spec.loader.exec_module(modulo)
            return modulo, ruta
    print("No se encontró REPORTE3.py. Se buscó en:")
    for ruta in candidatos:
        print(f"  • {ruta}")
    print("\nCorré este script desde la carpeta del proyecto (donde está el .py).")
    sys.exit(1)


R, _RUTA_R = _cargar_reporte3()

ok = "  ✓ "
mal = "  ✗ "


def main():
    print("\n=== Configuración en REPORTE3.py ===")
    print(f"  Leído de : {_RUTA_R}")
    print(f"  Servidor : {R.SCP_USUARIO}@{R.SCP_HOST}:{R.SCP_PUERTO}")
    print(f"  Clave    : {R.SCP_CLAVE or '(claves del agente/~/.ssh)'}")
    print(f"  Destino  : {R.SCP_DESTINO}")

    if not R.SCP_AVAILABLE:
        print(f"\n{mal}Faltan las librerías: pip install paramiko scp")
        return 1

    print("\n=== 1. Clave privada ===")
    if R.SCP_CLAVE and not os.path.isfile(R.SCP_CLAVE):
        print(f"{mal}No existe el archivo: {R.SCP_CLAVE}")
        print("     Corregí SCP_CLAVE, o dejala vacía para usar las de ~/.ssh.")
        return 1
    print(f"{ok}La clave existe")
    pub = (R.SCP_CLAVE or "") + ".pub"
    if os.path.isfile(pub):
        with open(pub, encoding="utf-8") as f:
            print(f"\n  Esta es la línea que va en el servidor (authorized_keys):\n")
            print(f"    {f.read().strip()}\n")

    print("=== 2. Conexión y autenticación ===")
    try:
        cliente = R.abrir_conexion_scp()
    except Exception as e:
        print(f"{mal}{e}")
        return 1
    print(f"{ok}Conectado y autenticado")

    try:
        print("\n=== 3. Usuario y shell en el servidor ===")
        # Sin shell interactivo no corre 'mkdir' ni el 'scp -t' que usa el envío:
        # es el error más común al crear el usuario desde la interfaz del NAS.
        codigo, salida, _ = R._correr_remoto(cliente, "id")
        if codigo != 0 or not salida:
            print(f"{mal}El usuario no puede ejecutar comandos (¿shell nologin?)")
            print("     Asignale /bin/bash como shell en el servidor.")
            return 1
        print(f"{ok}{salida}")

        codigo, salida, _ = R._correr_remoto(cliente, "getent passwd $(id -un)")
        shell = salida.rsplit(":", 1)[-1] if salida else ""
        if "nologin" in shell or "false" in shell:
            print(f"{mal}Shell = {shell} — SCP no puede funcionar así")
            print("     Cambialo a /bin/bash en el servidor.")
            return 1
        print(f"{ok}Shell = {shell or 'desconocido'}")

        codigo, salida, _ = R._correr_remoto(cliente, "command -v scp")
        if codigo != 0:
            print(f"{mal}El servidor no tiene el binario 'scp' (apt install openssh-client)")
            return 1
        print(f"{ok}Binario scp presente: {salida}")

        print("\n=== 4. Carpeta base remota ===")
        try:
            R.verificar_destino_remoto(cliente)
        except Exception as e:
            print(f"{mal}{e}")
            _sugerir_rutas(cliente)
            return 1
        print(f"{ok}{R.SCP_DESTINO} existe y es escribible")

        print("\n=== 5. Subida real de prueba ===")
        local = os.path.join(tempfile.mkdtemp(), "prueba_scp.txt")
        with open(local, "w", encoding="utf-8") as f:
            f.write("prueba de envio\n")
        remoto = R._ruta_remota(R.SCP_DESTINO, "_prueba_scp", "prueba_scp.txt")
        try:
            R._mkdir_remoto(cliente, R._ruta_remota(R.SCP_DESTINO, "_prueba_scp"))
            with R.SCPClient(cliente.get_transport(), socket_timeout=R.SCP_TIMEOUT) as scp:
                scp.put(local, remote_path=remoto)
            codigo, salida, _ = R._correr_remoto(cliente, f"cat '{remoto}'")
            if codigo != 0 or "prueba de envio" not in salida:
                print(f"{mal}El archivo no llegó o no se pudo leer de vuelta")
                return 1
            print(f"{ok}Archivo subido y leído de vuelta correctamente")
        finally:
            R._correr_remoto(
                cliente, f"rm -rf '{R._ruta_remota(R.SCP_DESTINO, '_prueba_scp')}'"
            )
            print(f"{ok}Prueba borrada del servidor")

        print("\n" + "=" * 58)
        print("  TODO LISTO — el envío por SCP va a funcionar.")
        print("=" * 58 + "\n")
        return 0
    finally:
        cliente.close()


def _sugerir_rutas(cliente):
    """Lista las carpetas compartidas típicas del NAS para acertarle a la ruta."""
    print("\n  Carpetas que sí existen en el servidor:")
    for comando in ("ls -d /srv/*/ 2>/dev/null", "ls -d /export/*/ 2>/dev/null"):
        _codigo, salida, _ = R._correr_remoto(cliente, comando)
        for linea in salida.splitlines():
            print(f"    {linea}")


if __name__ == "__main__":
    sys.exit(main())
