# Reporte Móvil — estado y contexto

Resumen de la sesión del 2026-10-01 para retomar el trabajo. Léelo antes de
tocar `movil/`.

## Qué es

App Flask chica (`app.py`, gunicorn en `:5070`) que corre en el servidor
OpenMediaVault `192.168.10.15` (VM 106 en Proxmox) como servicio systemd
`reporte-movil`, usuario `Reporte`. Lee directo el árbol que `REPORTE3.py`
sube por SCP:

```
/srv/dev-disk-by-uuid-50e34ae9-.../DocumentosLab/Reportes_Guardados
  _control/.lote_activo.json
  ENTREGA/<CLIENTE>/OT-xxx/*.json      un JSON por equipo
  RETIROS/<CLIENTE>/GUIA-xxx/*.json
  <lote>/.esperados  .cerrado  .transformadores
```

## Acceso desde el celular: Tailscale

- El wifi de la oficina **no llega** a `192.168.10.x`: el router
  `192.168.2.1` no tiene ruta a esa red (solo este PC la tiene, por cable:
  `192.168.10.0/24 via 192.168.2.95`). Por eso se usa Tailscale.
- Tailscale instalado en el servidor (`openmediavault`, `100.120.174.122`),
  en el celular (`u23`) y en este PC (`tomi`). **Funciona.**
- La cámara exige HTTPS → `sudo tailscale serve --bg 5070` en el servidor
  (MagicDNS + HTTPS Certificates activados en el admin de Tailscale). Se
  entra por `https://<servidor>.<tailnet>.ts.net`. **Funciona.**
- Fotos del celular al PC: Taildrop (compartir → Tailscale → `tomi`); llegan
  a `~/Downloads`.

## Funcionalidades

1. **Login** con una clave (`MOVIL_CLAVE`), sesión de 90 días.
2. **OT abiertas**: Entregas y Retiros no cerrados, marca la OT activa.
3. **Detalle de OT**: equipos llegados vs `.esperados` (ok / sobra / falta),
   modelo, fecha, trafo.
4. **Módulo 2 — transformadores** (`/lote/.../transformadores`):
   - Se escanea **solo el trafo** (el equipo ya lo registra REPORTE3). Se
     asigna solo al **siguiente equipo sin trafo en orden de escaneo** (el
     más viejo primero), igual que la pistola en el módulo del escritorio.
   - Tocar un equipo de la lista → el próximo trafo va a ese (para corregir).
   - Bloquea: OT cerrada, serial de un equipo escaneado como trafo, sin
     equipos libres. Pide "Guardar igual": trafo ya en otro equipo,
     reemplazar el de un equipo elegido.
   - "Quitar" borra lo cargado desde el celular.
   - Se guarda en `<lote>/.transformadores` (sin `.json` a propósito):
     `{"SERIAL_EQUIPO": {"sn": "...", "fecha": "..."}}`. **Nunca** se tocan
     los JSON de equipos: el escritorio los re-sube por SCP y pisaría el
     cambio.
5. **Fusión en el escritorio** (`REPORTE3.py`, `leer_transf_movil` +
   `abrir_modulo_agregar_transformador`): al abrir "Agregar
   transformadores" trae `.transformadores` por SSH y rellena en verde las
   filas vacías; no pisa lo ya cargado (lo distinto se avisa). Después
   GUARDAR + enviar como siempre. **Falta recompilar el .exe en Windows.**
   Si se vacía a propósito en el escritorio un trafo que vino del celular,
   vuelve a aparecer: hay que quitarlo también desde el celular.

## Cámara (en `templates/transformadores.html`)

- Botón 📷 al lado del campo. Cuadro de lectura **ajustable** (arrastrar
  para mover, esquina ↘ para el tamaño; se recuerda en localStorage). Solo
  se lee lo de adentro, recortado a la resolución completa de la cámara
  (se agranda ×2 si el cuadro es chico).
- Lectores en orden: `BarcodeDetector` nativo → zxing-js
  (`static/zxing.min.js`, Data Matrix + QR) → jsQR (`static/jsQR.js`, QR).
  Librerías servidas localmente, Apache 2.0 (licencias en `static/`).
- Códigos 1D: dos lecturas iguales seguidas; QR/Data Matrix: una basta.
- Tras guardar, la cámara se reabre sola para el siguiente trafo; la última
  etiqueta guardada se ignora (cuadro naranja).
- Zoom 🔍 y linterna 🔦 si el celular los ofrece. Línea gris de
  diagnóstico: lectores disponibles y resolución de la cámara.
- Probado en Chromium headless con cámara falsa (QR chico de 46 px y Data
  Matrix sintético): lee y guarda bien.

## Problema abierto: los trafos HP 45 W

Fotos de la etiqueta en `~/Downloads/20261001_161716.jpg` y `..._161717.jpg`
(fabricante Lite-On, modelo TPN-LA15):

- La serie que interesa es el **CT: `WHHRE0A1RCQCTS`** (última línea
  impresa, 14 caracteres, empieza con W).
- `9901662401` es otro número de la etiqueta (no es la serie).
- Al lado hay un **Data Matrix** (no QR) **grabado claro sobre fondo
  oscuro**, poco contraste y con un rayón.
- En el celular "funcionó a medias": leyó algo pero **guardó números que no
  son el CT**. Ni zxing-js ni zxing-cpp lograron decodificar el Data Matrix
  desde las fotos.

**Siguiente paso:** conseguir el texto exacto que quedó guardado (lista del
celular, junto al 📱, o en el servidor):

```bash
find /srv/dev-disk-by-uuid-50e34ae9-5743-420d-b093-89dfd29299cd/DocumentosLab/Reportes_Guardados \
  -name .transformadores -newermt today -exec sh -c 'echo "== $1"; cat "$1"' _ {} \;
```

- Si el CT viene dentro del contenido → extraerlo (p. ej. el token de 14
  caracteres que empieza con W).
- Si no viene → el Data Matrix no sirve; alternativas: OCR del texto
  `CT:` impreso, o escribirlo a mano/pistola.

## Pendientes técnicos

- Todo commiteado en la rama `reporte-movil` (sin merge a `main`, sin
  push). El bug de zxing (`decode()` reseteaba los hints de `setHints`) ya
  está corregido con `decodeWithState()`.
- `__pycache__/REPORTE3.cpython-314.pyc` está versionado y cambia solo:
  sacarlo con `git rm --cached` y agregar `__pycache__/` al `.gitignore`.
- Recompilar `REPORTE3.exe` (PyInstaller, Windows) para la fusión de trafos.
- Módulo 3 (crear sesiones de clonaje FOG desde el celular): sin empezar.
  Los tokens de FOG deben quedar solo en el servidor.

## Deploy

- `movil/deploy/subir.sh` (`-n` = prueba): `rsync --delete` a
  `/opt/reporte-movil` respetando `.env` y `venv/`, luego `chown` +
  restart. Por defecto `root@192.168.10.15` (`SERVIDOR=` para cambiarlo).
- **Nunca borrar `/opt/reporte-movil` a mano**: el 2026-10-01 se perdieron
  `.env` y `venv` así y el servicio quedó `Result: resources` ("Failed to
  load environment files"). Si pasa: recrear venv + `.env`,
  `systemctl reset-failed reporte-movil`, restart.
- Al actualizar, en el celular cerrar y reabrir Chrome (caché).
