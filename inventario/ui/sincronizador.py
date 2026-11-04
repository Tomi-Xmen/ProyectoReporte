"""
Traer automático de la OT publicada para clonación, para toda la app.

Antes vivía en el panel de clonación: con el panel cerrado, lo que mandaban
los equipos clonados no llegaba a esta PC (ni al menú, ni al reporte en vivo,
ni a "Asignar Office") hasta que alguien lo abría. Ahora lo corre la ventana
principal mientras el programa está abierto, y el panel solo lo muestra.

Cada vuelta consulta el servidor en un hilo de trabajo y escribe en el de la
interfaz (sincronizacion.aplicar), igual que el servidor del celular: así los
dos nunca escriben a la vez. Con una OT publicada vuelve cada 15 s; sin OT, o
si el servidor no responde, cada minuto, para no consultar la red todo el día
por nada.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ..nucleo import config, remoto, sincronizacion
from ..nucleo.lotes import anotar_publicada, esta_cerrado, etiqueta_lote
from .tareas import en_segundo_plano

INTERVALO_PUBLICADA_MS = 15_000
INTERVALO_ESPERA_MS = 60_000


def _primera_linea(exc):
    texto = str(exc).strip()
    return texto.splitlines()[0] if texto else type(exc).__name__


class Sincronizador(QObject):
    """
    Una sola instancia, de la ventana principal. 'estado' es lo último que se
    supo del servidor; 'cambio' avisa cada vez que se actualiza.
    """

    cambio = Signal()

    def __init__(self, padre=None):
        super().__init__(padre)
        self.pausado = False
        self.estado = {
            "lote": None,        # OT publicada en el servidor, o None
            "huellas": {},       # sus JSON en el servidor
            "esperados": [],
            "hora": "",          # hora de la última vuelta que contestó
            "escritos": 0,       # equipos nuevos o cambiados en esa vuelta
            "error": "",         # por qué falló la última vuelta, si falló
            "cerrada_aca": False,
        }
        self._trayendo = False
        self._fin = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.traer_ahora)

    @staticmethod
    def disponible():
        return config.SERVIDOR_CONFIGURADO and config.SCP_AVAILABLE

    def arrancar(self):
        self.traer_ahora()

    def detener(self):
        """Al salir: una vuelta que todavía corre no escribe nada al terminar."""
        self._fin = True
        self._timer.stop()

    def pausar(self, pausado):
        self.pausado = pausado
        if pausado:
            self._timer.stop()
        else:
            self.traer_ahora()
        self.cambio.emit()

    def traer_ahora(self):
        """Una vuelta en segundo plano, si no hay otra corriendo."""
        if self._trayendo or self._fin or self.pausado or not self.disponible():
            return
        self._trayendo = True
        self._timer.stop()
        en_segundo_plano(
            remoto.con_conexion,
            sincronizacion.consultar,
            al_terminar=self._al_traer,
            al_fallar=self._al_fallar,
        )

    def aplicar(self, res):
        """
        Escribe lo que trajo sincronizacion.consultar() (None: no hay OT
        publicada) y actualiza el estado. También lo usa "Traer y
        reconstruir" del panel. Devuelve los equipos escritos.
        """
        if res is None:
            anotar_publicada(None)
            self.estado.update(lote=None, huellas={}, esperados=[], escritos=0, cerrada_aca=False)
        else:
            local = sincronizacion.lote_local(res["lote"])
            anotar_publicada(local)
            cerrada = esta_cerrado(local["ruta"])
            escritos = 0
            if not cerrada:
                escritos = sincronizacion.aplicar(res["lote"], res["huellas"], res["contenidos"])
            self.estado.update(
                lote=res["lote"],
                huellas=res["huellas"],
                esperados=res["esperados"],
                hora=res["hora"],
                escritos=escritos,
                cerrada_aca=cerrada,
            )
        self.estado["error"] = ""
        return self.estado["escritos"]

    def _al_traer(self, res):
        self._trayendo = False
        if self._fin:
            return
        self.aplicar(res)
        self._programar()
        self.cambio.emit()

    def _al_fallar(self, exc):
        self._trayendo = False
        if self._fin:
            return
        self.estado["error"] = _primera_linea(exc)
        self._programar()
        self.cambio.emit()

    def _programar(self):
        if self.pausado or self._fin:
            return
        rapido = self.estado["lote"] is not None and not self.estado["error"]
        self._timer.start(INTERVALO_PUBLICADA_MS if rapido else INTERVALO_ESPERA_MS)

    # ── Para mostrar ──────────────────────────────────────
    def equipos_recibidos(self):
        """Los equipos de la OT publicada que ya están en esta PC."""
        if self.estado["lote"] is None:
            return []
        return sincronizacion.equipos_locales(self.estado["lote"], self.estado["huellas"])

    def resumen(self):
        """
        Una línea para el menú, o '' si no hay nada que decir (sin servidor
        configurado o sin OT publicada).
        """
        if not self.disponible():
            return ""
        e = self.estado
        if self.pausado:
            return "📡 Clonación: traer automático en pausa"
        if e["error"]:
            return f"⚠️ Clonación: sin conexión con el servidor, se reintenta ({e['error']})"
        if e["lote"] is None:
            return ""
        recibidos = len(e["huellas"])
        partes = [f"📡 Clonación: {etiqueta_lote(e['lote'])} · {recibidos} recibido(s)"]
        seriales = {str(j.get("SERIAL", "")).upper() for j in self.equipos_recibidos()}
        faltan = [s for s in e["esperados"] if s.upper() not in seriales]
        if faltan:
            partes.append(f"faltan {len(faltan)}")
        if e["cerrada_aca"]:
            partes.append("⚠️ cerrada en esta PC")
        partes.append(f"última vuelta {e['hora']}")
        return " · ".join(partes)
