package cl.arrienda.lector.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import cl.arrienda.lector.data.Tipos

@Composable
fun AppLector(vm: LectorViewModel) {
    val estado by vm.estado.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val feedback = remember { Feedback(context.applicationContext) }
    DisposableEffect(Unit) { onDispose { feedback.liberar() } }
    LaunchedEffect(Unit) { vm.senales.collect { feedback.dar(it) } }

    when (estado.pantalla) {
        Pantalla.CARGANDO -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        Pantalla.EMPAREJAR -> ConPermisoCamara { PantallaEmparejar(estado, vm) }
        Pantalla.LOTES -> PantallaLotes(estado, vm)
        Pantalla.NUEVO_LOTE -> {
            BackHandler { vm.cargarLotes() }
            PantallaNuevoLote(estado, vm)
        }
        Pantalla.ESCANEAR -> {
            BackHandler { vm.volverALotes() }
            ConPermisoCamara { PantallaEscaneo(estado, vm) }
        }
        // Su propio BackHandler: pregunta antes de perder cambios sin guardar.
        Pantalla.EQUIPO -> PantallaEquipo(estado, vm)
    }

    estado.pregunta?.let { DialogoPregunta(it, vm) }
}

/** Pide el permiso de cámara antes de mostrar [content]. */
@Composable
fun ConPermisoCamara(content: @Composable () -> Unit) {
    val context = LocalContext.current
    var concedido by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val pedir = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        concedido = it
    }
    LaunchedEffect(Unit) { if (!concedido) pedir.launch(Manifest.permission.CAMERA) }

    if (concedido) {
        content()
    } else {
        Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "El lector necesita la cámara para leer los códigos.",
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
            )
            Button(onClick = { pedir.launch(Manifest.permission.CAMERA) }, Modifier.padding(top = 16.dp)) {
                Text("Permitir cámara")
            }
        }
    }
}

@Composable
private fun DialogoPregunta(p: Pregunta, vm: LectorViewModel) {
    when (p) {
        is Pregunta.Elegir -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("¿Cuál es el serial?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("La etiqueta tiene varios códigos que podrían serlo.")
                    p.candidatos.forEach { c ->
                        OutlinedButton(onClick = { vm.elegirCandidato(p, c) }, Modifier.fillMaxWidth()) { Text(c) }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = vm::cerrarPregunta) { Text("Ninguno") } },
        )
        is Pregunta.Forzar -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("Equipo en otro lote") },
            text = { Text("${p.serial} ya está registrado en ${p.otro}.\n\n¿Agregarlo igual a este lote?") },
            confirmButton = { TextButton(onClick = { vm.forzar(p) }) { Text("Agregar igual") } },
            dismissButton = { TextButton(onClick = vm::cerrarPregunta) { Text("No") } },
        )
        is Pregunta.OtroTipo -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("¿Seguro que es ${p.esperado.lowercase()}?") },
            text = { Text("${p.valor} tiene forma de ${p.tipo.lowercase()}, según las reglas del PC.") },
            confirmButton = {
                TextButton(onClick = { vm.usarComo(p.base, p.valor, p.esperado) }) { Text("Sí, es ${p.esperado.lowercase()}") }
            },
            dismissButton = { TextButton(onClick = vm::cerrarPregunta) { Text("Cancelar") } },
        )
        is Pregunta.SinTipo -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("¿Qué es ${p.valor}?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Tipos.TODOS.forEach { t ->
                        OutlinedButton(onClick = { vm.usarComo(p.base, p.valor, t) }, Modifier.fillMaxWidth()) { Text(t) }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = vm::cerrarPregunta) { Text("Cancelar") } },
        )
        is Pregunta.SalirSinGuardar -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("Cargadores sin guardar") },
            text = { Text("Hay ${p.cantidad} cargador(es) en la lista que NO están en el PC.\n\nSi salís se pierden.") },
            confirmButton = { TextButton(onClick = vm::cerrarPregunta) { Text("Quedarme y guardar") } },
            dismissButton = { TextButton(onClick = vm::salirALotes) { Text("Salir sin guardar") } },
        )
        is Pregunta.Reabrir -> AlertDialog(
            onDismissRequest = vm::cerrarPregunta,
            title = { Text("Lote cerrado") },
            text = { Text(p.mensaje) },
            confirmButton = { TextButton(onClick = { vm.reabrir(p) }) { Text("Reabrir") } },
            dismissButton = { TextButton(onClick = vm::cerrarPregunta) { Text("No") } },
        )
    }
}
