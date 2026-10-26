package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.RespuestaEscaneo

/** Cómo suena y vibra cada respuesta: se distingue sin mirar la pantalla. */
enum class Nivel { OK, AVISO, ERROR, PREGUNTA }

fun nivel(r: RespuestaEscaneo): Nivel = when (r.estado) {
    "registrado", "asignado", "propuesto" -> Nivel.OK
    "ya_estaba" -> Nivel.AVISO
    "en_otra_ot", "otro_tipo", "elegir", "sin_tipo" -> Nivel.PREGUNTA
    else -> Nivel.ERROR // duplicado, equipo_no_encontrado, sin_equipo_pendiente, es_equipo, invalido, sin_serial
}

/** Qué pasó con un escaneo pendiente al reenviarlo. */
enum class Reenvio {
    /** Quedó en el PC. */
    LISTO,
    /** Cargador revisado: falta sumarlo a la lista y guardarla. */
    A_LA_LISTA,
    /** El PC necesita una decisión del usuario: NO quedó registrado. */
    PREGUNTAR,
    /** El PC lo rechazó: NO quedó registrado. */
    FALLO,
}

fun reenvio(r: RespuestaEscaneo): Reenvio = when (r.estado) {
    "registrado", "asignado", "ya_estaba" -> Reenvio.LISTO
    "propuesto" -> Reenvio.A_LA_LISTA
    else -> if (nivel(r) == Nivel.PREGUNTA) Reenvio.PREGUNTAR else Reenvio.FALLO
}

/** Texto de una respuesta. Mismos textos que describir_respuesta del PC. */
fun describir(r: RespuestaEscaneo): String = when (r.estado) {
    "registrado" -> "✅ ${r.tipo} ${r.serial} registrado (${r.total} en el lote)"
    "asignado" -> "🔌 Cargador ${r.snTransf} → ${r.equipo}" +
        (r.reemplazo?.let { " (reemplazó a $it)" } ?: "")
    "ya_estaba" ->
        if (r.snTransf != null) "☑️ El cargador ${r.snTransf} ya era de ${r.equipo}"
        else "☑️ ${r.serial} ya estaba en el lote"
    "en_otra_ot" -> "⚠️ ${r.serial} ya está en ${r.otro}"
    "duplicado" -> "⚠️ El cargador ${r.snTransf} ya es de ${r.equipo}"
    "otro_tipo" -> "❔ ${r.valor} parece ${r.tipo}, no ${r.esperado}"
    "invalido" -> "❌ ${r.motivo ?: "Código inválido"}"
    "equipo_no_encontrado" -> "⚠️ El equipo ${r.serial} no está en el lote"
    "sin_equipo_pendiente" -> "⚠️ No quedan notebooks sin cargador"
    "propuesto" -> "🔌 Cargador ${r.snTransf} leído (falta guardar)"
    "es_equipo" -> "⚠️ ${r.snTransf} es un equipo del lote, no un cargador"
    "elegir" -> "❔ Hay varios códigos: tocá el serial"
    "sin_serial" -> "❌ Ningún código era un serial"
    "sin_tipo" -> "❔ ¿Qué es ${r.valor}?"
    else -> r.estado
}
