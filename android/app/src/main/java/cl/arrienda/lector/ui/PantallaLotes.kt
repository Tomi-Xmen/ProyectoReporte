package cl.arrienda.lector.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import cl.arrienda.lector.data.Movimientos
import cl.arrienda.lector.data.PedidoNuevoLote

@Composable
fun PantallaLotes(estado: EstadoUi, vm: LectorViewModel) {
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("OT y guías abiertas", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.cargarLotes() }, enabled = !estado.ocupado) { Text("Actualizar") }
        }
        estado.mensaje?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (estado.pendientes.isNotEmpty()) {
            Text("📵 ${estado.pendientes.size} escaneo(s) sin enviar: se reintentan desde el lote.")
        }

        Button(onClick = vm::irANuevoLote, Modifier.fillMaxWidth(), enabled = !estado.ocupado) {
            Text("➕ Nueva OT / guía")
        }

        if (estado.lotes.isEmpty() && !estado.ocupado) {
            Text("No hay lotes abiertos en el PC.", style = MaterialTheme.typography.bodyMedium)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
            items(estado.lotes, key = { "${it.mov}/${it.cliente}/${it.numero}" }) { l ->
                Card(
                    Modifier.fillMaxWidth().clickable(enabled = !estado.ocupado) { vm.elegirLote(l) },
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(l.etiqueta, fontWeight = FontWeight.Bold)
                        val sec = if (l.numeroSec.isNotBlank()) {
                            if (l.mov == Movimientos.ENTREGA) " · Guía ${l.numeroSec}" else " · OT ${l.numeroSec}"
                        } else ""
                        Text("${l.equipos} equipo(s)$sec", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }

        TextButton(onClick = { vm.desemparejar() }, Modifier.align(Alignment.CenterHorizontally)) {
            Text("Desemparejar este celular")
        }
    }
}

/**
 * Mismos campos que "Nueva OT" del PC. El número se normaliza allá con las
 * mismas reglas ("OT 553" y "553" son la misma carpeta), así que acá no se
 * corrige nada: se muestra lo que respondió el PC.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PantallaNuevoLote(estado: EstadoUi, vm: LectorViewModel) {
    var mov by rememberSaveable { mutableStateOf(Movimientos.ENTREGA) }
    var cliente by rememberSaveable { mutableStateOf("") }
    var numero by rememberSaveable { mutableStateOf("") }
    var numeroSec by rememberSaveable { mutableStateOf("") }
    val esEntrega = mov == Movimientos.ENTREGA

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Nueva OT / guía", style = MaterialTheme.typography.headlineSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(Movimientos.ENTREGA, Movimientos.RETIRO).forEach { m ->
                FilterChip(selected = mov == m, onClick = { mov = m }, label = { Text(m) })
            }
        }
        OutlinedTextField(
            value = cliente,
            onValueChange = { cliente = it },
            label = { Text("Cliente") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        val sugerencias = estado.clientes
            .filter { cliente.isNotBlank() && it.contains(cliente.trim().replace(' ', '_'), ignoreCase = true) && it != cliente }
            .take(6)
        if (sugerencias.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                sugerencias.forEach { c -> AssistChip(onClick = { cliente = c }, label = { Text(c.replace('_', ' ')) }) }
            }
        }
        OutlinedTextField(
            value = numero,
            onValueChange = { numero = it },
            label = { Text(if (esEntrega) "N° de OT" else "N° de guía de retiro") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = numeroSec,
            onValueChange = { numeroSec = it },
            label = { Text(if (esEntrega) "N° de guía (opcional)" else "N° de OT (opcional)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        estado.mensaje?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(
            onClick = { vm.crearLote(PedidoNuevoLote(mov, cliente, numero, numeroSec)) },
            enabled = !estado.ocupado && cliente.isNotBlank() && numero.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Crear y escanear") }
        TextButton(onClick = { vm.cargarLotes() }, Modifier.align(Alignment.CenterHorizontally)) { Text("Volver") }
    }
}
