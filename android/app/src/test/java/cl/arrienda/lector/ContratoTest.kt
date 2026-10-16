package cl.arrienda.lector

import cl.arrienda.lector.data.ErrorApi
import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.EstadoPc
import cl.arrienda.lector.data.RespuestaClientes
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.RespuestaLotes
import cl.arrienda.lector.escaneo.Nivel
import cl.arrienda.lector.escaneo.describir
import cl.arrienda.lector.escaneo.nivel
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Respuestas REALES de la API de Python (las genera tests/test_contrato_celular.py).
 * Se decodifican en modo estricto: un campo que el PC manda y la app no modela
 * hace fallar el test, en vez de perderse en silencio.
 */
class ContratoTest {
    private val estricto = Json { ignoreUnknownKeys = false }

    private val casos: Map<String, JsonObject> by lazy {
        val texto = javaClass.classLoader!!.getResource("contrato/respuestas_api.json")!!.readText()
        estricto.parseToJsonElement(texto).jsonObject.mapValues { it.value.jsonObject }
    }

    private fun codigo(caso: String) = casos.getValue(caso)["codigo"]!!.jsonPrimitive.int

    private fun <T> cuerpo(caso: String, lector: DeserializationStrategy<T>): T =
        estricto.decodeFromJsonElement(lector, casos.getValue(caso)["cuerpo"]!!)

    private fun escaneo(caso: String) = cuerpo(caso, RespuestaEscaneo.serializer())

    @Test
    fun `lotes, clientes y estado del lote`() {
        assertEquals("inventario-arrienda", cuerpo("estado", EstadoPc.serializer()).app)

        val lotes = cuerpo("lotes", RespuestaLotes.serializer()).lotes
        val acme = lotes.single { it.cliente == "ACME" }
        assertEquals("553", acme.numero)
        assertEquals("G-9", acme.numeroSec)
        assertEquals(2, acme.equipos)

        assertEquals(listOf("ACME", "BETA"), cuerpo("clientes", RespuestaClientes.serializer()).clientes)

        val lote = cuerpo("lote", EstadoLote.serializer())
        assertEquals(2, lote.equipos.size)
        assertTrue(lote.equipos.none { it.sinHardware })

        val nuevo = cuerpo("crear_lote", EstadoLote.serializer())
        assertEquals("GAMMA", nuevo.cliente)
        assertEquals("5", nuevo.numero) // "Guía 5" normalizado por el PC
    }

    @Test
    fun `errores del PC`() {
        assertEquals(401, codigo("no_autorizado"))
        assertEquals(404, codigo("lote_inexistente"))
        assertEquals(409, codigo("crear_lote_cerrado"))
        assertEquals("cerrado", cuerpo("crear_lote_cerrado", ErrorApi.serializer()).error)
        val invalido = cuerpo("crear_lote_invalido", ErrorApi.serializer())
        assertEquals(400, codigo("crear_lote_invalido"))
        assertEquals("Falta el cliente", invalido.titulo)
    }

    @Test
    fun `cada estado de escaneo se decodifica y tiene texto y nivel`() {
        val r = escaneo("escaneo_registrado")
        assertEquals("MON12345", r.serial)
        assertEquals(1, r.descartes.size)
        assertEquals(Nivel.OK, nivel(r))

        assertEquals("TR-0001", escaneo("escaneo_asignado_reemplazo").reemplazo)
        assertNull(escaneo("escaneo_asignado").reemplazo)
        assertEquals(listOf("ABC12345", "XYZ98765"), escaneo("escaneo_elegir").candidatos)
        assertEquals("Transformador", escaneo("escaneo_otro_tipo").esperado)

        val esperados = mapOf(
            "escaneo_registrado" to Nivel.OK,
            "escaneo_asignado" to Nivel.OK,
            "escaneo_rafaga" to Nivel.OK,
            "escaneo_ya_estaba" to Nivel.AVISO,
            "escaneo_transformador_ya_estaba" to Nivel.AVISO,
            "escaneo_en_otra_ot" to Nivel.PREGUNTA,
            "escaneo_elegir" to Nivel.PREGUNTA,
            "escaneo_otro_tipo" to Nivel.PREGUNTA,
            "escaneo_sin_tipo" to Nivel.PREGUNTA,
            "escaneo_duplicado" to Nivel.ERROR,
            "escaneo_equipo_no_encontrado" to Nivel.ERROR,
            "escaneo_sin_equipo_pendiente" to Nivel.ERROR,
            "escaneo_sin_serial" to Nivel.ERROR,
        )
        for ((caso, n) in esperados) {
            val resp = escaneo(caso)
            assertEquals(caso, n, nivel(resp))
            val texto = describir(resp)
            assertTrue("$caso sin texto propio: $texto", texto != resp.estado && "null" !in texto)
        }
    }
}
