import os
import sys

import pytest

# Qt sin pantalla: los tests de UI corren igual en CI o en una sesión remota.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inventario.nucleo import lotes  # noqa: E402  (config hace chdir al importarse)


def pytest_sessionfinish(session, exitstatus):
    """
    Cierra Qt en orden antes de que Python termine. Si no, las ventanas que
    dejaron los tests se destruyen después que la aplicación, en el orden que
    elija el recolector, y en algunos entornos (el CI) el proceso termina con
    un "Segmentation fault" aunque todos los tests hayan pasado.
    """
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    QThreadPool.globalInstance().waitForDone(10_000)
    app = QApplication.instance()
    if app is None:
        return
    for ventana in app.topLevelWidgets():
        ventana.close()
        ventana.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _sin_configuracion_real(monkeypatch, tmp_path):
    """
    Ningún test usa la configuración real de la PC donde corre: ni el
    servidor de servidor.json (la app se conectaría sola) ni el lector de
    lector_celular.json (se encendía y podía reescribir el archivo real).
    Un test que necesita el servidor lo activa a mano.
    """
    from inventario.nucleo import api_celular, config

    monkeypatch.setattr(config, "SERVIDOR_CONFIGURADO", False)
    monkeypatch.setattr(api_celular, "ARCHIVO_PREFERENCIAS", str(tmp_path / "lector_celular.json"))


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    """Directorio de trabajo vacío: Reportes_Guardados se arma adentro."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def datos_equipo(serial="ABC123", modelo="HP EliteBook 840"):
    """Lo mínimo que devuelve get_inventory_fast, sin correr PowerShell."""
    from inventario.nucleo.reporte_html import (
        render_filas_discos,
        render_filas_ram,
        render_filas_red,
    )

    ram = ["8GB|3200|PC4|Kingston|PN1"]
    discos = [{"desc": "SSD 256GB", "serial": "DISCO-01"}]
    disk_html, disk_serials = render_filas_discos(discos)
    return {
        "fecha": "01/01/2026 10:00",
        "host": "PC",
        "model": modelo,
        "serial": serial,
        "key": "AAAAA-BBBBB",
        "cpu": "Intel i5",
        "ram_html": render_filas_ram(ram),
        "ram_raw": ram,
        "disk_html": disk_html,
        "disk_raw": discos,
        "disk_serials": disk_serials,
        "net_html": render_filas_red([]),
        "net_raw": [],
        "net_rows": render_filas_red([]),
        "Manufacturer": "Kingston",
        "Partnumber": "PN1",
        "Battery": "90%",
    }


@pytest.fixture
def lote_con_equipos(carpeta):
    """OT de entrega activa con dos equipos guardados."""
    lote = lotes.abrir_lote(lotes.hacer_lote("Entrega", "ACME", "553", numero_sec="G-9"))
    lotes.guardar_lote_activo(lote)
    for serial in ("SN1", "SN2"):
        lotes.guardar_equipo_general(lote, datos_equipo(serial), "", False, "", "2016", [])
    return lote
