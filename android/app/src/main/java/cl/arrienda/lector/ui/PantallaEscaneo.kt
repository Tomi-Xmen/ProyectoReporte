package cl.arrienda.lector.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import cl.arrienda.lector.data.EquipoLote
import cl.arrienda.lector.data.Tipos
import cl.arrienda.lector.escaneo.Modo
import cl.arrienda.lector.escaneo.VistaCamara

@Composable
fun PantallaEscaneo(estado: EstadoUi, vm: LectorViewModel) {
    val lote = estado.lote ?: return
    var linterna by rememberSaveable { mutableStateOf(false) }
    var manual by rememberSaveable { mutableStateOf("") }

    // Se escanea con el celular en la mano durante minutos: que no se apague la pantalla.
    val vista = LocalView.current
    DisposableEffect(Unit) {
        vista.keepScreenOn = true
        onDispose { vista.keepScreenOn = false }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = vm::volverALotes) { Text("‹ Lotes") }
            Text(lote.etiqueta, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Text("${lote.equipos.size}", style = MaterialTheme.typography.titleMedium)
        }

        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Modo.entries.forEach { m ->
                FilterChip(
                    selected = estado.flujo.modo == m,
                    onClick = { vm.cambiarModo(m) },
                    label = { Text(m.etiqueta) },
                )
            }
        }

        Box(Modifier.fillMaxWidth().aspectRatio(4f / 3f).clip(RoundedCornerShape(16.dp))) {
            VistaCamara(
                activo = !estado.ocupado && estado.pregunta == null,
                linterna = linterna,
                estabilizador = vm.estabilizador,
                alLeer = vm::alLeer,
                modifier = Modifier.fillMaxSize(),
            )
            Text(
                estado.flujo.indicacion,
                color = Color.White,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .background(Color(0x99000000))
                    .padding(8.dp),
            )
            if (estado.ocupado) {
                CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
        }

        estado.aviso?.let { a ->
            Text(
                a.texto,
                color = Color(0xFF111827),
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(colorNivel(a.nivel))
                    .padding(12.dp),
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedButton(onClick = { linterna = !linterna }) { Text(if (linterna) "🔦 Apagar" else "🔦 Luz") }
            OutlinedButton(onClick = vm::leerDeNuevo) { Text("↻ Releer") }
            if (estado.flujo.modo == Modo.GUIADO && estado.flujo.equipoGuiado != null) {
                OutlinedButton(onClick = vm::saltarCargador) { Text("Sin cargador") }
            }
        }
        if (estado.pendientes.isNotEmpty()) {
            Button(onClick = vm::reintentarPendientes, enabled = !estado.ocupado, modifier = Modifier.fillMaxWidth()) {
                Text("📵 Reintentar ${estado.pendientes.size} pendiente(s)")
            }
        }

        // Para etiquetas ilegibles: se escribe el serial y pasa por el mismo camino.
        OutlinedTextField(
            value = manual,
            onValueChange = { manual = it },
            label = { Text("Escribir serial a mano") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = {
                vm.ingresarManual(manual)
                manual = ""
            }),
            modifier = Modifier.fillMaxWidth(),
        )

        HorizontalDivider()
        LazyColumn(Modifier.weight(1f)) {
            // Sin key: un lote viejo podría traer dos registros con el mismo serial.
            items(lote.equipos.asReversed()) { e -> FilaEquipo(e) }
        }
    }
}

@Composable
private fun FilaEquipo(e: EquipoLote) {
    val icono = when (e.tipo) {
        Tipos.MONITOR -> "🖥️"
        Tipos.IMPRESORA -> "🖨️"
        else -> "💻"
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(icono, modifier = Modifier.padding(end = 8.dp))
        Column(Modifier.weight(1f)) {
            Text(e.serial, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            val detalle = buildList {
                if (e.modelo.isNotBlank() && e.modelo != e.tipo) add(e.modelo)
                if (e.sinHardware) add("sin escaneo de hardware")
            }.joinToString(" · ")
            if (detalle.isNotEmpty()) Text(detalle, style = MaterialTheme.typography.bodySmall)
        }
        if (e.tipo == Tipos.NOTEBOOK) {
            Text(
                e.snTransf?.let { "🔌 $it" } ?: "🔌 —",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
