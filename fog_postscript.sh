#!/bin/bash
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
[ -f "${postdownpath}/id_clonado" ]      || faltan="$faltan id_clonado"
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
cp "${postdownpath}/id_clonado" "$DEST"/
cp "${postdownpath}/fog_postscript.bat" "$STARTUP"/

sync
umount /ntfs

echo "¡REPORTE3 inyectado en C:\\${DEST_REL//\//\\} y programado en el arranque!"
exit 0
