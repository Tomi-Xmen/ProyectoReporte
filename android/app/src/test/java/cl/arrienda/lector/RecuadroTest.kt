package cl.arrienda.lector

import cl.arrienda.lector.escaneo.Caja
import cl.arrienda.lector.escaneo.Recuadro
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecuadroTest {
    // Sensor 1280×960 acostado (rotación 90): enderezada queda 960×1280.
    private fun caja(cx: Float, cy: Float) = Caja(cx - 10, cy - 10, cx + 10, cy + 10)

    @Test
    fun `el recuadro queda centrado y proporcional a la vista`() {
        val c = Recuadro.enVista(400f, 300f, 0.5f)
        assertEquals(Caja(100f, 75f, 300f, 225f), c)
    }

    @Test
    fun `la fraccion se limita al rango permitido`() {
        assertEquals(Caja(0f, 0f, 400f, 300f), Recuadro.enVista(400f, 300f, 3f))
        assertEquals(Recuadro.enVista(400f, 300f, Recuadro.MINIMO), Recuadro.enVista(400f, 300f, 0f))
    }

    @Test
    fun `sin rotacion y misma proporcion el centro de la imagen esta adentro y la esquina afuera`() {
        assertTrue(Recuadro.contiene(caja(640f, 480f), 1280, 960, 0, 400f, 300f, 0.3f))
        assertFalse(Recuadro.contiene(caja(50f, 50f), 1280, 960, 0, 400f, 300f, 0.3f))
    }

    @Test
    fun `con rotacion 90 usa la imagen enderezada`() {
        // Vista vertical 300×400; imagen enderezada 960×1280, mismo 3:4.
        assertTrue(Recuadro.contiene(caja(480f, 640f), 1280, 960, 90, 300f, 400f, 0.3f))
        // Arriba de todo en la imagen enderezada: afuera del recuadro.
        assertFalse(Recuadro.contiene(caja(480f, 40f), 1280, 960, 90, 300f, 400f, 0.3f))
    }

    @Test
    fun `fill center recorta los costados que sobran`() {
        // Imagen 4:3 en una vista cuadrada 300×300: escala 300/960, sobran
        // 50 px por lado. x=160 de la imagen cae en x=0 de la vista.
        assertTrue(Recuadro.contiene(caja(160f, 480f), 1280, 960, 0, 300f, 300f, 1f))
        assertFalse(Recuadro.contiene(caja(100f, 480f), 1280, 960, 0, 300f, 300f, 1f))
    }

    @Test
    fun `al maximo cuenta todo lo visible`() {
        assertTrue(Recuadro.contiene(caja(15f, 15f), 1280, 960, 0, 400f, 300f, Recuadro.MAXIMO))
    }

    @Test
    fun `sin medidas de la vista no filtra`() {
        assertTrue(Recuadro.contiene(caja(0f, 0f), 1280, 960, 0, 0f, 0f, 0.3f))
    }
}
