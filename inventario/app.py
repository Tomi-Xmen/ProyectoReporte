"""
Punto de entrada: decide el modo según los argumentos y, solo si hace falta
una ventana, carga Qt.

    REPORTE3.exe                       menú normal
    REPORTE3.exe --verificar           chequea el envío desde ESTE equipo
    REPORTE3.exe --clonacion           registro automático del equipo clonado
    REPORTE3.exe --clonacion --sin-ui  idem, sin ninguna ventana
"""

import sys
import traceback

from .nucleo import config

AYUDA = (
    "REPORTE3 — Sistema de Control de Inventario\n\n"
    "  REPORTE3.exe                       menú normal\n"
    "  REPORTE3.exe --verificar           chequea el envío desde ESTE equipo\n"
    "  REPORTE3.exe --clonacion           registro automático del equipo,\n"
    "                                     envía cuando lo confirmás\n"
    "  REPORTE3.exe --clonacion --sin-ui  sin ninguna ventana: en un cmd\n"
    "                                     pide las observaciones por\n"
    "                                     consola antes de enviar; sin\n"
    "                                     consola manda directo.\n"
    "                                     Ctrl+C cancela.\n\n"
    "Códigos de salida en modo clonación:\n"
    "  0 enviado   1 cancelado   2 sin conexión\n"
    "  3 sin OT activa   4 falló el escaneo   5 error inesperado\n"
)


def _ocultar_consola():
    """
    Si el .exe se compila con consola (para que el post-script de FOG se quede
    con la traza de --clonacion), en el uso diario esa ventana negra detrás
    del menú no aporta nada: se esconde apenas arranca la GUI.
    """
    try:
        import ctypes

        ventana_consola = ctypes.windll.kernel32.GetConsoleWindow()
        if ventana_consola:
            ctypes.windll.user32.ShowWindow(ventana_consola, 0)  # SW_HIDE
    except Exception:
        pass


def _ruta_icono():
    import os

    for base in (getattr(sys, "_MEIPASS", None), config.ruta_base_proyecto):
        if base:
            ruta = os.path.join(base, "favicon.ico")
            if os.path.isfile(ruta):
                return ruta
    return None


def iniciar_interfaz_principal():
    _ocultar_consola()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .ui import avisos
    from .ui.tema import aplicar_tema
    from .ui.ventana_principal import VentanaPrincipal

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Control de Inventario")
    app.setOrganizationName("Arrienda.cl")
    aplicar_tema(app)
    icono = _ruta_icono()
    if icono:
        app.setWindowIcon(QIcon(icono))

    ventana = VentanaPrincipal()

    # Un error no previsto en cualquier botón se muestra en vez de perderse
    # en una consola que nadie ve; la app sigue abierta.
    def _al_fallar(tipo, valor, tb):
        detalle = "".join(traceback.format_exception(tipo, valor, tb))
        print(detalle, file=sys.stderr)
        avisos.error(ventana, "Error inesperado", str(valor) or tipo.__name__, detalle)

    sys.excepthook = _al_fallar
    ventana.show()
    return app.exec()


def main(argv=None):
    """
    Sin argumentos abre el menú de siempre; con --clonacion corre el flujo
    automático del equipo recién clonado.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    # El .bat redirige la salida a un log con la codificación de la consola
    # (cp1252/cp850). Sin esto, un acento que no entre revienta el print y se
    # pierde el registro de un equipo ya clonado por un problema de tipografía.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except Exception:
            pass

    if "--ayuda" in argv or "-h" in argv or "--help" in argv:
        print(AYUDA)
        return 0

    if "--verificar" in argv:
        from .nucleo.clonacion import diagnostico_scp

        return diagnostico_scp()

    if "--clonacion" in argv:
        from .nucleo.clonacion import modo_clonacion

        sin_ui = "--sin-ui" in argv
        if sin_ui:
            return modo_clonacion(sin_ui=True)
        from .ui import clonacion as ui_clonacion

        return modo_clonacion(
            pedir_observaciones=ui_clonacion.pedir_observaciones,
            avisar_error=ui_clonacion.avisar_error,
            avisar_ok=ui_clonacion.avisar_ok,
        )

    return iniciar_interfaz_principal()
