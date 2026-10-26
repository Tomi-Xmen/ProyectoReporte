package cl.arrienda.lector

import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.EquipoLote
import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.ParCargador
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Tipos
import cl.arrienda.lector.escaneo.Flujo
import cl.arrienda.lector.escaneo.Modo
import cl.arrienda.lector.escaneo.proximoSinCargador
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FlujoTest {
    private fun r(estado: String, serial: String? = null, tipo: String? = Tipos.NOTEBOOK) =
        RespuestaEscaneo(estado = estado, serial = serial, tipo = tipo)

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
        // Los que ya están en la lista sin guardar no reciben otro cargador.
        val lista = listOf(ParCargador("5CD0000002", "WHHRE0A1RK0002"))
        assertEquals("5CD0000003", proximoSinCargador(l, lista))
        assertNull(proximoSinCargador(l, lista + ParCargador("5CD0000003", "WHHRE0A1RK0003")))
        assertNull(proximoSinCargador(lote(EquipoLote("5CD0000001", Tipos.NOTEBOOK, snTransf = "W1"))))
        assertEquals("Todos los notebooks tienen cargador", Flujo().indicacion(lote()))
    }

    @Test
    fun `cargador y elegir equipo solo lee`() {
        val f = Flujo(Modo.CARGADOR_ELEGIR)
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertTrue(f.soloLeer)
        assertFalse(f.aLaLista) // se guarda en el momento, sin lista
        assertEquals(f, f.trasRespuesta(r("asignado", tipo = null)))
        assertFalse(Flujo(Modo.TRANSFORMADOR).soloLeer)
        assertTrue(Flujo(Modo.TRANSFORMADOR).aLaLista)
    }

    @Test
    fun `cargador pedido desde la ficha vale para una lectura`() {
        // Se estaba armando la lista de cargadores: este va directo, no a la lista.
        val antes = Flujo(Modo.TRANSFORMADOR)
        val f = antes.paraCargadorDe("5CD805ABCD")
        assertEquals(Tipos.TRANSFORMADOR, f.esperado)
        assertTrue(f.soloLeer)
        assertFalse(f.aLaLista)
        assertTrue("5CD805ABCD" in f.indicacion(null))
        assertEquals(Tipos.TRANSFORMADOR, Flujo(Modo.NOTEBOOK).paraCargadorDe("X").esperado)

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
