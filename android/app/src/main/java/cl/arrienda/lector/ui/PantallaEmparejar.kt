package cl.arrienda.lector.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import cl.arrienda.lector.escaneo.Estabilizador
import cl.arrienda.lector.escaneo.VistaCamara

@Composable
fun PantallaEmparejar(estado: EstadoUi, vm: LectorViewModel) {
    // Para el QR alcanza con verlo una vez bien: no hay etiquetas con varios códigos.
    val estabilizador = remember { Estabilizador(cuadrosNecesarios = 2) }
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("📱 Emparejar con el PC", style = MaterialTheme.typography.headlineSmall)
        Text(
            "En el PC: menú → Lector celular → Encender. Apuntá la cámara al código QR que aparece.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Box(Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(16.dp))) {
            VistaCamara(
                activo = !estado.ocupado,
                linterna = false,
                estabilizador = estabilizador,
                alLeer = vm::alLeerQr,
                modifier = Modifier.fillMaxSize(),
            )
        }
        estado.mensaje?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (estado.hayEmparejamientoGuardado && !estado.ocupado) {
            OutlinedButton(onClick = vm::reintentarConexion, Modifier.fillMaxWidth()) {
                Text("Reintentar con el PC anterior")
            }
        }
    }
}
