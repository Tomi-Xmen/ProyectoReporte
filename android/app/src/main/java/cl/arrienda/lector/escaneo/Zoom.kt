package cl.arrienda.lector.escaneo

import kotlin.math.ln
import kotlin.math.pow

/**
 * Zoom como fracción 0..1 en escala logarítmica: cada tramo del deslizador
 * multiplica el aumento por lo mismo (1×→2× se siente igual que 2×→4×), y un
 * pellizco que duplica el aumento avanza siempre lo mismo.
 *
 * Arranca en 1×: el ultra gran angular (aumentos < 1) lee peor de cerca. Se
 * corta en [TOPE]: más allá el zoom digital ya no agrega detalle que sirva.
 *
 * Sin Android adentro: se prueba en la JVM.
 */
object Zoom {
    const val TOPE = 8f

    private fun rango(min: Float, max: Float): Pair<Float, Float> {
        val bajo = maxOf(min, 1f)
        return bajo to minOf(max, TOPE).coerceAtLeast(bajo)
    }

    fun aAumento(fraccion: Float, min: Float, max: Float): Float {
        val (bajo, alto) = rango(min, max)
        return bajo * (alto / bajo).pow(fraccion.coerceIn(0f, 1f))
    }

    fun aFraccion(aumento: Float, min: Float, max: Float): Float {
        val (bajo, alto) = rango(min, max)
        if (alto <= bajo || aumento <= bajo) return 0f
        return (ln(aumento / bajo) / ln(alto / bajo)).coerceIn(0f, 1f)
    }
}
