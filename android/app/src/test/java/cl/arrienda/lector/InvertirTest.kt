package cl.arrienda.lector

import cl.arrienda.lector.escaneo.luminanciaInvertidaNv21
import java.nio.ByteBuffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertSame
import org.junit.Test

class InvertirTest {
    private fun b(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }

    @Test
    fun `invierte la luminancia y deja el color en gris`() {
        // 2×2 con filas de 3 bytes (relleno al final de cada fila).
        val plano = ByteBuffer.wrap(b(0, 255, 9, 100, 200, 9))
        val nv21 = luminanciaInvertidaNv21(plano, 2, 2, pasoFila = 3, pasoPixel = 1)
        assertArrayEquals(b(255, 0, 155, 55, 128, 128), nv21)
    }

    @Test
    fun `respeta el paso entre pixeles`() {
        val plano = ByteBuffer.wrap(b(10, 0, 20, 0, 30, 0, 40, 0))
        val nv21 = luminanciaInvertidaNv21(plano, 2, 2, pasoFila = 4, pasoPixel = 2)
        assertArrayEquals(b(245, 235, 225, 215, 128, 128), nv21)
    }

    @Test
    fun `reusa el destino si tiene el tamano justo`() {
        val destino = ByteArray(6)
        val nv21 = luminanciaInvertidaNv21(ByteBuffer.wrap(b(1, 2, 3, 4)), 2, 2, 2, 1, destino)
        assertSame(destino, nv21)
    }
}
