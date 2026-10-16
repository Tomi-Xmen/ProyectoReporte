package cl.arrienda.lector.escaneo

/**
 * Geometría del recuadro de mira. Una etiqueta de transformador trae varios
 * códigos juntos (QR, barras de P/N, EAN…): solo cuenta el que cae adentro
 * del recuadro, así se elige cuál leer apuntando.
 *
 * Sin Android adentro (android.graphics.Rect no anda en los tests JVM).
 */
data class Caja(val izq: Float, val arriba: Float, val der: Float, val abajo: Float) {
    val centroX get() = (izq + der) / 2
    val centroY get() = (arriba + abajo) / 2

    fun contiene(x: Float, y: Float) = x in izq..der && y in arriba..abajo
}

object Recuadro {
    const val MINIMO = 0.25f
    const val MAXIMO = 1f
    const val INICIAL = 0.6f

    /** Recuadro centrado, con la misma proporción que la vista y [fraccion] de su tamaño. */
    fun enVista(anchoVista: Float, altoVista: Float, fraccion: Float): Caja {
        val f = fraccion.coerceIn(MINIMO, MAXIMO)
        val mx = anchoVista * (1 - f) / 2
        val my = altoVista * (1 - f) / 2
        return Caja(mx, my, anchoVista - mx, altoVista - my)
    }

    /**
     * La caja de un código en coordenadas de la vista.
     *
     * [caja] viene de ML Kit en coordenadas de la imagen ya enderezada (con
     * [rotacion] aplicada); [anchoImg]/[altoImg] son los del sensor, sin rotar.
     * La vista muestra la imagen en FILL_CENTER: escalada hasta cubrirla y
     * recortada parejo por los lados que sobran.
     */
    fun aVista(
        caja: Caja,
        anchoImg: Int,
        altoImg: Int,
        rotacion: Int,
        anchoVista: Float,
        altoVista: Float,
    ): Caja {
        val acostada = rotacion % 180 != 0
        val w = (if (acostada) altoImg else anchoImg).toFloat()
        val h = (if (acostada) anchoImg else altoImg).toFloat()
        val escala = maxOf(anchoVista / w, altoVista / h)
        val dx = (anchoVista - w * escala) / 2
        val dy = (altoVista - h * escala) / 2
        return Caja(caja.izq * escala + dx, caja.arriba * escala + dy, caja.der * escala + dx, caja.abajo * escala + dy)
    }

    /** True si el centro del código cae adentro del recuadro (ver [aVista]). */
    fun contiene(
        caja: Caja,
        anchoImg: Int,
        altoImg: Int,
        rotacion: Int,
        anchoVista: Float,
        altoVista: Float,
        fraccion: Float,
    ): Boolean {
        if (anchoVista <= 0f || altoVista <= 0f || anchoImg <= 0 || altoImg <= 0) return true
        val v = aVista(caja, anchoImg, altoImg, rotacion, anchoVista, altoVista)
        return enVista(anchoVista, altoVista, fraccion).contiene(v.centroX, v.centroY)
    }
}
