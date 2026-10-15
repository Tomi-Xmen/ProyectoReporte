"""
Acciones del menú principal que no tienen ventana propia: pasan por diálogos
y avisos, llaman al núcleo y dejan que el menú se refresque.

Cada función recibe la ventana padre y devuelve True si cambió algo que el
menú tenga que volver a mostrar (OT activa, cantidad de equipos, etc.).
"""

import os
import subprocess

from PySide6.QtWidgets import QFileDialog

from ..nucleo import config, escaner, lotes, reconstruccion, remoto
from ..nucleo.lotes import MOV_CFG, etiqueta_lote
from . import avisos
from .dialogos import elegir_lote, nuevo_lote
from .tareas import con_espera


def nueva_ot(ventana):
    lote = nuevo_lote(ventana)
    if not lote:
        return False
    lotes.guardar_lote_activo(lote)
    return True


def cambiar_ot(ventana):
    lote = elegir_lote(ventana, "Cambiar de OT", "✅ Activar")
    if not lote:
        return False
    lotes.guardar_lote_activo(lote)
    return True


def cerrar_ot(ventana):
    lote = elegir_lote(ventana, "Cerrar OT", "📦 Cerrar esta OT")
    if not lote:
        return False

    if lote["equipos"] == 0 and not avisos.confirmar(
        ventana, "OT vacía", f"{etiqueta_lote(lote)} no tiene equipos.\n\n¿Cerrarla igual?"
    ):
        return False

    if not avisos.confirmar(
        ventana,
        "Confirmar cierre",
        f"¿Cerrar {etiqueta_lote(lote)}?\n\n"
        f"{lote['equipos']} equipo(s). Se regenera el JSON FUSIONADO con todo "
        "lo escaneado y la carpeta queda marcada como finalizada.",
    ):
        return False

    def cerrar():
        total, malos = lotes.cerrar_lote(lote)
        return total, malos, lotes.crear_backup("cierre")

    total, equipos_malos, ruta_bk = con_espera(
        ventana, "Cerrando OT", "Cerrando la OT y generando el backup…", cerrar
    )

    extra = ""
    if equipos_malos:
        extra = f"\n\n⚠️ {len(equipos_malos)} equipo(s) quedaron con fallas registradas."
    if ruta_bk:
        extra += f"\n\n🗄️ Backup: {os.path.basename(ruta_bk)}"
    avisos.info(
        ventana,
        "📦 OT cerrada",
        f"{etiqueta_lote(lote)}\n\n"
        f"{total} equipo(s) en el JSON FUSIONADO.\n"
        f"Carpeta: {lote['ruta']}{extra}",
    )
    return True


def migrar_legacy(ventana):
    """Adopta los equipos sueltos del modelo anterior dentro de una OT."""
    legacy = lotes.pendientes_legacy()
    if not sum(len(v) for v in legacy.values()):
        return False

    for mov, rutas in legacy.items():
        if not rutas:
            continue
        avisos.info(
            ventana,
            "Migrar equipos sueltos",
            f"Hay {len(rutas)} equipo(s) de {MOV_CFG[mov]['tipo_doc'].upper()} "
            "escaneados con el formato anterior.\n\nElegí a qué OT pertenecen.",
        )
        lote = nuevo_lote(ventana, mov_sugerido=mov)
        if not lote:
            continue
        if lote["mov"] != mov:
            avisos.aviso(
                ventana,
                "Movimiento distinto",
                f"Esos equipos son de {mov} y la OT elegida es de "
                f"{lote['mov']}.\n\nSe migran igual con el movimiento de la OT.",
            )
        migrados = lotes.migrar_legacy_a_lote(rutas, lote)
        avisos.info(
            ventana, "✅ Migrados", f"{migrados} equipo(s) quedaron en {etiqueta_lote(lote)}."
        )
        lotes.guardar_lote_activo(lote)
    return True


def enviar_al_servidor(ventana):
    if not os.path.exists(lotes.ruta_reportes()):
        avisos.aviso(ventana, "Aviso", "No hay reportes locales para enviar.")
        return False

    if not config.SCP_AVAILABLE:
        avisos.error(
            ventana,
            "Falta dependencia",
            "El envío por SCP necesita las librerías 'paramiko' y 'scp'.\n\n"
            "Instalalas con:  pip install paramiko scp\n"
            "y volvé a compilar el ejecutable.",
        )
        return False

    pendientes, hay_carpetas = lotes.pendientes_envio()
    if not pendientes:
        if hay_carpetas:
            avisos.info(
                ventana,
                "Nada nuevo por enviar",
                "Todas las OT ya fueron enviadas al servidor.",
            )
        else:
            avisos.aviso(
                ventana,
                "Aviso",
                "No hay ninguna OT para enviar.\n\nEscaneá equipos primero.",
            )
        return False

    total_archivos = sum(len(remoto.archivos_a_enviar(p[3])) for p in pendientes)
    abiertas = sum(1 for p in pendientes if p[4])
    aviso_abiertas = ""
    if abiertas:
        aviso_abiertas = (
            f"\n\n⚠️ {abiertas} de ellas siguen ABIERTAS: se enviarán tal como "
            "van y se volverán a enviar cuando les agregues equipos."
        )

    if not avisos.confirmar(
        ventana,
        "Confirmar envío",
        f"¿Enviar {len(pendientes)} carpeta(s) de OT al servidor por SCP?\n\n"
        f"Destino: {config.SCP_USUARIO}@{config.SCP_HOST}:{config.SCP_DESTINO}\n"
        f"Archivos: {total_archivos} (JSON individuales, FUSIONADO y marcadores).\n\n"
        f"El HTML no se sube: se reconstruye desde los JSON en destino."
        f"{aviso_abiertas}",
    ):
        return False

    try:
        enviados, subidos, errores, ruta_bk = con_espera(
            ventana,
            "Enviando…",
            f"🚀 Subiendo por SCP a {config.SCP_HOST}",
            remoto.enviar_pendientes,
            pendientes,
            detalle="Conectando… Por favor, no cierres el programa.",
            con_progreso=True,
        )
    except remoto.ErrorEnvio as e:
        aviso_bk = (
            f"\n\n🗄️ Backup previo: {os.path.basename(e.ruta_backup)}"
            if e.ruta_backup
            else ""
        )
        avisos.error(ventana, "Error de conexión", f"{e}{aviso_bk}")
        return True

    aviso_bk = f"\n\n🗄️ Backup previo: {os.path.basename(ruta_bk)}" if ruta_bk else ""
    if errores:
        avisos.aviso(
            ventana,
            "Proceso con observaciones",
            f"Se enviaron {enviados} carpeta(s) ({subidos} archivo(s)), "
            f"pero {len(errores)} fallaron:\n\n"
            + "\n".join(f"  • {e}" for e in errores[:8])
            + aviso_bk,
            detalle="\n".join(errores),
        )
    else:
        avisos.info(
            ventana,
            "✅ Envío exitoso",
            f"Se enviaron {enviados} carpeta(s) de OT ({subidos} archivo(s)) "
            f"a {config.SCP_HOST} correctamente.{aviso_bk}",
        )
    return True


