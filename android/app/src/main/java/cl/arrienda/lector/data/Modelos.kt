package cl.arrienda.lector.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/*
 * Modelos del contrato con el PC. Espejo de inventario/nucleo/api_celular.py:
 * si allá cambia un nombre, cambia acá. Los tests de ApiPcTest decodifican
 * respuestas reales de la API de Python para detectar cualquier diferencia.
 */

val json = Json {
    ignoreUnknownKeys = true // el PC puede sumar campos sin romper celulares viejos
    explicitNulls = false // los opcionales en null no viajan
    encodeDefaults = true
}

object Tipos {
    const val NOTEBOOK = "Notebook"
    const val MONITOR = "Monitor"
    const val IMPRESORA = "Impresora"
    const val TRANSFORMADOR = "Transformador"
    val EQUIPOS = listOf(NOTEBOOK, MONITOR, IMPRESORA)
    val TODOS = EQUIPOS + TRANSFORMADOR
}

object Movimientos {
    const val ENTREGA = "Entrega"
    const val RETIRO = "Retiro"
}

/** Lo que trae el QR del panel "Lector celular" del PC. */
@Serializable
data class Emparejamiento(val app: String, val v: Int, val url: String, val token: String) {
    companion object {
        const val APP_ID = "inventario-arrienda"
        const val VERSION = 1

        /** El emparejamiento si el texto es un QR del panel, o null. */
        fun desdeQr(texto: String): Emparejamiento? {
            val e = runCatching { json.decodeFromString<Emparejamiento>(texto.trim()) }.getOrNull()
                ?: return null
            val valido = e.app == APP_ID && e.v == VERSION &&
                e.url.startsWith("http://") && e.token.isNotBlank()
            return if (valido) e else null
        }
    }
}

@Serializable
data class EstadoPc(val app: String, val v: Int)

/** Cómo se nombra un lote en cada pedido: siempre explícito, nunca "el activo del PC". */
@Serializable
data class LoteRef(val mov: String, val cliente: String, val numero: String)

@Serializable
data class LoteAbierto(
    val mov: String,
    val cliente: String,
    val numero: String,
    @SerialName("numero_sec") val numeroSec: String = "",
    val equipos: Int = 0,
    val etiqueta: String,
) {
    val ref get() = LoteRef(mov, cliente, numero)
}

@Serializable
data class RespuestaLotes(val lotes: List<LoteAbierto>)

@Serializable
data class RespuestaClientes(val clientes: List<String>)

@Serializable
data class EquipoLote(
    val serial: String,
    val tipo: String,
    val modelo: String = "",
    @SerialName("sn_transf") val snTransf: String? = null,
    @SerialName("sin_hardware") val sinHardware: Boolean = false,
)

@Serializable
data class EstadoLote(
    val mov: String,
    val cliente: String,
    val numero: String,
    @SerialName("numero_sec") val numeroSec: String = "",
    val etiqueta: String,
    val equipos: List<EquipoLote> = emptyList(),
) {
    val ref get() = LoteRef(mov, cliente, numero)
}

@Serializable
data class PedidoLote(val lote: LoteRef)

@Serializable
data class PedidoNuevoLote(
    val mov: String,
    val cliente: String,
    val numero: String,
    @SerialName("numero_sec") val numeroSec: String = "",
    val reabrir: Boolean = false,
)

@Serializable
data class Lectura(val texto: String, val formato: String = "")

@Serializable
data class PedidoEscaneo(
    val id: String,
    val lote: LoteRef,
    val lecturas: List<Lectura>,
    val esperado: String? = null,
    val tipo: String? = null,
    @SerialName("serial_equipo") val serialEquipo: String? = null,
    val forzar: Boolean? = null,
)

@Serializable
data class Descarte(val texto: String, val motivo: String)

/** Una sola clase para todos los estados: cada uno usa sus campos (ver api_celular._escaneo). */
@Serializable
data class RespuestaEscaneo(
    val estado: String,
    val serial: String? = null,
    val tipo: String? = null,
    val total: Int? = null,
    val otro: String? = null,
    val motivo: String? = null,
    @SerialName("sn_transf") val snTransf: String? = null,
    val equipo: String? = null,
    val reemplazo: String? = null,
    val candidatos: List<String> = emptyList(),
    val valor: String? = null,
    val esperado: String? = null,
    val descartes: List<Descarte> = emptyList(),
    val lote: String? = null,
)

@Serializable
data class ErrorApi(val error: String = "", val titulo: String? = null, val mensaje: String = "")
