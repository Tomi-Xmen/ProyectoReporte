package cl.arrienda.lector

import cl.arrienda.lector.data.ApiPc
import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.Lectura
import cl.arrienda.lector.data.LoteRef
import cl.arrienda.lector.data.PedidoEscaneo
import cl.arrienda.lector.data.Resultado
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** El cliente HTTP contra un servidor falso: cabeceras, cuerpo, errores y reintentos. */
class ApiPcTest {
    private lateinit var servidor: MockWebServer
    private lateinit var api: ApiPc
    private val lote = LoteRef("Entrega", "ACME", "553")

    @Before
    fun arrancar() {
        servidor = MockWebServer().apply { start() }
        val url = servidor.url("/").toString().trimEnd('/')
        api = ApiPc(Emparejamiento("inventario-arrienda", 1, url, "tok"), dormir = {})
    }

    @After
    fun parar() = servidor.shutdown()

    private fun pedido() = PedidoEscaneo(
        id = "id-1",
        lote = lote,
        lecturas = listOf(Lectura("S/N: 5CD805DVNV", "CODE_128")),
        esperado = "Transformador",
        serialEquipo = "5CD805DVNV",
    )

    @Test
    fun `manda token y cuerpo con los nombres que espera Python`() = runTest {
        servidor.enqueue(MockResponse().setBody("""{"estado":"asignado","equipo":"5CD805DVNV","sn_transf":"TR-1"}"""))
        val r = api.escanear(pedido())
        assertTrue(r is Resultado.Ok)

        val enviado = servidor.takeRequest()
        assertEquals("/api/v1/escaneo", enviado.path)
        assertEquals("POST", enviado.method)
        assertEquals("Bearer tok", enviado.getHeader("Authorization"))
        val cuerpo = Json.parseToJsonElement(enviado.body.readUtf8()).jsonObject
        assertEquals("5CD805DVNV", cuerpo["serial_equipo"]!!.jsonPrimitive.content)
        assertEquals("ACME", cuerpo["lote"]!!.jsonObject["cliente"]!!.jsonPrimitive.content)
        // Los opcionales sin valor no viajan (el PC trata 'forzar' ausente como false).
        assertFalse("forzar" in cuerpo)
        assertFalse("tipo" in cuerpo)
    }

    @Test
    fun `un error del PC llega como Rechazado con su mensaje`() = runTest {
        servidor.enqueue(MockResponse().setResponseCode(401).setBody("""{"error":"no_autorizado","mensaje":"Emparejá"}"""))
        val r = api.lotes()
        assertTrue(r is Resultado.Rechazado)
        r as Resultado.Rechazado
        assertEquals(401, r.codigo)
        assertEquals("no_autorizado", r.error.error)
        assertEquals(1, servidor.requestCount) // un rechazo no se reintenta
    }

    @Test
    fun `sin respuesta reintenta con el mismo id`() = runTest {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        servidor.enqueue(MockResponse().setBody("""{"estado":"registrado","serial":"X1","tipo":"Monitor","total":1}"""))
        val r = api.escanear(pedido())
        assertTrue(r is Resultado.Ok)
        assertEquals(2, servidor.requestCount)
        servidor.takeRequest() // el cortado: el servidor no llegó a leer su cuerpo
        val reintento = Json.parseToJsonElement(servidor.takeRequest().body.readUtf8()).jsonObject
        assertEquals("id-1", reintento["id"]!!.jsonPrimitive.content)
    }

    @Test
    fun `PC apagado es SinConexion despues de reintentar`() = runTest {
        repeat(3) { servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)) }
        assertTrue(api.escanear(pedido()) is Resultado.SinConexion)
        assertEquals(3, servidor.requestCount)
    }

    @Test
    fun `el ping rechaza otra app u otra version`() = runTest {
        servidor.enqueue(MockResponse().setBody("""{"app":"inventario-arrienda","v":1}"""))
        assertTrue(api.estado() is Resultado.Ok)
        servidor.enqueue(MockResponse().setBody("""{"app":"inventario-arrienda","v":2}"""))
        assertTrue(api.estado() is Resultado.Rechazado)
    }
}
