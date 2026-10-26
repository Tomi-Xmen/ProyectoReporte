package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.ParCargador
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
 * hardware); en CARGADORES cada cargador leído se empareja con el siguiente
 * notebook sin cargador, en el orden en que se escanearon, y queda en una
 * lista en el celular hasta tocar Guardar.
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

    fun indicacion(lote: EstadoLote?, borrador: List<ParCargador> = emptyList()): String = when (modo) {
        Modo.TRANSFORMADOR -> proximoSinCargador(lote, borrador)
            ?.let { "Escaneá el cargador de $it" }
            ?: "Todos los notebooks tienen cargador"
        else -> "Escaneá el serial del ${esperado.lowercase()}"
    }

    fun conModo(m: Modo) = Flujo(m)
}

/**
 * El notebook al que va el próximo cargador: el primero sin cargador en orden
 * de escaneo (la regla de asignar_transformador) que no esté ya en la lista.
 */
fun proximoSinCargador(lote: EstadoLote?, borrador: List<ParCargador> = emptyList()): String? {
    val enLista = borrador.map { it.serial }.toSet()
    return lote?.equipos
        ?.firstOrNull { it.tipo == Tipos.NOTEBOOK && it.snTransf == null && it.serial !in enLista }
        ?.serial
}
