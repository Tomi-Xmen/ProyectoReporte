package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Tipos

/** Qué se está escaneando. */
enum class Modo(val etiqueta: String) {
    GUIADO("Notebook + cargador"),
    NOTEBOOK("Notebooks"),
    MONITOR("Monitores"),
    IMPRESORA("Impresoras"),
    TRANSFORMADOR("Cargadores en ráfaga"),
}

/**
 * Estado del escaneo guiado: en GUIADO se alterna notebook → su cargador →
 * notebook… Los demás modos escanean siempre lo mismo. En TRANSFORMADOR
 * (ráfaga) el PC asigna cada cargador al siguiente notebook sin cargador, en
 * el orden en que se escanearon.
 */
data class Flujo(val modo: Modo = Modo.GUIADO, val equipoGuiado: String? = null) {

    /** Tipo que se espera leer ahora. */
    val esperado: String
        get() = when (modo) {
            Modo.GUIADO -> if (equipoGuiado != null) Tipos.TRANSFORMADOR else Tipos.NOTEBOOK
            Modo.NOTEBOOK -> Tipos.NOTEBOOK
            Modo.MONITOR -> Tipos.MONITOR
            Modo.IMPRESORA -> Tipos.IMPRESORA
            Modo.TRANSFORMADOR -> Tipos.TRANSFORMADOR
        }

    /** A qué equipo va el cargador (solo en guiado, después de leer el notebook). */
    val serialEquipo: String? get() = if (modo == Modo.GUIADO) equipoGuiado else null

    val indicacion: String
        get() = when {
            modo == Modo.GUIADO && equipoGuiado != null -> "Escaneá el cargador de $equipoGuiado"
            modo == Modo.GUIADO -> "Escaneá el serial del notebook"
            modo == Modo.TRANSFORMADOR -> "Escaneá los cargadores en el orden de los equipos"
            else -> "Escaneá el serial del ${esperado.lowercase()}"
        }

    fun trasRespuesta(r: RespuestaEscaneo): Flujo = when {
        modo != Modo.GUIADO -> this
        equipoGuiado == null && r.estado in EQUIPO_LISTO && r.serial != null && r.tipo == Tipos.NOTEBOOK ->
            copy(equipoGuiado = r.serial)
        equipoGuiado != null && r.estado in CARGADOR_LISTO -> copy(equipoGuiado = null)
        else -> this
    }

    /** El notebook no tiene cargador (o llega después): seguir con el próximo equipo. */
    fun saltarCargador() = copy(equipoGuiado = null)

    fun conModo(m: Modo) = Flujo(m)

    private companion object {
        val EQUIPO_LISTO = setOf("registrado", "ya_estaba")
        val CARGADOR_LISTO = setOf("asignado", "ya_estaba")
    }
}
