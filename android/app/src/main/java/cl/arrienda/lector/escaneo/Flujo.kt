package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.ParCargador
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Tipos

/** Qué se está escaneando. El primero es el modo con que se entra a un lote. */
enum class Modo(val etiqueta: String) {
    TRANSFORMADOR("Cargadores"),
    CARGADOR_ELEGIR("Cargador → elegir equipo"),
    NOTEBOOK("Notebooks"),
    MONITOR("Monitores"),
    IMPRESORA("Impresoras"),
}

/**
 * Qué se escanea ahora. Los notebooks llegan al lote desde el PC (escaneo de
 * hardware); en CARGADORES cada cargador leído se empareja con el siguiente
 * notebook sin cargador, en el orden en que se escanearon, y queda en una
 * lista en el celular hasta tocar Guardar. En CARGADOR_ELEGIR el PC solo dice
 * qué cargador se leyó y la app pregunta a qué equipo va.
 *
 * [cargadorPara] es un paso suelto que se pide desde la ficha de un equipo
 * ("escanear su cargador"): manda sobre el modo para UNA lectura y, al quedar
 * asignado, se vuelve al modo en que se estaba.
 */
data class Flujo(
    val modo: Modo = Modo.TRANSFORMADOR,
    val cargadorPara: String? = null,
) {

    /** Tipo que se espera leer ahora. */
    val esperado: String
        get() = if (cargadorPara != null) Tipos.TRANSFORMADOR else when (modo) {
            Modo.TRANSFORMADOR -> Tipos.TRANSFORMADOR
            Modo.CARGADOR_ELEGIR -> Tipos.TRANSFORMADOR
            Modo.NOTEBOOK -> Tipos.NOTEBOOK
            Modo.MONITOR -> Tipos.MONITOR
            Modo.IMPRESORA -> Tipos.IMPRESORA
        }

    /** El PC no asigna: dice qué cargador se leyó y la app decide a qué equipo va. */
    val soloLeer: Boolean get() = cargadorPara != null || modo == Modo.CARGADOR_ELEGIR

    /** El cargador va a la lista del celular (se guarda con el botón), no directo al PC. */
    val aLaLista: Boolean get() = cargadorPara == null && modo == Modo.TRANSFORMADOR

    fun indicacion(lote: EstadoLote?, borrador: List<ParCargador> = emptyList()): String = when {
        cargadorPara != null -> "Escaneá el cargador para $cargadorPara"
        modo == Modo.TRANSFORMADOR -> proximoSinCargador(lote, borrador)
            ?.let { "Escaneá el cargador de $it" }
            ?: "Todos los notebooks tienen cargador"
        modo == Modo.CARGADOR_ELEGIR -> "Escaneá un cargador: después elegís a qué equipo va"
        else -> "Escaneá el serial del ${esperado.lowercase()}"
    }

    fun trasRespuesta(r: RespuestaEscaneo): Flujo =
        if (cargadorPara != null && r.estado in CARGADOR_LISTO) copy(cargadorPara = null) else this

    /** Desde la ficha: la próxima lectura es el cargador de [serial]. */
    fun paraCargadorDe(serial: String) = copy(cargadorPara = serial)

    fun sinCargadorPara() = copy(cargadorPara = null)

    fun conModo(m: Modo) = Flujo(m)

    private companion object {
        val CARGADOR_LISTO = setOf("asignado", "ya_estaba")
    }
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
