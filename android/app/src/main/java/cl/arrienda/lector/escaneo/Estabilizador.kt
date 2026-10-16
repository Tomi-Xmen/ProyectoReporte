package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.Lectura

/**
 * Decide CUÁNDO una etiqueta está leída. La cámara entrega 10-30 cuadros por
 * segundo y un código a medio enfocar puede leerse mal en uno: se espera a
 * verlo en varios cuadros seguidos antes de mandarlo.
 *
 * Junta todos los códigos vistos mientras tanto (una etiqueta trae S/N, P/N,
 * EAN…): el PC elige cuál es el serial. Un código ya mandado se ignora
 * mientras siga a la vista y hasta [enfriamientoMs] después de que salga
 * del cuadro: dejar el celular apuntando no registra el mismo equipo 30 veces.
 *
 * Sin Android adentro: se prueba con tiempos inventados.
 */
class Estabilizador(
    private val cuadrosNecesarios: Int = 3,
    private val enfriamientoMs: Long = 2_500,
) {
    private val vistas = LinkedHashMap<String, Lectura>()
    private val conteo = HashMap<String, Int>()
    private val ignorarHasta = HashMap<String, Long>()

    /** Las lecturas de la etiqueta cuando quedó firme; null mientras tanto. */
    @Synchronized
    fun alimentar(cuadro: List<Lectura>, ahoraMs: Long): List<Lectura>? {
        ignorarHasta.entries.removeAll { it.value <= ahoraMs }

        val nuevas = ArrayList<Lectura>()
        for (l in cuadro.distinctBy { it.texto }) {
            if (l.texto.isBlank()) continue
            if (l.texto in ignorarHasta) {
                ignorarHasta[l.texto] = ahoraMs + enfriamientoMs // sigue a la vista
            } else {
                nuevas += l
            }
        }

        // Un cuadro sin nada nuevo corta la racha: el celular se movió.
        if (nuevas.isEmpty()) {
            vistas.clear()
            conteo.clear()
            return null
        }
        for (l in nuevas) {
            vistas[l.texto] = l
            conteo[l.texto] = (conteo[l.texto] ?: 0) + 1
        }
        if (conteo.values.none { it >= cuadrosNecesarios }) return null

        val etiqueta = vistas.values.toList()
        etiqueta.forEach { ignorarHasta[it.texto] = ahoraMs + enfriamientoMs }
        vistas.clear()
        conteo.clear()
        return etiqueta
    }

    /** Para releer a propósito lo que está enfrente (botón "leer de nuevo"). */
    @Synchronized
    fun olvidar() {
        vistas.clear()
        conteo.clear()
        ignorarHasta.clear()
    }
}
