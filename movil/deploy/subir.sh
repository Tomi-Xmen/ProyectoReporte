#!/usr/bin/env bash
# Sube movil/ al servidor y reinicia el servicio.
#
#   deploy/subir.sh        sube y reinicia
#   deploy/subir.sh -n     solo muestra qué copiaría/borraría (no toca nada)
#
# Deja /opt/reporte-movil igual al repo (--delete) SIN tocar lo que vive solo
# en el servidor: .env (claves) y venv/. Borrarlos deja el servicio caído con
# "Failed to load environment files" / Result: resources.
#
# Destino configurable: SERVIDOR=root@otra-ip deploy/subir.sh
set -euo pipefail

SERVIDOR="${SERVIDOR:-root@192.168.10.15}"
DESTINO="/opt/reporte-movil"
MOVIL="$(cd "$(dirname "$0")/.." && pwd)"

PRUEBA=()
if [[ "${1:-}" == "-n" ]]; then
    PRUEBA=(--dry-run)
    echo "== Prueba: no se cambia nada =="
fi

# Sin .env o venv el servicio no arranca: mejor avisar antes de subir.
if ! ssh "$SERVIDOR" "test -f '$DESTINO/.env' && test -x '$DESTINO/venv/bin/gunicorn'"; then
    echo "⚠ En $SERVIDOR falta $DESTINO/.env o $DESTINO/venv: ver pasos 2 y 3 de deploy/README.md." >&2
    exit 1
fi

# La barra final de "$MOVIL/" copia el CONTENIDO, no la carpeta movil/ adentro.
rsync -av --delete "${PRUEBA[@]}" \
    --exclude='.env' --exclude='venv/' --exclude='__pycache__/' \
    "$MOVIL/" "$SERVIDOR:$DESTINO/"

[[ ${#PRUEBA[@]} -gt 0 ]] && exit 0

ssh "$SERVIDOR" "chown -R Reporte: '$DESTINO' && systemctl restart reporte-movil && sleep 1 && systemctl is-active reporte-movil" \
    && echo "✅ Reporte Móvil actualizado" \
    || { echo "❌ El servicio no quedó activo. Ver: ssh $SERVIDOR journalctl -u reporte-movil -n 30" >&2; exit 1; }
