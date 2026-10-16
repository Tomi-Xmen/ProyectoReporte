package cl.arrienda.lector

import cl.arrienda.lector.data.ApiPc
import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.Lectura
import cl.arrienda.lector.data.LoteRef
import cl.arrienda.lector.data.PedidoEscaneo
import cl.arrienda.lector.data.PedidoNuevoLote
import cl.arrienda.lector.data.Resultado
import cl.arrienda.lector.data.Tipos
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * La app contra el servidor REAL del PC (QtNetwork + api_celular.py), no uno
 * falso: prueba que el HTTP escrito a mano en Python y OkHttp se entienden.
 * Se salta salvo que se indique un PC:
 *
 *   LECTOR_PC_URL=http://127.0.0.1:8765  LECTOR_PC_TOKEN=…
 *
 * con un lote ACME OT-553 abierto que tenga el notebook 5CD805DVNV.
 */
class IntegracionPcTest {
    private val url = System.getenv("LECTOR_PC_URL")
    private val token = System.getenv("LECTOR_PC_TOKEN")

    private fun <T> ok(r: Resultado<T>): T {
        assertTrue("Esperaba Ok y llegó $r", r is Resultado.Ok)
        return (r as Resultado.Ok).valor
    }

    @Test
    fun `flujo completo contra el PC`() = runBlocking {
        assumeTrue("Sin PC indicado (LECTOR_PC_URL)", !url.isNullOrBlank() && !token.isNullOrBlank())
        val api = ApiPc(Emparejamiento(Emparejamiento.APP_ID, 1, url!!, token!!))
        val lote = LoteRef("Entrega", "ACME", "553")

        ok(api.estado())
        assertTrue(ok(api.lotes()).any { it.ref == lote })
        assertEquals(1, ok(api.estadoLote(lote)).equipos.size)

        val notebook = ok(
            api.escanear(
                PedidoEscaneo(
                    id = "int-1", lote = lote, esperado = Tipos.NOTEBOOK,
                    lecturas = listOf(Lectura("7801234567890", "EAN_13"), Lectura("S/N: 5cd805dvnv", "CODE_128")),
                ),
            ),
        )
        assertEquals("ya_estaba", notebook.estado)
        assertEquals(1, notebook.descartes.size)

        val cargador = ok(
            api.escanear(
                PedidoEscaneo(
                    id = "int-2", lote = lote, esperado = Tipos.TRANSFORMADOR,
                    serialEquipo = notebook.serial, lecturas = listOf(Lectura("TR-0001")),
                ),
            ),
        )
        assertEquals("asignado", cargador.estado)

        val monitor = ok(
            api.escanear(
                PedidoEscaneo(id = "int-3", lote = lote, esperado = Tipos.MONITOR, lecturas = listOf(Lectura("MON12345"))),
            ),
        )
        assertEquals("registrado", monitor.estado)
        // El mismo id otra vez (reintento): misma respuesta, sin duplicar.
        val reintento = ok(
            api.escanear(
                PedidoEscaneo(id = "int-3", lote = lote, esperado = Tipos.MONITOR, lecturas = listOf(Lectura("MON12345"))),
            ),
        )
        assertEquals("registrado", reintento.estado)

        val estado = ok(api.estadoLote(lote))
        assertEquals(2, estado.equipos.size)
        assertEquals("TR-0001", estado.equipos.single { it.serial == "5CD805DVNV" }.snTransf)

        val nuevo = ok(api.crearLote(PedidoNuevoLote("Retiro", "Gamma Ltda", "Guía 77")))
        assertEquals("GAMMA_LTDA" to "77", nuevo.cliente to nuevo.numero)

        val intruso = ApiPc(Emparejamiento(Emparejamiento.APP_ID, 1, url, "token-viejo"))
        val r = intruso.lotes()
        assertTrue(r is Resultado.Rechazado && r.codigo == 401)
    }
}
