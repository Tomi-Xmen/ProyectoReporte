"""
Sistema de Control de Inventario — Arrienda.cl
==============================================

Lanzador del programa (el .exe se compila desde acá, ver REPORTE3.spec). El
código vive en el paquete 'inventario':

  inventario/nucleo/   lógica sin interfaz: escaneo, lotes (OT), reporte HTML,
                       reconstrucción, SCP, FOG y modo clonación.
  inventario/ui/       interfaz de escritorio en PySide6 (Qt).
  inventario/app.py    elige el modo según los argumentos (--clonacion, ...).
"""

import sys

from inventario.app import main

if __name__ == "__main__":
    sys.exit(main())
