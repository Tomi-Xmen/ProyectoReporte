package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Tipos

/** Qué se está escaneando. */
enum class Modo(val etiqueta: String) {
    GUIADO("Notebook + cargador"),
    CARGADOR_ELEGIR("Cargador → elegir equipo"),
    NOTEBOOK("Notebooks"),
    MONITOR("Monitores"),
    IMPRESORA("Impresoras"),
    TRANSFORMADOR("Cargadores en ráfaga"),
}

/**
 * Estado del escaneo guiado: en GUIADO se alterna notebook → su cargador →
 * notebook… Los demás modos escanean siempre lo mismo. En TRANSFORMADOR
 * (ráfaga) el PC asigna cada cargador al siguiente notebook sin cargador, en
 * el orden en que se escanearon. En CARGADOR_ELEGIR el PC solo dice qué
 * cargador se leyó y la app pregunta a qué equipo va.
 *
 * [cargadorPara] es un paso suelto que se pide desde la ficha de un equipo
 * ("escanear su cargador"): manda sobre el modo para UNA lectura y, al quedar
 * asignado, se vuelve al modo en que se estaba.
 */
data class Flujo(
    val modo: Modo = Modo.GUIADO,
    val equipoGuiado: String? = null,
    val cargadorPara: String? = null,
) {

    /** Tipo que se espera leer ahora. */
    val esperado: String
        get() = if (cargadorPara != null) Tipos.TRANSFORMADOR else when (modo) {
            Modo.GUIADO -> if (equipoGuiado != null) Tipos.TRANSFORMADOR else Tipos.NOTEBOOK
            Modo.CARGADOR_ELEGIR -> Tipos.TRANSFORMADOR
            Modo.NOTEBOOK -> Tipos.NOTEBOOK
            Modo.MONITOR -> Tipos.MONITOR
            Modo.IMPRESORA -> Tipos.IMPRESORA
            Modo.TRANSFORMADOR -> Tipos.TRANSFORMADOR
        }

    /** A qué equipo va el cargador (solo en guiado, después de leer el notebook). */
    val serialEquipo: String? get() = if (cargadorPara == null && modo == Modo.GUIADO) equipoGuiado else null

    /** El PC no asigna: dice qué cargador se leyó y la app decide a qué equipo va. */
    val soloLeer: Boolean get() = cargadorPara != null || modo == Modo.CARGADOR_ELEGIR

    val indicacion: String
        get() = when {
            cargadorPara != null -> "Escaneá el cargador para $cargadorPara"
            modo == Modo.GUIADO && equipoGuiado != null -> "Escaneá el cargador de $equipoGuiado"
            modo == Modo.GUIADO -> "Escaneá el serial del notebook"
            modo == Modo.CARGADOR_ELEGIR -> "Escaneá un cargador: después elegís a qué equipo va"
            modo == Modo.TRANSFORMADOR -> "Escaneá los cargadores en el orden de los equipos"
            else -> "Escaneá el serial del ${esperado.lowercase()}"
        }

    fun trasRespuesta(r: RespuestaEscaneo): Flujo = when {
        cargadorPara != null -> if (r.estado in CARGADOR_LISTO) copy(cargadorPara = null) else this
        modo != Modo.GUIADO -> this
        equipoGuiado == null && r.estado in EQUIPO_LISTO && r.serial != null && r.tipo == Tipos.NOTEBOOK ->
            copy(equipoGuiado = r.serial)
        equipoGuiado != null && r.estado in CARGADOR_LISTO -> copy(equipoGuiado = null)
        else -> this
    }

    /** El notebook no tiene cargador (o llega después): seguir con el próximo equipo. */
    fun saltarCargador() = copy(equipoGuiado = null)

    /** Desde la ficha: la próxima lectura es el cargador de [serial]. */
    fun paraCargadorDe(serial: String) = copy(cargadorPara = serial)

    fun sinCargadorPara() = copy(cargadorPara = null)

    fun conModo(m: Modo) = Flujo(m)

    private companion object {
        val EQUIPO_LISTO = setOf("registrado", "ya_estaba")
        val CARGADOR_LISTO = setOf("asignado", "ya_estaba")
    }
}
