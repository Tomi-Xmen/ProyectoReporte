package cl.arrienda.lector

import cl.arrienda.lector.data.CambiosEquipo
import cl.arrienda.lector.data.Disco
import cl.arrienda.lector.data.HardwareEquipo
import cl.arrienda.lector.data.ErrorApi
import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.EstadoPc
import cl.arrienda.lector.data.FichaEquipo
import cl.arrienda.lector.data.RespuestaAccion
import cl.arrienda.lector.data.RespuestaCierre
import cl.arrienda.lector.data.RespuestaClientes
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.RespuestaLotes
import cl.arrienda.lector.data.ResumenCierre
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
import org.junit.Assert.assertFalse
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

    @Test
    fun `ficha de un equipo y su edicion`() {
        val f = cuerpo("equipo", FichaEquipo.serializer())
        assertEquals("5CD805DVNV", f.serial)
        assertEquals("TR-0009", f.datos.snTransf)
        assertEquals("", f.datos.obs) // "Sin observaciones" llega vacío
        assertFalse(f.sinHardware)
        assertEquals("Intel i5", f.hardware.cpu)
        assertEquals(listOf("DISCO-01"), f.hardware.discos.map { it.serial })
        assertEquals(listOf("OK", "OBS", "MALO"), f.opciones.estados)
        assertEquals(11, f.componentes.size)

        val monitor = cuerpo("equipo_sin_hardware", FichaEquipo.serializer())
        assertTrue(monitor.sinHardware)
        assertEquals(HardwareEquipo(), monitor.hardware)

        val conHw = cuerpo("equipo_hardware_editado", FichaEquipo.serializer())
        assertEquals("Intel i7", conHw.hardware.cpu)
        assertEquals(listOf(Disco("SSD 500GB", "AB1234")), conHw.hardware.discos)

        val editada = cuerpo("equipo_editado", FichaEquipo.serializer())
        assertEquals("Rayón en tapa", editada.datos.obs)
        assertTrue(editada.version != f.version)

        assertEquals(404, codigo("equipo_inexistente"))
        assertEquals("cambiado", cuerpo("equipo_cambiado", ErrorApi.serializer()).error)
        assertEquals(409, codigo("equipo_transformador_duplicado"))
        assertEquals("duplicado", cuerpo("equipo_transformador_duplicado", ErrorApi.serializer()).error)
    }

    @Test
    fun `cargador leido y pasado de un equipo a otro`() {
        val libre = escaneo("escaneo_leido_libre")
        assertEquals("leido", libre.estado)
        assertEquals("TR-0100", libre.snTransf)
        assertNull(libre.equipo)
        assertEquals(Nivel.PREGUNTA, nivel(libre))

        val leido = escaneo("escaneo_leido")
        assertEquals("5CD805DVNV", leido.equipo)
        assertTrue("5CD805DVNV" in describir(leido))

        val pasado = escaneo("escaneo_reasignado")
        assertEquals("asignado", pasado.estado)
        assertEquals("5CD805ABCD", pasado.equipo)
        assertEquals("5CD805DVNV", pasado.desde)
        assertEquals("TR-0003", pasado.reemplazo)
        assertTrue("era de 5CD805DVNV" in describir(pasado))
    }

    @Test
    fun `gestion del lote`() {
        val resumen = cuerpo("lote_resumen", ResumenCierre.serializer())
        assertEquals(3, resumen.equipos)
        assertEquals(listOf("5CD805DVNV"), resumen.sinCargador)
        assertNull(resumen.faltaDocumento)

        val conGuia = cuerpo("lote_documento", EstadoLote.serializer())
        assertEquals("G-10", conGuia.numeroSec)
        assertEquals(400, codigo("lote_documento_invalido"))

        val movido = cuerpo("equipo_mover", RespuestaAccion.serializer())
        assertEquals("movido", movido.estado)
        assertEquals("MON12345", movido.serial)
        assertTrue(movido.destino!!.startsWith("BETA"))
        assertEquals("mismo_lote", cuerpo("equipo_mover_mismo_lote", ErrorApi.serializer()).error)

        val quitado = cuerpo("equipo_quitar", RespuestaAccion.serializer())
        assertEquals("quitado", quitado.estado)
        assertEquals(1, quitado.total)
        assertEquals(404, codigo("equipo_quitar_inexistente"))

        val cerrado = cuerpo("lote_cerrar", RespuestaCierre.serializer())
        assertEquals("cerrado", cerrado.estado)
        assertEquals(1, cerrado.total)
        assertTrue(cerrado.backup!!.endsWith(".zip"))
        assertEquals(409, codigo("lote_cerrado_resumen"))
        assertEquals("lote", cuerpo("lote_cerrado_resumen", ErrorApi.serializer()).error)
    }

    @Test
    fun `solo viajan los campos tocados`() {
        val f = cuerpo("equipo", FichaEquipo.serializer())
        assertTrue(CambiosEquipo.entre(f, f.datos, f.componentes, f.hardware).vacio)

        val componentes = f.componentes.toMutableList()
        componentes[1] = componentes[1].copy(estado = "MALO", obs = "Píxeles muertos")
        val c = CambiosEquipo.entre(f, f.datos.copy(obs = "Rayón"), componentes, f.hardware)
        assertEquals(CambiosEquipo(obs = "Rayón", componentes = componentes), c)

        val hw = f.hardware.copy(cpu = "Intel i7")
        assertEquals(CambiosEquipo(hardware = hw), CambiosEquipo.entre(f, f.datos, f.componentes, hw))
        // explicitNulls = false: los campos no tocados no van en el JSON.
        val enviado = cl.arrienda.lector.data.json.encodeToString(CambiosEquipo.serializer(), c)
        assertFalse("modelo" in enviado)
    }
}
