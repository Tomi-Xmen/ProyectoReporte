package cl.arrienda.lector

import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Tipos
import cl.arrienda.lector.escaneo.Flujo
import cl.arrienda.lector.escaneo.Modo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FlujoTest {
    private fun r(estado: String, serial: String? = null, tipo: String? = Tipos.NOTEBOOK) =
        RespuestaEscaneo(estado = estado, serial = serial, tipo = tipo)

    @Test
    fun `guiado alterna notebook y su cargador`() {
        var f = Flujo(Modo.GUIADO)
        assertEquals(Tipos.NOTEBOOK, f.esperado)
        assertNull(f.serialEquipo)

        f = f.trasRespuesta(r("registrado", "5CD805DVNV"))
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertEquals("5CD805DVNV", f.serialEquipo)

        // Un error con el cargador no saca del paso: se reintenta el mismo.
        assertEquals(f, f.trasRespuesta(r("duplicado", tipo = null)))

        f = f.trasRespuesta(r("asignado", tipo = null))
        assertEquals(Tipos.NOTEBOOK, f.esperado)
    }

    @Test
    fun `guiado no pide cargador para monitores ni si el equipo esta en otra OT`() {
        val f = Flujo(Modo.GUIADO)
        assertNull(f.trasRespuesta(r("ya_estaba", "MON12345", Tipos.MONITOR)).equipoGuiado)
        assertNull(f.trasRespuesta(r("en_otra_ot", "5CD805DVNV")).equipoGuiado)
        assertNotNull(f.trasRespuesta(r("ya_estaba", "5CD805DVNV")).equipoGuiado)
    }

    @Test
    fun `saltar cargador y cambiar de modo`() {
        val f = Flujo(Modo.GUIADO, equipoGuiado = "5CD805DVNV")
        assertNull(f.saltarCargador().equipoGuiado)
        val rafaga = f.conModo(Modo.TRANSFORMADOR)
        assertEquals(Tipos.TRANSFORMADOR, rafaga.esperado)
        assertNull(rafaga.serialEquipo) // en ráfaga el PC elige el equipo
        assertEquals(rafaga, rafaga.trasRespuesta(r("asignado")))
    }

    @Test
    fun `cargador y elegir equipo solo lee`() {
        val f = Flujo(Modo.CARGADOR_ELEGIR)
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertTrue(f.soloLeer)
        assertNull(f.serialEquipo) // el equipo lo elige el usuario después
        assertEquals(f, f.trasRespuesta(r("asignado", tipo = null)))
        assertFalse(Flujo(Modo.GUIADO).soloLeer)
        assertFalse(Flujo(Modo.TRANSFORMADOR).soloLeer)
    }

    @Test
    fun `cargador pedido desde la ficha vale para una lectura`() {
        // Se estaba en guiado esperando el cargador de otro notebook.
        val antes = Flujo(Modo.GUIADO, equipoGuiado = "5CD805DVNV")
        val f = antes.paraCargadorDe("5CD805ABCD")
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertTrue(f.soloLeer)
        assertNull(f.serialEquipo)
        assertTrue("5CD805ABCD" in f.indicacion)

        // "leido" no lo termina: falta asignarlo. "asignado" sí, y se vuelve a como estaba.
        assertEquals(f, f.trasRespuesta(r("leido", tipo = null)))
        assertEquals(antes, f.trasRespuesta(r("asignado", tipo = null)))
        assertEquals(antes, f.sinCargadorPara())
        assertNull(f.conModo(Modo.NOTEBOOK).cargadorPara)
    }

    @Test
    fun `emparejamiento solo desde el QR del panel`() {
        val ok = Emparejamiento.desdeQr(
            """{"app":"inventario-arrienda","v":1,"url":"http://192.168.1.20:8765","token":"abc"}""",
        )
        assertEquals("http://192.168.1.20:8765", ok?.url)
        assertNull(Emparejamiento.desdeQr("5CD805DVNV"))
        assertNull(Emparejamiento.desdeQr("""{"app":"otra","v":1,"url":"http://x","token":"t"}"""))
        assertNull(Emparejamiento.desdeQr("""{"app":"inventario-arrienda","v":2,"url":"http://x","token":"t"}"""))
        assertNull(Emparejamiento.desdeQr("""{"app":"inventario-arrienda","v":1,"url":"ftp://x","token":"t"}"""))
        assertNull(Emparejamiento.desdeQr("""{"app":"inventario-arrienda","v":1,"url":"http://x","token":""}"""))
    }
}
