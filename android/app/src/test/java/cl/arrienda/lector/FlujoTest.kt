package cl.arrienda.lector

import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.EquipoLote
import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.Tipos
import cl.arrienda.lector.escaneo.Flujo
import cl.arrienda.lector.escaneo.Modo
import cl.arrienda.lector.escaneo.proximoSinCargador
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FlujoTest {
    private fun lote(vararg equipos: EquipoLote) =
        EstadoLote(mov = "Entrega", cliente = "ACME", numero = "553", etiqueta = "ACME · OT-553", equipos = equipos.toList())

    @Test
    fun `se entra escaneando cargadores`() {
        val f = Flujo()
        assertEquals(Modo.TRANSFORMADOR, f.modo)
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertEquals(Tipos.NOTEBOOK, f.conModo(Modo.NOTEBOOK).esperado)
    }

    @Test
    fun `indica el proximo notebook sin cargador en orden de escaneo`() {
        val l = lote(
            EquipoLote("5CD0000001", Tipos.NOTEBOOK, snTransf = "WHHRE0A1RKAL0C"),
            EquipoLote("MON12345", Tipos.MONITOR),
            EquipoLote("5CD0000002", Tipos.NOTEBOOK),
            EquipoLote("5CD0000003", Tipos.NOTEBOOK),
        )
        assertEquals("5CD0000002", proximoSinCargador(l))
        assertEquals("Escaneá el cargador de 5CD0000002", Flujo().indicacion(l))
        assertNull(proximoSinCargador(lote(EquipoLote("5CD0000001", Tipos.NOTEBOOK, snTransf = "W1"))))
        assertEquals("Todos los notebooks tienen cargador", Flujo().indicacion(lote()))
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
