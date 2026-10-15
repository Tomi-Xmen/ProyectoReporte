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
    modulos/           mover OT, transformadores, etiquetas, panel de clonación
tests/                 pruebas (pytest)
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
