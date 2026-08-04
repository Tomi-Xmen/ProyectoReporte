#!/bin/bash
# ===========================================================================
#  Post-download script de FOG — inyecta REPORTE3 en el equipo recién clonado
# ---------------------------------------------------------------------------
#  Corre en el Linux de FOG, con la imagen ya escrita y antes del reboot.
#  NO ejecuta el programa: solo deja los archivos y lo programa en el arranque
#  de Windows, porque acá todavía no hay Windows corriendo.
#
#  En el servidor de FOG, ${postdownpath} tiene que contener:
#
#      REPORTE3/            la carpeta COMPLETA de dist\ (exe + _internal)
#      id_ed25519           la clave privada SSH  <-- SIN esto no puede enviar
#      fog_postscript.bat   el lanzador que corre en el primer login
#
#  El build es "onedir": REPORTE3.exe suelto NO arranca, necesita _internal
#  al lado. Por eso se copia la carpeta entera.
#
#  Antes de clonar, en la PC central: abrir REPORTE3 -> PANEL DE CLONACION ->
#  "Publicar OT activa". Todo lo que se clone después cae en esa OT.
# ===========================================================================

# Cargar las funciones internas de FOG (CRÍTICO)
. /usr/share/fog/lib/funcs.sh

DEST_REL="Users/Public/Desktop/Reporte"
STARTUP_REL="ProgramData/Microsoft/Windows/Start Menu/Programs/StartUp"

echo "Inyectando REPORTE3 en el equipo clonado..."

# 1. Punto de montaje
mkdir -p /ntfs

# 2. Buscar la partición de Windows a prueba de fallos.
#    Si $osdiskpart viene vacío, se prueba cada NTFS hasta encontrar la que
#    tenga la carpeta Windows.
if [ -z "$osdiskpart" ]; then
    for part in $(blkid -o device -t TYPE=ntfs); do
        ntfs-3g "$part" /ntfs >/dev/null 2>&1 || continue
        if [ -d "/ntfs/Windows" ]; then
            osdiskpart="$part"
            umount /ntfs >/dev/null 2>&1
            break
        fi
        umount /ntfs >/dev/null 2>&1
    done
fi

if [ -z "$osdiskpart" ]; then
    echo "ERROR: no se encontró la partición de Windows"
    exit 1
fi

echo "Montando disco de Windows ($osdiskpart)..."
if ! ntfs-3g "$osdiskpart" /ntfs; then
    echo "ERROR: no se pudo montar $osdiskpart"
    exit 1
fi

# 3. Verificar que esté todo lo que hay que copiar ANTES de tocar el disco.
#    Si falta la clave el programa clona igual pero no puede enviar nada, y el
#    equipo se pierde sin que nadie se entere hasta el inventario.
faltan=""
[ -d "${postdownpath}/REPORTE3" ]        || faltan="$faltan REPORTE3/"
[ -f "${postdownpath}/id_ed25519" ]      || faltan="$faltan id_ed25519"
[ -f "${postdownpath}/fog_postscript.bat" ] || faltan="$faltan fog_postscript.bat"
if [ -n "$faltan" ]; then
    echo "ERROR: falta en ${postdownpath}:$faltan"
    umount /ntfs
    exit 2
fi

# 4. Copiar el programa completo, la clave y el lanzador.
DEST="/ntfs/${DEST_REL}"
STARTUP="/ntfs/${STARTUP_REL}"
mkdir -p "$DEST" "$STARTUP"

cp -r "${postdownpath}/REPORTE3/." "$DEST"/
cp "${postdownpath}/id_ed25519" "$DEST"/
cp "${postdownpath}/fog_postscript.bat" "$STARTUP"/

sync
umount /ntfs

echo "¡REPORTE3 inyectado en C:\\${DEST_REL//\//\\} y programado en el arranque!"
exit 0
