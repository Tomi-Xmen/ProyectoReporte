package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.Tipos

/** Qué se está escaneando. El primero es el modo con que se entra a un lote. */
enum class Modo(val etiqueta: String) {
    TRANSFORMADOR("Cargadores"),
    NOTEBOOK("Notebooks"),
    MONITOR("Monitores"),
    IMPRESORA("Impresoras"),
}

/**
 * Qué se escanea ahora. Los notebooks llegan al lote desde el PC (escaneo de
 * hardware); en CARGADORES el PC asigna cada cargador al siguiente notebook
 * sin cargador, en el orden en que se escanearon.
 */
data class Flujo(val modo: Modo = Modo.TRANSFORMADOR) {

    /** Tipo que se espera leer ahora. */
    val esperado: String
        get() = when (modo) {
            Modo.TRANSFORMADOR -> Tipos.TRANSFORMADOR
            Modo.NOTEBOOK -> Tipos.NOTEBOOK
            Modo.MONITOR -> Tipos.MONITOR
            Modo.IMPRESORA -> Tipos.IMPRESORA
        }

    fun indicacion(lote: EstadoLote?): String = when (modo) {
        Modo.TRANSFORMADOR -> proximoSinCargador(lote)
            ?.let { "Escaneá el cargador de $it" }
            ?: "Todos los notebooks tienen cargador"
        else -> "Escaneá el serial del ${esperado.lowercase()}"
    }

    fun conModo(m: Modo) = Flujo(m)
}

/** El notebook al que el PC le dará el próximo cargador (misma regla que asignar_transformador). */
fun proximoSinCargador(lote: EstadoLote?): String? =
    lote?.equipos?.firstOrNull { it.tipo == Tipos.NOTEBOOK && it.snTransf == null }?.serial
