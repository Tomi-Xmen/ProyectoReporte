package cl.arrienda.lector.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Resultado de hablar con el PC: o respondió bien, o respondió que no, o no respondió. */
sealed interface Resultado<out T> {
    data class Ok<T>(val valor: T) : Resultado<T>

    /** El PC contestó con un error (401 desemparejado, 404/409 lote, 400 dato…). */
    data class Rechazado(val codigo: Int, val error: ErrorApi) : Resultado<Nothing>

    /** No hubo respuesta: Wi-Fi cortado, PC apagado o panel cerrado. */
    data class SinConexion(val causa: String) : Resultado<Nothing>
}

/**
 * Cliente de la API del PC. Reintenta lo que no tuvo respuesta mandando el
 * MISMO cuerpo: en un escaneo eso incluye su id, y el PC devuelve la respuesta
 * que ya dio en vez de procesarlo dos veces.
 */
class ApiPc(
    emparejamiento: Emparejamiento,
    private val http: OkHttpClient = clientePorDefecto(),
    private val esperas: List<Long> = listOf(400, 1200),
    private val dormir: suspend (Long) -> Unit = { delay(it) },
) {
    private val base = emparejamiento.url.trimEnd('/') + "/api/v1"
    private val autorizacion = "Bearer ${emparejamiento.token}"

    /** Ping: confirma que del otro lado está el panel y que el token sirve. */
    suspend fun estado(): Resultado<EstadoPc> =
        when (val r = pedir("GET", "/estado", null, EstadoPc.serializer())) {
            is Resultado.Ok ->
                if (r.valor.app == Emparejamiento.APP_ID && r.valor.v == Emparejamiento.VERSION) r
                else Resultado.Rechazado(0, ErrorApi("version", mensaje = "El PC tiene otra versión del lector."))
            else -> r
        }

    suspend fun lotes(): Resultado<List<LoteAbierto>> =
        pedir("GET", "/lotes", null, RespuestaLotes.serializer()).mapear { it.lotes }

    suspend fun clientes(): Resultado<List<String>> =
        pedir("GET", "/clientes", null, RespuestaClientes.serializer()).mapear { it.clientes }

    suspend fun crearLote(pedido: PedidoNuevoLote): Resultado<EstadoLote> =
        pedir("POST", "/lotes", json.encodeToString(PedidoNuevoLote.serializer(), pedido), EstadoLote.serializer())

    suspend fun estadoLote(lote: LoteRef): Resultado<EstadoLote> =
        pedir("POST", "/lote", json.encodeToString(PedidoLote.serializer(), PedidoLote(lote)), EstadoLote.serializer())

    suspend fun ficha(lote: LoteRef, serial: String): Resultado<FichaEquipo> =
        pedir("POST", "/equipo", json.encodeToString(PedidoEquipo.serializer(), PedidoEquipo(lote, serial)), FichaEquipo.serializer())

    suspend fun editar(pedido: PedidoEditar): Resultado<FichaEquipo> =
        pedir("POST", "/equipo/editar", json.encodeToString(PedidoEditar.serializer(), pedido), FichaEquipo.serializer())

    suspend fun escanear(pedido: PedidoEscaneo): Resultado<RespuestaEscaneo> =
        pedir("POST", "/escaneo", json.encodeToString(PedidoEscaneo.serializer(), pedido), RespuestaEscaneo.serializer())

    // Gestión del lote. Si un reintento llega después de que el PC ya lo hizo,
    // responde 404/409 (el equipo ya no está, el lote ya está cerrado): la app
    // lo muestra como mensaje y nada se hace dos veces.
    suspend fun mover(pedido: PedidoMover): Resultado<RespuestaAccion> =
        pedir("POST", "/equipo/mover", json.encodeToString(PedidoMover.serializer(), pedido), RespuestaAccion.serializer())

    suspend fun quitar(lote: LoteRef, serial: String): Resultado<RespuestaAccion> =
        pedir("POST", "/equipo/quitar", json.encodeToString(PedidoEquipo.serializer(), PedidoEquipo(lote, serial)), RespuestaAccion.serializer())

    suspend fun documento(lote: LoteRef, numeroSec: String): Resultado<EstadoLote> =
        pedir("POST", "/lote/documento", json.encodeToString(PedidoDocumento.serializer(), PedidoDocumento(lote, numeroSec)), EstadoLote.serializer())

    suspend fun resumenCierre(lote: LoteRef): Resultado<ResumenCierre> =
        pedir("POST", "/lote/resumen", json.encodeToString(PedidoLote.serializer(), PedidoLote(lote)), ResumenCierre.serializer())

    suspend fun cerrar(lote: LoteRef): Resultado<RespuestaCierre> =
        pedir("POST", "/lote/cerrar", json.encodeToString(PedidoLote.serializer(), PedidoLote(lote)), RespuestaCierre.serializer())

    private suspend fun <T> pedir(
        metodo: String,
        ruta: String,
        cuerpo: String?,
        lector: DeserializationStrategy<T>,
    ): Resultado<T> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(base + ruta)
            .header("Authorization", autorizacion)
            .method(metodo, cuerpo?.toRequestBody(JSON))
            .build()

        var ultimaCausa = ""
        for (intento in 0..esperas.size) {
            if (intento > 0) dormir(esperas[intento - 1])
            try {
                http.newCall(request).execute().use { r ->
                    val texto = r.body?.string().orEmpty()
                    return@withContext if (r.isSuccessful) {
                        Resultado.Ok(json.decodeFromString(lector, texto))
                    } else {
                        val error = runCatching { json.decodeFromString(ErrorApi.serializer(), texto) }
                            .getOrDefault(ErrorApi(mensaje = "El PC respondió ${r.code}."))
                        Resultado.Rechazado(r.code, error)
                    }
                }
            } catch (e: IOException) {
                ultimaCausa = e.message ?: e.javaClass.simpleName
            }
        }
        Resultado.SinConexion(ultimaCausa)
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun clientePorDefecto(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(8, TimeUnit.SECONDS)
            .callTimeout(10, TimeUnit.SECONDS)
            // Los reintentos los maneja ApiPc (con el mismo id), no OkHttp.
            .retryOnConnectionFailure(false)
            .build()
    }
}

private inline fun <T, R> Resultado<T>.mapear(f: (T) -> R): Resultado<R> = when (this) {
    is Resultado.Ok -> Resultado.Ok(f(valor))
    is Resultado.Rechazado -> this
    is Resultado.SinConexion -> this
}