def reconstruir_desde_json(ventana):
    """
    Rearma los HTML desde los JSON guardados. Se puede apuntar a una OT, a un
    cliente (con todas sus OT) o a ENTREGA/ completo.
    """
    carpeta = QFileDialog.getExistingDirectory(
        ventana,
        "Seleccioná la carpeta a reconstruir (OT, cliente o grupo)",
        lotes.ruta_reportes(),
    )
    if not carpeta:
        return False

    carpetas = reconstruccion.carpetas_a_reconstruir(carpeta)
    if not carpetas:
        avisos.aviso(
            ventana,
            "Sin JSONs",
            f"No se encontraron JSON de equipos en:\n{carpeta}\n\n"
            "(Se busca también dentro de las subcarpetas.)",
        )
        return False

    if len(carpetas) > 1 and not avisos.confirmar(
        ventana,
        "Reconstrucción múltiple",
        f"Se encontraron {len(carpetas)} carpetas con equipos dentro de:\n"
        f"{carpeta}\n\n¿Reconstruir todas?",
    ):
        return False

    total, regenerados, sueltos, errores = con_espera(
        ventana,
        "Reconstruyendo",
        f"🔧 Reconstruyendo {len(carpetas)} carpeta(s)…",
        reconstruccion.reconstruir_carpetas,
        carpetas,
    )

    if not total and not regenerados:
        msg = "No se pudo leer ningún JSON válido."
        if errores:
            msg += "\n\nErrores:\n" + "\n".join(errores[:15])
        avisos.error(ventana, "Error", msg, detalle="\n".join(errores) or None)
        return False

    resumen = f"✅ Reconstrucción completa: {total} equipo(s)."
    if regenerados:
        resumen += (
            f"\n\n📁 OT regeneradas ({len(regenerados)}) — HTML + JSON FUSIONADO:\n"
            + "\n".join(f"  • {r}" for r in regenerados[:12])
        )
        if len(regenerados) > 12:
            resumen += f"\n  … y {len(regenerados) - 12} más"
    if sueltos:
        resumen += f"\n\n📄 Carpetas sueltas ({len(sueltos)}):\n" + "\n".join(
            f"  • {a}" for a in sueltos[:12]
        )
    if errores:
        resumen += f"\n\n⚠️ Advertencias ({len(errores)}):\n" + "\n".join(errores[:10])
    avisos.info(
        ventana,
        "🔧 Reconstrucción completa",
        resumen,
        detalle="\n".join(regenerados + sueltos + errores) or None,
    )
    return True


def cambiar_nombre_equipo(ventana):
    try:
        serial = con_espera(
            ventana, "Leyendo BIOS", "Leyendo el número de serie…", escaner.leer_serial_bios
        )
    except Exception as e:
        avisos.error(
            ventana, "Error", f"No se pudo obtener el número de serie de la BIOS.\n{e}"
        )
        return False

    if not serial:
        avisos.aviso(
            ventana,
            "Aviso",
            "No se detectó un número de serie válido en la BIOS de este equipo.",
        )
        return False

    nuevo_nombre = escaner.nombre_equipo_para(serial)
    if not avisos.confirmar(
        ventana,
        "Confirmar cambio de nombre",
        f"El número de serie detectado es: {serial}\n\n"
        f"¿Seguro que querés cambiar el nombre de este equipo a:\n\n{nuevo_nombre}?\n\n"
        "(Tenés que aceptar la ventana de permisos de Administrador que aparece "
        "a continuación).",
    ):
        return False

    try:
        escaner.cambiar_nombre_equipo(nuevo_nombre)
    except subprocess.CalledProcessError:
        avisos.error(
            ventana,
            "Error",
            "No se pudo cambiar el nombre del equipo.\n\n"
            "Asegurate de aceptar la ventana de permisos de Administrador.",
        )
        return False
    except Exception as e:
        avisos.error(
            ventana,
            "Error inesperado",
            f"Ocurrió un error al intentar cambiar el nombre: {e}",
        )
        return False

    avisos.info(
        ventana,
        "✅ Solicitud enviada",
        f"Se ordenó el cambio de nombre a '{nuevo_nombre}'.\n\n"
        "REINICIÁ EL EQUIPO para que el cambio surta efecto.",
    )
    return False
