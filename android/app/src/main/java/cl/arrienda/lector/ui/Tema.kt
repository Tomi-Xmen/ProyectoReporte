package cl.arrienda.lector.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import cl.arrienda.lector.escaneo.Nivel

// Los mismos azules del reporte HTML del PC.
private val Azul = Color(0xFF1A3C6E)
private val AzulClaro = Color(0xFF93B4E6)

private val Claro = lightColorScheme(
    primary = Azul,
    secondary = Color(0xFF0F766E),
    background = Color(0xFFF5F7FA),
    surface = Color.White,
)

private val Oscuro = darkColorScheme(
    primary = AzulClaro,
    secondary = Color(0xFF5EEAD4),
)

@Composable
fun TemaLector(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Oscuro else Claro, content = content)
}

/** Color de fondo del aviso de cada respuesta: legible en claro y en oscuro (texto oscuro encima). */
fun colorNivel(n: Nivel): Color = when (n) {
    Nivel.OK -> Color(0xFFBBF7D0)
    Nivel.AVISO -> Color(0xFFFDE68A)
    Nivel.PREGUNTA -> Color(0xFFBFDBFE)
    Nivel.ERROR -> Color(0xFFFECACA)
}
