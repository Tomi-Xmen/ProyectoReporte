# Sistema de Control de Inventario — Arrienda.cl

App de escritorio para escanear el hardware de un equipo, registrar entregas
y retiros por OT/guía y generar los reportes HTML y JSON. La interfaz está
hecha con **PySide6 (Qt)**.

## Estructura

```
REPORTE3.py            lanzador (el .exe se compila desde acá)
inventario/
  app.py               elige el modo: menú, --clonacion, --verificar
  nucleo/              lógica sin interfaz (se puede probar sin ventanas)
    config.py          servidor SCP, carpeta base, librerías opcionales
    escaner.py         script de PowerShell y lectura del hardware
    lotes.py           OT/guías en disco: guardar, cerrar, mover, backups
    escaneos.py        lector celular: elegir el serial y aplicarlo al lote
    gestion_lote.py    lector celular: cargadores, mover/quitar, guía/OT, cierre
    api_celular.py     lector celular: qué responde el PC a cada pedido
    reporte_vivo.py    reporte HTML servido con recarga automática
    sincronizacion.py  traer automático de la OT de clonación desde el servidor
    reporte_html.py    plantilla del reporte y entrada de cada equipo
    reconstruccion.py  rearmar HTML y FUSIONADO desde los JSON
    remoto.py          envío por SCP y control central de clonación
    fog.py             API de FOG (multicast)
    transformadores.py carga masiva de transformadores
    etiquetas.py       etiqueta manual de diagnóstico
    clonacion.py       modo clonación y diagnóstico (--verificar)
  ui/                  interfaz Qt
    tema.py            colores (claro/oscuro) y hoja de estilos
    widgets.py         piezas reutilizables (tarjetas, tablas, botones)
    tareas.py          trabajo en segundo plano sin congelar la ventana
    ventana_principal.py, dialogos.py, acciones.py, componentes.py
    servidor_celular.py  HTTP del lector celular (QtNetwork)
    reporte_vivo.py      HTTP del reporte en vivo (solo 127.0.0.1)
    modulos/           mover OT, transformadores, etiquetas, panel de clonación,
                       lector celular
tests/                 pruebas (pytest)
herramientas/          simular_celular.py: prueba el lector sin la app
android/               app Android del lector celular (ver android/README.md)
REPORTE3_tk.py         versión anterior en Tkinter (respaldo temporal)
```

La regla de la estructura: **`nucleo/` nunca importa nada de `ui/`**. Toda
pantalla nueva llama al núcleo; toda regla de negocio nueva va en el núcleo
con su test.

## Uso

```
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

.venv\Scripts\python REPORTE3.py                       menú
.venv\Scripts\python REPORTE3.py --clonacion           modo clonación
.venv\Scripts\python REPORTE3.py --clonacion --sin-ui  sin ventanas (FOG)
.venv\Scripts\python REPORTE3.py --verificar           diagnóstico del envío
```

La app sigue el modo claro/oscuro de Windows.

## Lector celular

Menú → **Lector celular** → **Encender**. El panel muestra un QR que la app
del celular escanea para emparejarse; desde ahí el celular registra
notebooks, monitores e impresoras y empareja transformadores en las OT y
guías abiertas, con los mismos JSON, HTML y FUSIONADO de siempre.

- Viene **apagado**: si nadie lo enciende no se abre ningún puerto.
- Funciona mientras el panel está abierto; al cerrarlo se desconecta.
- Cada encendido genera un token nuevo (el QR anterior deja de servir).
- Solo acepta conexiones de la red local. La primera vez Windows pregunta
  si permite el acceso en la red: hay que aceptar para redes privadas.
- El celular no cambia cuál es la OT activa del PC. Sí puede: elegir a qué
  equipo va cada cargador, mover o quitar equipos (lo quitado va a
  `Reportes_Guardados/_PAPELERA`), completar la guía/OT del lote en todos sus
  equipos y cerrar el lote (ver `android/README.md`).

## Reporte en vivo

En el panel **Lector celular** → **📡 Reportes en vivo**, o en el **Panel de
clonación** → **📡 Ver en vivo**, el reporte HTML se abre en el navegador y se
recarga solo cada vez que cambia el lote (escaneo, edición, equipo clonado que
llega). Es el mismo HTML de la carpeta de la OT, servido por el programa en
`127.0.0.1` (nadie más de la red lo ve) mientras el programa esté abierto.
Quitar un equipo con el botón del reporte es solo visual y se pierde en la
próxima recarga, como al reabrir el archivo.

## Clonación: traer automático

Con el **Panel de clonación** abierto, cada 15 s se trae del servidor lo que
mandaron los equipos clonados a la OT publicada y se regeneran su HTML y su
FUSIONADO, sin apretar "Traer y reconstruir". Solo baja lo nuevo o lo que
cambió en el servidor: lo cargado en esta PC (un cargador, una corrección) no
se pisa, y lo quitado a mano no vuelve salvo que el equipo mande un escaneo
nuevo. Los equipos que llegan se re-etiquetan con la guía/OT de la OT local.
Se pausa con la casilla del panel. El botón **Traer y reconstruir** hace lo
mismo a pedido (con las mismas reglas: no pisa ni devuelve lo quitado) y
además rearma el HTML y el FUSIONADO aunque no haya nada nuevo.

Para probarlo sin la app: en el panel, *Copiar datos de emparejamiento*, y

```
.venv\Scripts\python herramientas\simular_celular.py
```

Cada línea es un escaneo (sirve también la pistola USB). Las reglas para
reconocer cada tipo de serial van en `reglas_codigos.json`, junto al
programa (ver `cargar_reglas` en `escaneos.py`).

## Tests

```
.venv\Scripts\python -m pytest
```

## Compilar el .exe

```
.venv\Scripts\pyinstaller REPORTE3.spec
```

Sale en `dist/REPORTE3/`. Para los equipos clonados se copia la carpeta
completa junto con la clave `id_clonado` (ver `fog_postscript.bat`).
