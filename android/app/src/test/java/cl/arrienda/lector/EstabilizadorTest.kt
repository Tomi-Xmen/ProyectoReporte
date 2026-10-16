package cl.arrienda.lector

import cl.arrienda.lector.data.Lectura
import cl.arrienda.lector.escaneo.Estabilizador
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class EstabilizadorTest {
    private val sn = Lectura("5CD805DVNV", "CODE_128")
    private val ean = Lectura("7801234567890", "EAN_13")

    @Test
    fun `espera varios cuadros seguidos antes de leer`() {
        val e = Estabilizador(cuadrosNecesarios = 3)
        assertNull(e.alimentar(listOf(sn), 0))
        assertNull(e.alimentar(listOf(sn), 33))
        assertEquals(listOf(sn), e.alimentar(listOf(sn), 66))
    }

    @Test
    fun `un cuadro vacio corta la racha`() {
        val e = Estabilizador(cuadrosNecesarios = 3)
        e.alimentar(listOf(sn), 0)
        e.alimentar(listOf(sn), 33)
        assertNull(e.alimentar(emptyList(), 66))
        assertNull(e.alimentar(listOf(sn), 99))
    }

    @Test
    fun `junta todos los codigos de la etiqueta`() {
        val e = Estabilizador(cuadrosNecesarios = 2)
        assertNull(e.alimentar(listOf(ean), 0))
        val etiqueta = e.alimentar(listOf(sn, ean), 33)
        assertEquals(setOf(sn, ean), etiqueta!!.toSet())
    }

    @Test
    fun `no relee lo que sigue a la vista`() {
        val e = Estabilizador(cuadrosNecesarios = 2, enfriamientoMs = 1000)
        e.alimentar(listOf(sn), 0)
        assertNotNull(e.alimentar(listOf(sn), 10))
        // Diez segundos apuntando a la misma etiqueta: nunca se vuelve a mandar.
        var t = 20L
        while (t < 10_000) {
            assertNull(e.alimentar(listOf(sn), t))
            t += 33
        }
        // Sale del cuadro más que el enfriamiento y vuelve: se lee otra vez.
        e.alimentar(emptyList(), t)
        e.alimentar(listOf(sn), t + 1500)
        assertNotNull(e.alimentar(listOf(sn), t + 1533))
    }

    @Test
    fun `olvidar permite releer en el acto`() {
        val e = Estabilizador(cuadrosNecesarios = 1)
        assertNotNull(e.alimentar(listOf(sn), 0))
        assertNull(e.alimentar(listOf(sn), 10))
        e.olvidar()
        assertNotNull(e.alimentar(listOf(sn), 20))
    }
}
