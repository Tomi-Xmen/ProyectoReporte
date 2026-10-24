package cl.arrienda.lector.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import cl.arrienda.lector.data.CambiosEquipo
import cl.arrienda.lector.data.Componente
import cl.arrienda.lector.data.DatosEquipo
import cl.arrienda.lector.data.Disco
import cl.arrienda.lector.data.FichaEquipo
import cl.arrienda.lector.data.HardwareEquipo
import cl.arrienda.lector.data.Tipos

/**
 * Ficha de un equipo del lote, toda editable menos el serial. Guardar
 * reescribe su JSON en el PC, que rearma el HTML del lote (las filas de
 * hardware, con el mismo formato que el escaneo): lo que se ve acá es lo que
 * va al reporte.
 */
@Composable
fun PantallaEquipo(estado: EstadoUi, vm: LectorViewModel) {
    val ficha = estado.ficha ?: return
    // Se reinicia al cargar otra versión (guardado o recarga tras un 409).
    var datos by remember(ficha.version) { mutableStateOf(ficha.datos) }
    var componentes by remember(ficha.version) { mutableStateOf(ficha.componentes) }
    var hardware by remember(ficha.version) { mutableStateOf(ficha.hardware) }
    var confirmarSalida by remember { mutableStateOf(false) }
    var elegirDestino by remember { mutableStateOf(false) }
    var confirmarQuitar by remember { mutableStateOf(false) }
    val sinGuardar = !CambiosEquipo.entre(ficha, datos, componentes, hardware).vacio

    BackHandler { if (sinGuardar) confirmarSalida = true else vm.cerrarEquipo() }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { if (sinGuardar) confirmarSalida = true else vm.cerrarEquipo() }) { Text("‹ Lote") }
            Column(Modifier.weight(1f)) {
                Text(ficha.serial, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                Text(ficha.tipo, style = MaterialTheme.typography.bodySmall)
            }
            if (ficha.tieneFallas) Etiqueta("CON FALLAS", Color(0xFFFCA5A5))
        }

        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                AccionesEquipo(
                    esNotebook = ficha.tipo == Tipos.NOTEBOOK,
                    sinGuardar = sinGuardar,
                    habilitadas = !sinGuardar && !estado.ocupado,
                    escanearCargador = { vm.escanearCargadorPara(ficha.serial) },
                    mover = {
                        vm.pedirLotesDestino()
                        elegirDestino = true
                    },
                    quitar = { confirmarQuitar = true },
                )
            }
            item {
                Seccion("Hardware")
                val nota = if (ficha.sinHardware) "Leído solo por su código: sin escaneo de hardware. Podés cargarlo a mano."
                else "Escaneado ${ficha.fecha}"
                Text(nota, style = MaterialTheme.typography.bodySmall)
            }
            item { CamposHardware(hardware) { hardware = it } }

            item { Seccion("Datos del reporte") }
            item { CamposDatos(ficha, datos) { datos = it } }

            item {
                Seccion("Revisión de componentes")
                if (!ficha.revisado) {
                    Text(
                        "Sin revisión cargada. Se guarda solo si marcás algo.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            itemsIndexed(componentes) { i, c ->
                FilaComponente(c, ficha.opciones.estados) { nuevo ->
                    componentes = componentes.toMutableList().also { it[i] = nuevo }
                }
            }
        }

        estado.mensaje?.let { Text(it, modifier = Modifier.padding(vertical = 6.dp)) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(
                onClick = {
                    datos = ficha.datos
                    componentes = ficha.componentes
                    hardware = ficha.hardware
                },
                enabled = sinGuardar && !estado.ocupado,
            ) { Text("Deshacer") }
            Button(
                onClick = { vm.guardarEquipo(datos, componentes, hardware) },
                enabled = sinGuardar && !estado.ocupado,
                modifier = Modifier.weight(1f),
            ) {
                if (estado.ocupado) CircularProgressIndicator(Modifier.padding(end = 8.dp).width(18.dp))
                Text("Guardar en el PC")
            }
        }
    }

    if (confirmarSalida) {
        AlertDialog(
            onDismissRequest = { confirmarSalida = false },
            title = { Text("Cambios sin guardar") },
            text = { Text("Si salís ahora se pierden los cambios de esta ficha.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmarSalida = false
                    vm.cerrarEquipo()
                }) { Text("Salir sin guardar") }
            },
            dismissButton = { TextButton(onClick = { confirmarSalida = false }) { Text("Seguir editando") } },
        )
    }

    if (elegirDestino) {
        val actual = estado.lote?.ref
        val destinos = estado.lotes.filter { it.ref != actual }
        AlertDialog(
            onDismissRequest = { elegirDestino = false },
            title = { Text("Mover ${ficha.serial} a…") },
            text = {
                // Column con scroll: el AlertDialog no admite listas perezosas.
                Column(
                    Modifier.heightIn(max = 380.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        "Se lleva todo lo cargado (cargador, observaciones, revisión).",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    if (destinos.isEmpty()) Text("No hay otros lotes abiertos. Creá uno desde la lista de lotes.")
                    destinos.forEach { l ->
                        OutlinedButton(
                            onClick = {
                                elegirDestino = false
                                vm.moverEquipo(l.ref)
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(Modifier.fillMaxWidth()) {
                                Text(l.etiqueta, fontWeight = FontWeight.Bold)
                                Text("${l.equipos} equipo(s)", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { elegirDestino = false }) { Text("Cancelar") } },
        )
    }

    if (confirmarQuitar) {
        AlertDialog(
            onDismissRequest = { confirmarQuitar = false },
            title = { Text("¿Quitar ${ficha.serial} del lote?") },
            text = {
                Text(
                    "Sale del reporte y del FUSIONADO. No se borra: queda en la papelera " +
                        "del PC (Reportes_Guardados/_PAPELERA) por si hay que recuperarlo.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmarQuitar = false
                    vm.quitarEquipo()
                }) { Text("Quitar") }
            },
            dismissButton = { TextButton(onClick = { confirmarQuitar = false }) { Text("Cancelar") } },
        )
    }
}

/** Lo que se hace con el equipo entero. Con cambios sin guardar se bloquea: primero guardar. */
@Composable
private fun AccionesEquipo(
    esNotebook: Boolean,
    sinGuardar: Boolean,
    habilitadas: Boolean,
    escanearCargador: () -> Unit,
    mover: () -> Unit,
    quitar: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (esNotebook) {
                OutlinedButton(onClick = escanearCargador, enabled = habilitadas) { Text("🔌 Escanear cargador") }
            }
            OutlinedButton(onClick = mover, enabled = habilitadas) { Text("↔️ Mover") }
            OutlinedButton(onClick = quitar, enabled = habilitadas) { Text("🗑️ Quitar") }
        }
        if (sinGuardar) {
            Text("Guardá o deshacé los cambios para usar estas acciones.", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun CamposDatos(ficha: FichaEquipo, datos: DatosEquipo, cambiar: (DatosEquipo) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Campo("Modelo", datos.modelo) { cambiar(datos.copy(modelo = it)) }
        Campo("Licencia de Windows", datos.snWin, monoespaciada = true) { cambiar(datos.copy(snWin = it)) }
        Campo("Serie del transformador", datos.snTransf, monoespaciada = true) { cambiar(datos.copy(snTransf = it)) }
        if (datos.snTransf.isNotBlank()) {
            TextButton(onClick = { cambiar(datos.copy(snTransf = "")) }) { Text("✕ Dejar sin cargador (después Guardar)") }
        }

        Text("Office", style = MaterialTheme.typography.labelMedium)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(
                selected = datos.office.isBlank(),
                onClick = { cambiar(datos.copy(office = "")) },
                label = { Text("No") },
            )
            ficha.opciones.office.forEach { v ->
                val valor = "Office $v"
                FilterChip(
                    selected = datos.office == valor,
                    onClick = { cambiar(datos.copy(office = valor)) },
                    label = { Text(v) },
                )
            }
        }
        if (datos.office.isNotBlank() || datos.snApp.isNotBlank()) {
            Campo("Key de Office", datos.snApp, monoespaciada = true) { cambiar(datos.copy(snApp = it)) }
        }
        Campo("Observaciones", datos.obs, unaLinea = false) { cambiar(datos.copy(obs = it)) }
    }
}

@Composable
private fun FilaComponente(c: Componente, estados: List<String>, cambiar: (Componente) -> Unit) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(c.nombre, modifier = Modifier.weight(1f))
            estados.forEach { e ->
                FilterChip(
                    selected = c.estado == e,
                    // Como en el PC: volver a OK borra la observación.
                    onClick = { cambiar(c.copy(estado = e, obs = if (e == "OK") "" else c.obs)) },
                    label = { Text(e) },
                    modifier = Modifier.padding(start = 4.dp),
                )
            }
        }
        if (c.estado != "OK") {
            Campo("Qué tiene", c.obs) { cambiar(c.copy(obs = it)) }
        }
    }
}

@Composable
private fun Campo(
    etiqueta: String,
    valor: String,
    monoespaciada: Boolean = false,
    unaLinea: Boolean = true,
    cambiar: (String) -> Unit,
) {
    OutlinedTextField(
        value = valor,
        onValueChange = cambiar,
        label = { Text(etiqueta) },
        singleLine = unaLinea,
        minLines = if (unaLinea) 1 else 2,
        textStyle = if (monoespaciada) MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace)
        else MaterialTheme.typography.bodyLarge,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Seccion(titulo: String) {
    Column(Modifier.padding(top = 8.dp)) {
        Text(titulo.uppercase(), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
        HorizontalDivider(Modifier.padding(top = 2.dp))
    }
}

@Composable
private fun CamposHardware(hw: HardwareEquipo, cambiar: (HardwareEquipo) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Campo("Equipo (host)", hw.host) { cambiar(hw.copy(host = it)) }
        Campo("CPU", hw.cpu) { cambiar(hw.copy(cpu = it)) }
        Campo("Batería", hw.bateria) { cambiar(hw.copy(bateria = it)) }

        Subtitulo("Memoria RAM", "+ Módulo") { cambiar(hw.copy(ram = hw.ram + "")) }
        hw.ram.forEachIndexed { i, modulo ->
            ConQuitar({ cambiar(hw.copy(ram = hw.ram.sinElemento(i))) }) {
                Campo("Módulo ${i + 1} · GB | MHz | tipo | marca | P/N", modulo, monoespaciada = true) { nuevo ->
                    cambiar(hw.copy(ram = hw.ram.conElemento(i, nuevo)))
                }
            }
        }

        Subtitulo("Discos", "+ Disco") { cambiar(hw.copy(discos = hw.discos + Disco())) }
        hw.discos.forEachIndexed { i, d ->
            ConQuitar({ cambiar(hw.copy(discos = hw.discos.sinElemento(i))) }) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Campo("Disco ${i + 1} · descripción", d.desc) { nuevo ->
                        cambiar(hw.copy(discos = hw.discos.conElemento(i, d.copy(desc = nuevo))))
                    }
                    Campo("Serie del disco", d.serial, monoespaciada = true) { nuevo ->
                        cambiar(hw.copy(discos = hw.discos.conElemento(i, d.copy(serial = nuevo))))
                    }
                }
            }
        }

        Subtitulo("Red", "+ Adaptador") { cambiar(hw.copy(red = hw.red + "")) }
        hw.red.forEachIndexed { i, adaptador ->
            ConQuitar({ cambiar(hw.copy(red = hw.red.sinElemento(i))) }) {
                Campo("Adaptador ${i + 1}", adaptador) { nuevo -> cambiar(hw.copy(red = hw.red.conElemento(i, nuevo))) }
            }
        }
    }
}

private fun <T> List<T>.sinElemento(i: Int) = filterIndexed { j, _ -> j != i }

private fun <T> List<T>.conElemento(i: Int, valor: T) = toMutableList().also { it[i] = valor }

@Composable
private fun Subtitulo(texto: String, agregar: String, alAgregar: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(texto, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
        TextButton(onClick = alAgregar) { Text(agregar) }
    }
}

@Composable
private fun ConQuitar(quitar: () -> Unit, contenido: @Composable () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { contenido() }
        TextButton(onClick = quitar) { Text("✕") }
    }
}

@Composable
private fun Etiqueta(texto: String, fondo: Color) {
    Text(
        texto,
        color = Color(0xFF111827),
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(fondo).padding(horizontal = 8.dp, vertical = 4.dp),
    )
}
