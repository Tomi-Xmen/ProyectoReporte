package cl.arrienda.lector.escaneo

import cl.arrienda.lector.data.RespuestaEscaneo

/** Cómo suena y vibra cada respuesta: se distingue sin mirar la pantalla. */
enum class Nivel { OK, AVISO, ERROR, PREGUNTA }

fun nivel(r: RespuestaEscaneo): Nivel = when (r.estado) {
    "registrado", "asignado" -> Nivel.OK
    "ya_estaba" -> Nivel.AVISO
    "en_otra_ot", "otro_tipo", "elegir", "sin_tipo" -> Nivel.PREGUNTA
    else -> Nivel.ERROR // duplicado, equipo_no_encontrado, sin_equipo_pendiente, invalido, sin_serial
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
    "elegir" -> "❔ Hay varios códigos: tocá el serial"
    "sin_serial" -> "❌ Ningún código era un serial"
    "sin_tipo" -> "❔ ¿Qué es ${r.valor}?"
    else -> r.estado
}
