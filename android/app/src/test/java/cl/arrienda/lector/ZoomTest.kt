package cl.arrienda.lector

import cl.arrienda.lector.escaneo.Zoom
import org.junit.Assert.assertEquals
import org.junit.Test

class ZoomTest {
    @Test
    fun `los extremos van de 1x al tope`() {
        assertEquals(1f, Zoom.aAumento(0f, 1f, 10f), 1e-4f)
        assertEquals(Zoom.TOPE, Zoom.aAumento(1f, 1f, 10f), 1e-4f)
    }

    @Test
    fun `escala logaritmica - la mitad del deslizador es la raiz del tope`() {
        assertEquals(2f, Zoom.aAumento(0.5f, 1f, 4f), 1e-4f)
    }

    @Test
    fun `no usa el ultra gran angular ni pasa del maximo de la camara`() {
        assertEquals(1f, Zoom.aAumento(0f, 0.6f, 5f), 1e-4f)
        assertEquals(5f, Zoom.aAumento(1f, 0.6f, 5f), 1e-4f)
    }

    @Test
    fun `ida y vuelta da lo mismo`() {
        val f = Zoom.aFraccion(Zoom.aAumento(0.37f, 1f, 8f), 1f, 8f)
        assertEquals(0.37f, f, 1e-4f)
    }

    @Test
    fun `fuera de rango se limita`() {
        assertEquals(0f, Zoom.aFraccion(0.5f, 1f, 8f), 0f)
        assertEquals(1f, Zoom.aFraccion(50f, 1f, 8f), 0f)
    }

    @Test
    fun `camara sin zoom queda en cero`() {
        assertEquals(0f, Zoom.aFraccion(1f, 1f, 1f), 0f)
        assertEquals(1f, Zoom.aAumento(0.8f, 1f, 1f), 1e-4f)
    }
}
