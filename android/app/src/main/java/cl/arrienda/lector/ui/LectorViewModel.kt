package cl.arrienda.lector.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import cl.arrienda.lector.data.AlmacenEmparejamiento
import cl.arrienda.lector.data.CambiosEquipo
import cl.arrienda.lector.data.Componente
import cl.arrienda.lector.data.DatosEquipo
import cl.arrienda.lector.data.ApiPc
import cl.arrienda.lector.data.Emparejamiento
import cl.arrienda.lector.data.EstadoLote
import cl.arrienda.lector.data.FichaEquipo
import cl.arrienda.lector.data.HardwareEquipo
import cl.arrienda.lector.data.Lectura
import cl.arrienda.lector.data.LoteAbierto
import cl.arrienda.lector.data.LoteRef
import cl.arrienda.lector.data.ParCargador
import cl.arrienda.lector.data.PedidoCargadores
import cl.arrienda.lector.data.Movimientos
import cl.arrienda.lector.data.PedidoEditar
import cl.arrienda.lector.data.PedidoEscaneo
import cl.arrienda.lector.data.PedidoMover
import cl.arrienda.lector.data.PedidoNuevoLote
import cl.arrienda.lector.data.RespuestaEscaneo
import cl.arrienda.lector.data.Resultado
import cl.arrienda.lector.data.ResumenCierre
import cl.arrienda.lector.data.Tipos
import cl.arrienda.lector.escaneo.Estabilizador
import cl.arrienda.lector.escaneo.Flujo
import cl.arrienda.lector.escaneo.Modo
import cl.arrienda.lector.escaneo.Nivel
import cl.arrienda.lector.escaneo.Reenvio
import cl.arrienda.lector.escaneo.describir
import cl.arrienda.lector.escaneo.nivel
import cl.arrienda.lector.escaneo.proximoSinCargador
import cl.arrienda.lector.escaneo.reenvio
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

enum class Pantalla { CARGANDO, EMPAREJAR, LOTES, NUEVO_LOTE, ESCANEAR, EQUIPO }

data class Aviso(val texto: String, val nivel: Nivel)

/** Decisiones que el PC devuelve al usuario. Cada una guarda el pedido original para reenviarlo. */
sealed interface Pregunta {
    data class Elegir(val candidatos: List<String>, val base: PedidoEscaneo) : Pregunta
    data class Forzar(val serial: String, val otro: String, val base: PedidoEscaneo) : Pregunta
    data class OtroTipo(val valor: String, val tipo: String, val esperado: String, val base: PedidoEscaneo) : Pregunta
    data class SinTipo(val valor: String, val base: PedidoEscaneo) : Pregunta
    data class Reabrir(val mensaje: String, val pedido: PedidoNuevoLote) : Pregunta
    data class SalirSinGuardar(val cantidad: Int) : Pregunta

    /** Cargador leído: el usuario toca a qué notebook va. [portador] es el que lo tiene hoy. */
    data class ElegirEquipo(val snTransf: String, val portador: String?, val base: PedidoEscaneo) : Pregunta

    data class Cerrar(val resumen: ResumenCierre) : Pregunta
}

data class EstadoUi(
    val pantalla: Pantalla = Pantalla.CARGANDO,
    val hayEmparejamientoGuardado: Boolean = false,
    val lotes: List<LoteAbierto> = emptyList(),
    val clientes: List<String> = emptyList(),
    val lote: EstadoLote? = null,
    /** El equipo abierto en la pantalla EQUIPO. */
    val ficha: FichaEquipo? = null,
    val flujo: Flujo = Flujo(),
    val aviso: Aviso? = null,
    val pregunta: Pregunta? = null,
    val ocupado: Boolean = false,
    /** Cargadores leídos y emparejados que todavía NO están en el PC: se guardan con el botón. */
    val borrador: List<ParCargador> = emptyList(),
    /** Por qué el PC rechazó cada cargador de la lista (clave: serial del cargador). */
    val erroresBorrador: Map<String, String> = emptyMap(),
    /** Escaneos que no llegaron al PC; se reenvían con su mismo id. */
    val pendientes: List<PedidoEscaneo> = emptyList(),
    /** Mensaje para las pantallas fuera del escaneo (errores de conexión, validación). */
    val mensaje: String? = null,
)

class LectorViewModel(app: Application) : AndroidViewModel(app) {
    private val almacen = AlmacenEmparejamiento(app)
    private var api: ApiPc? = null
    private var guardado: Emparejamiento? = null

    private val _estado = MutableStateFlow(EstadoUi())
    val estado: StateFlow<EstadoUi> = _estado.asStateFlow()

    /** Un evento por respuesta: la pantalla lo convierte en sonido + vibración. */
    private val _senales = MutableSharedFlow<Nivel>(extraBufferCapacity = 8)
    val senales: SharedFlow<Nivel> = _senales

    val estabilizador = Estabilizador()

    /** Refresca el lote mientras se escanea: los notebooks llegan desde el PC. */
    private var refresco: Job? = null

    /** Con un PC ya emparejado que no responde, se reintenta solo hasta que vuelva. */
    private var reconexion: Job? = null

    init {
        viewModelScope.launch {
            guardado = almacen.leer()
            val e = guardado
            if (e == null) ir(Pantalla.EMPAREJAR) else conectar(e, guardar = false)
        }
    }

    private fun actualizar(f: (EstadoUi) -> EstadoUi) = _estado.update(f)

    private fun ir(p: Pantalla, mensaje: String? = null) = actualizar {
        it.copy(pantalla = p, mensaje = mensaje, ocupado = false, hayEmparejamientoGuardado = guardado != null)
    }

    private fun senal(n: Nivel) {
        _senales.tryEmit(n)
    }

    // ── Emparejamiento ───────────────────────────────────
    fun alLeerQr(lecturas: List<Lectura>) {
        if (estado.value.ocupado) return
        val e = lecturas.firstNotNullOfOrNull { Emparejamiento.desdeQr(it.texto) }
        if (e == null) {
            senal(Nivel.ERROR)
            actualizar { it.copy(mensaje = "Ese no es el QR del panel \"Lector celular\" del PC.") }
            return
        }
        viewModelScope.launch { conectar(e, guardar = true) }
    }

    fun reintentarConexion() {
        guardado?.let { e -> viewModelScope.launch { conectar(e, guardar = false) } }
    }

    private suspend fun conectar(e: Emparejamiento, guardar: Boolean) {
        val nueva = ApiPc(e)
        actualizar { it.copy(ocupado = true, mensaje = "Conectando con el PC…") }
        when (val r = nueva.estado()) {
            is Resultado.Ok -> {
                api = nueva
                if (guardar) {
                    almacen.guardar(e)
                    guardado = e
                }
                senal(Nivel.OK)
                cargarLotes()
            }
            is Resultado.Rechazado -> desemparejar(
                if (r.codigo == 401) "El PC cambió el código: escaneá el QR de nuevo."
                else r.error.mensaje,
            )
            is Resultado.SinConexion -> {
                ir(
                    Pantalla.EMPAREJAR,
                    "No se encontró el PC: reintentando solo… Revisá que el lector " +
                        "esté encendido en el PC y que el celular esté en el mismo Wi-Fi.",
                )
                reconectarSolo()
            }
        }
    }

    private fun reconectarSolo() {
        if (reconexion?.isActive == true) return
        reconexion = viewModelScope.launch {
            while (true) {
                delay(RECONEXION_MS)
                val e = guardado ?: break
                val s = estado.value
                if (api != null || s.pantalla != Pantalla.EMPAREJAR) break
                if (s.ocupado) continue
                if (ApiPc(e).estado() is Resultado.Ok) {
                    conectar(e, guardar = false)
                    break
                }
            }
        }
    }

    fun desemparejar(mensaje: String? = null) {
        viewModelScope.launch {
            almacen.borrar()
            guardado = null
            api = null
            actualizar { EstadoUi(pantalla = Pantalla.EMPAREJAR, mensaje = mensaje, pendientes = it.pendientes) }
        }
    }

    /** 401 → desemparejar; lo demás queda como mensaje. Devuelve el texto mostrado. */
    private fun falla(r: Resultado<*>): String {
        val texto = when (r) {
            is Resultado.Rechazado ->
                if (r.codigo == 401) {
                    desemparejar("El PC cambió el código: escaneá el QR de nuevo.")
                    return ""
                } else {
                    r.error.mensaje.ifBlank { "El PC respondió ${r.codigo}." }
                }
            is Resultado.SinConexion -> "📵 Sin conexión con el PC."
            is Resultado.Ok -> ""
        }
        actualizar { it.copy(ocupado = false, mensaje = texto) }
        return texto
    }

    // ── Lotes ────────────────────────────────────────────
    /** [aviso]: algo que salió bien y se cuenta en la lista (p. ej. "lote cerrado"). */
    fun cargarLotes(mensaje: String? = null, aviso: Aviso? = null) {
        val api = api ?: return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            when (val r = api.lotes()) {
                is Resultado.Ok -> actualizar {
                    it.copy(
                        pantalla = Pantalla.LOTES, lotes = r.valor, lote = null, ocupado = false,
                        mensaje = mensaje, aviso = aviso,
                    )
                }
                else -> {
                    falla(r)
                    if (estado.value.pantalla == Pantalla.CARGANDO) ir(Pantalla.LOTES, estado.value.mensaje)
                }
            }
        }
    }

    fun elegirLote(l: LoteAbierto) = abrirLote(l.ref)

    private fun abrirLote(ref: LoteRef) {
        val api = api ?: return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            when (val r = api.estadoLote(ref)) {
                is Resultado.Ok -> entrarAEscanear(r.valor)
                else -> falla(r)
            }
        }
    }

    private fun entrarAEscanear(lote: EstadoLote) {
        estabilizador.olvidar()
        refrescarSeguido()
        actualizar {
            it.copy(
                pantalla = Pantalla.ESCANEAR, lote = lote, flujo = Flujo(), aviso = null,
                pregunta = null, ocupado = false, mensaje = null,
                borrador = emptyList(), erroresBorrador = emptyMap(),
            )
        }
    }

    fun irANuevoLote() {
        val api = api ?: return
        viewModelScope.launch {
            val clientes = (api.clientes() as? Resultado.Ok)?.valor.orEmpty()
            actualizar { it.copy(pantalla = Pantalla.NUEVO_LOTE, clientes = clientes, mensaje = null) }
        }
    }

    fun crearLote(pedido: PedidoNuevoLote) {
        val api = api ?: return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, pregunta = null, mensaje = null) }
            when (val r = api.crearLote(pedido)) {
                is Resultado.Ok -> entrarAEscanear(r.valor)
                is Resultado.Rechazado ->
                    if (r.codigo == 409 && r.error.error == "cerrado") {
                        actualizar { it.copy(ocupado = false, pregunta = Pregunta.Reabrir(r.error.mensaje, pedido)) }
                    } else {
                        falla(r)
                    }
                is Resultado.SinConexion -> falla(r)
            }
        }
    }

    fun volverALotes() {
        val pendientes = estado.value.borrador.size
        if (pendientes > 0) {
            actualizar { it.copy(pregunta = Pregunta.SalirSinGuardar(pendientes)) }
            return
        }
        salirALotes()
    }

    /** Sale del lote aunque queden cargadores sin guardar (se pierden). */
    fun salirALotes() {
        estabilizador.olvidar()
        actualizar { it.copy(pregunta = null, borrador = emptyList(), erroresBorrador = emptyMap()) }
        cargarLotes()
    }

    // ── Escaneo ──────────────────────────────────────────
    fun alLeer(lecturas: List<Lectura>) {
        val s = estado.value
        val lote = s.lote ?: return
        if (s.ocupado || s.pregunta != null || lecturas.isEmpty()) return
        enviar(
            PedidoEscaneo(
                id = nuevoId(),
                lote = lote.ref,
                lecturas = lecturas,
                esperado = s.flujo.esperado,
                borrador = s.flujo.aLaLista.takeIf { it },
                soloLeer = s.flujo.soloLeer.takeIf { it },
            ),
        )
    }

    fun ingresarManual(texto: String) {
        if (texto.isNotBlank()) alLeer(listOf(Lectura(texto.trim(), "MANUAL")))
    }

    /**
     * Pedidos de escaneo en curso. Una respuesta puede disparar otro pedido
     * (el cargador para un equipo elegido desde la ficha): "ocupado" se apaga
     * recién cuando no queda ninguno, si no la cámara volvería a leer en medio.
     */
    private var enVuelo = 0

    private fun enviar(p: PedidoEscaneo) {
        val api = api ?: return
        viewModelScope.launch {
            enVuelo++
            actualizar { it.copy(ocupado = true, pregunta = null) }
            when (val r = api.escanear(p)) {
                is Resultado.Ok -> procesar(p, r.valor)
                is Resultado.SinConexion -> {
                    senal(Nivel.ERROR)
                    actualizar {
                        val pendientes = it.pendientes + p
                        it.copy(
                            pendientes = pendientes,
                            aviso = Aviso("📵 Sin conexión con el PC: quedó pendiente (${pendientes.size}).", Nivel.ERROR),
                        )
                    }
                }
                is Resultado.Rechazado -> {
                    senal(Nivel.ERROR)
                    when (r.codigo) {
                        401 -> desemparejar("El PC cambió el código: escaneá el QR de nuevo.")
                        // El lote se cerró o desapareció en el PC: no tiene sentido seguir en él.
                        404, 409 -> cargarLotes(r.error.mensaje)
                        else -> actualizar { it.copy(aviso = Aviso("❌ ${r.error.mensaje}", Nivel.ERROR)) }
                    }
                }
            }
            enVuelo--
            if (enVuelo == 0) actualizar { it.copy(ocupado = false) }
        }
    }

    private fun procesar(p: PedidoEscaneo, r: RespuestaEscaneo) {
        if (r.estado == "propuesto") {
            agregarAlBorrador(r.snTransf.orEmpty())
            return
        }
        if (r.estado == "leido") {
            alLeerCargador(p, r)
            return
        }
        val pregunta = when (r.estado) {
            "elegir" -> Pregunta.Elegir(r.candidatos, p)
            "en_otra_ot" -> Pregunta.Forzar(r.serial.orEmpty(), r.otro.orEmpty(), p)
            "otro_tipo" -> Pregunta.OtroTipo(r.valor.orEmpty(), r.tipo.orEmpty(), r.esperado.orEmpty(), p)
            "sin_tipo" -> Pregunta.SinTipo(r.valor.orEmpty(), p)
            else -> null
        }
        senal(nivel(r))
        actualizar {
            it.copy(flujo = it.flujo.trasRespuesta(r), aviso = Aviso(describir(r), nivel(r)), pregunta = pregunta)
        }
        // Asignado directo (elegir equipo, o desde la ficha): ese par ya no va en la lista.
        if (r.estado == "asignado") {
            r.equipo?.let(::sacarDelBorrador)
            r.snTransf?.let { sn -> actualizar { s -> s.copy(borrador = s.borrador.filterNot { it.snTransf.equals(sn, ignoreCase = true) }) } }
        }
        if (r.estado in CAMBIAN_EL_LOTE) refrescarLote()
    }

    // ── Lista de cargadores ──────────────────────────────
    private fun agregarAlBorrador(sn: String) {
        val aviso = sumarAlBorrador(sn)
        senal(aviso.nivel)
        actualizar { it.copy(aviso = aviso) }
    }

    /** Empareja el cargador con el próximo notebook sin cargador y lo suma a la lista. */
    private fun sumarAlBorrador(sn: String): Aviso {
        val s = estado.value
        val destino = proximoSinCargador(s.lote, s.borrador)
        val (aviso, borrador) = when {
            s.borrador.any { it.snTransf.equals(sn, ignoreCase = true) } ->
                Aviso("☑️ $sn ya está en la lista", Nivel.AVISO) to s.borrador
            destino == null ->
                Aviso("⚠️ No quedan notebooks sin cargador para $sn", Nivel.ERROR) to s.borrador
            else ->
                Aviso("🔌 $sn → $destino (falta guardar)", Nivel.OK) to s.borrador + ParCargador(destino, sn)
        }
        actualizar { it.copy(borrador = borrador) }
        return aviso
    }

    /** Quita uno de la lista; los que venían después NO se corren: cada uno ya tiene su equipo. */
    fun quitarDelBorrador(par: ParCargador) = actualizar {
        it.copy(borrador = it.borrador - par, erroresBorrador = it.erroresBorrador - par.snTransf)
    }

    /** El equipo se fue del lote o ya tiene cargador en el PC: su par de la lista sobra. */
    private fun sacarDelBorrador(serial: String) = actualizar { s ->
        val sobran = s.borrador.filter { it.serial.equals(serial, ignoreCase = true) }
        s.copy(borrador = s.borrador - sobran.toSet(), erroresBorrador = s.erroresBorrador - sobran.map { it.snTransf }.toSet())
    }

    fun descartarBorrador() = actualizar {
        it.copy(borrador = emptyList(), erroresBorrador = emptyMap(), aviso = Aviso("Lista descartada: no se guardó nada.", Nivel.AVISO))
    }

    fun guardarBorrador() {
        val api = api ?: return
        val s = estado.value
        val ref = s.lote?.ref ?: return
        val pares = s.borrador
        if (pares.isEmpty() || s.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, aviso = Aviso("💾 Guardando ${pares.size} cargador(es) en el PC…", Nivel.AVISO)) }
            when (val r = api.guardarCargadores(PedidoCargadores(ref, pares))) {
                is Resultado.Ok -> {
                    val v = r.valor
                    if (v.estado == "guardado") {
                        senal(Nivel.OK)
                        actualizar {
                            it.copy(
                                ocupado = false,
                                borrador = it.borrador - pares.toSet(),
                                erroresBorrador = emptyMap(),
                                aviso = Aviso(
                                    "✅ Guardado y verificado en el PC: ${v.guardados.size} cargador(es) " +
                                        "en el JSON de cada equipo y en el FUSIONADO." +
                                        if (v.sinCargador > 0) " Faltan ${v.sinCargador} notebook(s)." else "",
                                    Nivel.OK,
                                ),
                            )
                        }
                        refrescarLote()
                    } else {
                        senal(Nivel.ERROR)
                        val porCargador = v.errores.mapNotNull { e -> e.snTransf?.let { it to e.motivo } }.toMap()
                        val titulo = if (v.estado == "rechazado") "❌ No se guardó NADA" else "❌ El PC no pudo confirmar el guardado"
                        actualizar {
                            it.copy(
                                ocupado = false,
                                erroresBorrador = porCargador,
                                aviso = Aviso(
                                    "$titulo: " + v.errores.joinToString(" · ") { e -> e.motivo } +
                                        " Corregí la lista y tocá Guardar de nuevo.",
                                    Nivel.ERROR,
                                ),
                            )
                        }
                    }
                }
                is Resultado.Rechazado -> {
                    senal(Nivel.ERROR)
                    if (r.codigo == 401) {
                        desemparejar("El PC cambió el código: escaneá el QR de nuevo.")
                    } else {
                        actualizar { it.copy(ocupado = false, aviso = Aviso("❌ No se guardó: ${r.error.mensaje}", Nivel.ERROR)) }
                    }
                }
                is Resultado.SinConexion -> {
                    senal(Nivel.ERROR)
                    actualizar {
                        it.copy(
                            ocupado = false,
                            aviso = Aviso("📵 Sin conexión: no se pudo confirmar. La lista sigue acá, tocá Guardar de nuevo.", Nivel.ERROR),
                        )
                    }
                }
            }
        }
    }

    private fun refrescarLote() {
        val api = api ?: return
        val ref = estado.value.lote?.ref ?: return
        viewModelScope.launch {
            (api.estadoLote(ref) as? Resultado.Ok)?.let { r ->
                actualizar { if (it.lote?.ref == ref) it.copy(lote = r.valor) else it }
            }
        }
    }

    // Respuestas a las preguntas: cada una es un escaneo NUEVO (id nuevo).
    fun elegirCandidato(p: Pregunta.Elegir, valor: String) =
        enviar(p.base.copy(id = nuevoId(), lecturas = listOf(Lectura(valor))))

    fun forzar(p: Pregunta.Forzar) =
        enviar(p.base.copy(id = nuevoId(), lecturas = listOf(Lectura(p.serial)), forzar = true))

    fun usarComo(base: PedidoEscaneo, valor: String, tipo: String) =
        enviar(base.copy(id = nuevoId(), lecturas = listOf(Lectura(valor)), tipo = tipo, esperado = tipo))

    fun reabrir(p: Pregunta.Reabrir) = crearLote(p.pedido.copy(reabrir = true))

    fun cerrarPregunta() = actualizar { it.copy(pregunta = null) }

    // ── Cargador: leerlo y elegir el equipo ──────────────
    /** El PC dijo qué cargador se leyó: va al equipo pedido desde la ficha, o se pregunta a cuál. */
    private fun alLeerCargador(p: PedidoEscaneo, r: RespuestaEscaneo) {
        val sn = r.snTransf ?: return
        val destino = estado.value.flujo.cargadorPara
        if (destino != null) {
            asignarCargador(p, sn, r.equipo, destino)
            return
        }
        senal(Nivel.PREGUNTA)
        actualizar { it.copy(aviso = Aviso(describir(r), Nivel.PREGUNTA), pregunta = Pregunta.ElegirEquipo(sn, r.equipo, p)) }
    }

    fun elegirEquipoParaCargador(p: Pregunta.ElegirEquipo, serial: String) =
        asignarCargador(p.base, p.snTransf, p.portador, serial)

    /** Si el cargador era de otro equipo, se le pasa a este (el PC se lo saca al anterior). */
    private fun asignarCargador(base: PedidoEscaneo, sn: String, portador: String?, destino: String) {
        if (portador != null && portador.equals(destino, ignoreCase = true)) {
            senal(Nivel.AVISO)
            actualizar {
                it.copy(
                    pregunta = null,
                    flujo = it.flujo.sinCargadorPara(),
                    aviso = Aviso("☑️ El cargador $sn ya era de $destino", Nivel.AVISO),
                )
            }
            return
        }
        enviar(
            base.copy(
                id = nuevoId(),
                lecturas = listOf(Lectura(sn)),
                tipo = Tipos.TRANSFORMADOR,
                esperado = Tipos.TRANSFORMADOR,
                serialEquipo = destino,
                soloLeer = null,
                reasignar = if (portador != null) true else null,
            ),
        )
    }

    /** Desde la ficha: volver a la cámara para leer el cargador de ese equipo. */
    fun escanearCargadorPara(serial: String) {
        estabilizador.olvidar()
        actualizar {
            it.copy(
                pantalla = Pantalla.ESCANEAR, ficha = null, mensaje = null, ocupado = false,
                flujo = it.flujo.paraCargadorDe(serial),
                aviso = Aviso("🔌 Escaneá el cargador para $serial", Nivel.AVISO),
            )
        }
        refrescarSeguido()
    }

    fun cancelarCargadorPara() = actualizar { it.copy(flujo = it.flujo.sinCargadorPara(), aviso = null) }

    /**
     * Reenvía los pendientes de a uno y EN ORDEN: la hora en que el PC los
     * registra es el orden de escaneo con que se emparejan los cargadores.
     * Se corta en el primero sin conexión (los demás esperan detrás) y en el
     * primero que pide una decisión, que se muestra como cualquier pregunta.
     * Lo que el PC rechazó se informa: nunca se da por enviado.
     */
    fun reintentarPendientes() {
        val api = api ?: return
        if (estado.value.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            val cola = estado.value.pendientes
            var hechos = 0
            var listos = 0
            val fallos = mutableListOf<String>()
            var pregunta: Pair<PedidoEscaneo, RespuestaEscaneo>? = null
            for (p in cola) {
                val r = api.escanear(p)
                if (r is Resultado.SinConexion) break
                hechos++
                if (r is Resultado.Rechazado) {
                    if (r.codigo == 401) {
                        desemparejar("El PC cambió el código: escaneá el QR de nuevo.")
                        return@launch
                    }
                    fallos += "${textoLeido(p)}: ${r.error.mensaje}"
                    continue
                }
                val v = (r as Resultado.Ok).valor
                when (reenvio(v)) {
                    Reenvio.LISTO -> listos++
                    Reenvio.A_LA_LISTA ->
                        if (p.lote != estado.value.lote?.ref) {
                            fallos += "${v.snTransf}: era de otro lote, volvé a leerlo ahí"
                        } else {
                            val a = sumarAlBorrador(v.snTransf.orEmpty())
                            if (a.nivel == Nivel.ERROR) fallos += a.texto else listos++
                        }
                    Reenvio.PREGUNTAR -> pregunta = p to v
                    Reenvio.FALLO -> fallos += describir(v)
                }
                if (pregunta != null) break
            }
            val quedan = cola.drop(hechos)
            actualizar { it.copy(pendientes = quedan, ocupado = false) }

            val partes = buildList {
                if (listos > 0) add("✅ $listos enviado(s)")
                if (fallos.isNotEmpty()) add("❌ ${fallos.size} NO entraron: " + fallos.joinToString(" · "))
                if (quedan.isNotEmpty()) add("📵 Siguen ${quedan.size} pendiente(s)")
            }
            val q = pregunta
            if (q != null) {
                // procesar muestra la pregunta; el resumen va detrás.
                procesar(q.first, q.second)
                actualizar { s -> s.copy(aviso = s.aviso?.let { it.copy(texto = (listOf(it.texto) + partes).joinToString(" · ")) }) }
            } else {
                val nivel = if (fallos.isEmpty() && quedan.isEmpty()) Nivel.OK else Nivel.ERROR
                senal(nivel)
                actualizar { it.copy(aviso = Aviso(partes.joinToString(" · ").ifEmpty { "Nada para enviar." }, nivel)) }
            }
            if (listos > 0) refrescarLote()
        }
    }

    private fun textoLeido(p: PedidoEscaneo) = p.lecturas.firstOrNull()?.texto ?: "?"

    // ── Ficha del equipo ─────────────────────────────────
    fun abrirEquipo(serial: String) {
        val api = api ?: return
        val ref = estado.value.lote?.ref ?: return
        if (estado.value.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            when (val r = api.ficha(ref, serial)) {
                is Resultado.Ok -> actualizar {
                    it.copy(pantalla = Pantalla.EQUIPO, ficha = r.valor, ocupado = false, mensaje = null)
                }
                else -> avisarFallaFicha(r)
            }
        }
    }

    fun guardarEquipo(datos: DatosEquipo, componentes: List<Componente>, hardware: HardwareEquipo) {
        val api = api ?: return
        val s = estado.value
        val ref = s.lote?.ref ?: return
        val ficha = s.ficha ?: return
        val cambios = CambiosEquipo.entre(ficha, datos, componentes, hardware)
        if (cambios.vacio || s.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, mensaje = null) }
            when (val r = api.editar(PedidoEditar(ref, ficha.serial, ficha.version, cambios))) {
                is Resultado.Ok -> {
                    senal(Nivel.OK)
                    actualizar { it.copy(ficha = r.valor, ocupado = false, mensaje = "✅ Guardado en el PC.") }
                    refrescarLote()
                }
                is Resultado.Rechazado -> {
                    senal(Nivel.ERROR)
                    when {
                        r.codigo == 401 -> falla(r)
                        // El lote se cerró en el PC: se vuelve a la lista, como al escanear.
                        r.error.error == "lote" -> cargarLotes(r.error.mensaje)
                        // Cambió en el PC (o el guardado llegó y se perdió la respuesta):
                        // se trae lo que hay ahora para no pisarlo.
                        r.error.error == "cambiado" -> recargarFicha(ref, ficha.serial, r.error.mensaje)
                        else -> actualizar { it.copy(ocupado = false, mensaje = "❌ ${r.error.mensaje}") }
                    }
                }
                is Resultado.SinConexion -> {
                    senal(Nivel.ERROR)
                    actualizar { it.copy(ocupado = false, mensaje = "📵 Sin conexión con el PC: no se guardó.") }
                }
            }
        }
    }

    private suspend fun recargarFicha(ref: LoteRef, serial: String, mensaje: String) {
        val nueva = (api?.ficha(ref, serial) as? Resultado.Ok)?.valor
        actualizar { it.copy(ficha = nueva ?: it.ficha, ocupado = false, mensaje = "⚠️ $mensaje Se recargó: revisá y guardá de nuevo.") }
    }

    private fun avisarFallaFicha(r: Resultado<*>) {
        senal(Nivel.ERROR)
        when {
            r is Resultado.Rechazado && r.codigo == 401 -> falla(r)
            r is Resultado.Rechazado && r.error.error == "lote" -> cargarLotes(r.error.mensaje)
            else -> {
                val texto = (r as? Resultado.Rechazado)?.error?.mensaje ?: "📵 Sin conexión con el PC."
                actualizar { it.copy(ocupado = false, aviso = Aviso("❌ $texto", Nivel.ERROR)) }
            }
        }
    }

    fun cerrarEquipo() {
        estabilizador.olvidar()
        actualizar { it.copy(pantalla = Pantalla.ESCANEAR, ficha = null, mensaje = null, ocupado = false) }
        refrescarSeguido()
    }

    // ── Gestión: mover o quitar el equipo de la ficha ────
    /** Los lotes abiertos, para elegir a cuál mover el equipo. */
    fun pedirLotesDestino() {
        val api = api ?: return
        viewModelScope.launch {
            (api.lotes() as? Resultado.Ok)?.let { r -> actualizar { it.copy(lotes = r.valor) } }
        }
    }

    fun moverEquipo(destino: LoteRef) {
        val api = api ?: return
        val s = estado.value
        val ref = s.lote?.ref ?: return
        val ficha = s.ficha ?: return
        if (s.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, mensaje = null) }
            when (val r = api.mover(PedidoMover(ref, ficha.serial, destino))) {
                is Resultado.Ok -> {
                    sacarDelBorrador(ficha.serial)
                    volverDeFicha("↔️ ${r.valor.serial} pasó a ${r.valor.destino}")
                }
                else -> fallaEnFicha(r)
            }
        }
    }

    fun quitarEquipo() {
        val api = api ?: return
        val s = estado.value
        val ref = s.lote?.ref ?: return
        val ficha = s.ficha ?: return
        if (s.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, mensaje = null) }
            when (val r = api.quitar(ref, ficha.serial)) {
                is Resultado.Ok -> {
                    sacarDelBorrador(ficha.serial)
                    volverDeFicha("🗑️ ${r.valor.serial} quitado del lote (quedan ${r.valor.total})")
                }
                else -> fallaEnFicha(r)
            }
        }
    }

    private fun volverDeFicha(texto: String) {
        senal(Nivel.OK)
        estabilizador.olvidar()
        actualizar {
            it.copy(
                pantalla = Pantalla.ESCANEAR, ficha = null, mensaje = null, ocupado = false,
                aviso = Aviso(texto, Nivel.OK),
            )
        }
        refrescarLote()
        refrescarSeguido()
    }

    /** El error queda a la vista en la ficha; solo un 401 saca de ahí. */
    private fun fallaEnFicha(r: Resultado<*>) {
        senal(Nivel.ERROR)
        if (r is Resultado.Rechazado && r.codigo == 401) {
            falla(r)
            return
        }
        val texto = (r as? Resultado.Rechazado)?.error?.mensaje ?: "📵 Sin conexión con el PC."
        actualizar { it.copy(ocupado = false, mensaje = "❌ $texto") }
    }

    // ── Gestión: documento y cierre del lote ─────────────
    /** Carga o corrige la guía (entrega) u OT (retiro) del lote, en TODOS sus equipos. */
    fun fijarDocumento(numeroSec: String) {
        val api = api ?: return
        val ref = estado.value.lote?.ref ?: return
        if (estado.value.ocupado) return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            when (val r = api.documento(ref, numeroSec.trim())) {
                is Resultado.Ok -> {
                    senal(Nivel.OK)
                    val doc = if (r.valor.mov == Movimientos.ENTREGA) "Guía" else "OT"
                    val valor = r.valor.numeroSec.ifBlank { "sin cargar" }
                    actualizar {
                        it.copy(lote = r.valor, ocupado = false, aviso = Aviso("📄 $doc del lote: $valor (en todos los equipos)", Nivel.OK))
                    }
                }
                else -> fallaEnLote(r)
            }
        }
    }

    fun pedirCierre() {
        val api = api ?: return
        val ref = estado.value.lote?.ref ?: return
        if (estado.value.ocupado) return
        val sinGuardar = estado.value.borrador.size
        if (sinGuardar > 0) {
            senal(Nivel.ERROR)
            actualizar { it.copy(aviso = Aviso("⚠️ Hay $sinGuardar cargador(es) sin guardar: guardá o descartá la lista antes de cerrar.", Nivel.ERROR)) }
            return
        }
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true) }
            when (val r = api.resumenCierre(ref)) {
                is Resultado.Ok -> actualizar { it.copy(ocupado = false, pregunta = Pregunta.Cerrar(r.valor)) }
                else -> fallaEnLote(r)
            }
        }
    }

    fun cerrarLote() {
        val api = api ?: return
        val ref = estado.value.lote?.ref ?: return
        viewModelScope.launch {
            actualizar { it.copy(ocupado = true, pregunta = null) }
            when (val r = api.cerrar(ref)) {
                is Resultado.Ok -> {
                    senal(Nivel.OK)
                    estabilizador.olvidar()
                    val bk = r.valor.backup?.let { " Backup: $it" } ?: ""
                    cargarLotes(aviso = Aviso("📦 ${r.valor.etiqueta} cerrado con ${r.valor.total} equipo(s).$bk", Nivel.OK))
                }
                else -> fallaEnLote(r)
            }
        }
    }

    /** 401 desempareja; si el lote ya no está abierto se vuelve a la lista; lo demás es un aviso. */
    private fun fallaEnLote(r: Resultado<*>) {
        senal(Nivel.ERROR)
        when {
            r is Resultado.Rechazado && r.codigo == 401 -> falla(r)
            r is Resultado.Rechazado && r.error.error == "lote" -> cargarLotes(r.error.mensaje)
            else -> {
                val texto = (r as? Resultado.Rechazado)?.error?.mensaje ?: "📵 Sin conexión con el PC."
                actualizar { it.copy(ocupado = false, pregunta = null, aviso = Aviso("❌ $texto", Nivel.ERROR)) }
            }
        }
    }

    // ── Modo ─────────────────────────────────────────────
    fun cambiarModo(m: Modo) = actualizar { it.copy(flujo = it.flujo.conModo(m)) }

    fun leerDeNuevo() = estabilizador.olvidar()

    private fun refrescarSeguido() {
        refresco?.cancel()
        refresco = viewModelScope.launch {
            while (true) {
                delay(REFRESCO_MS)
                val s = estado.value
                if (s.pantalla != Pantalla.ESCANEAR) break
                if (!s.ocupado && s.pregunta == null) refrescarLote()
            }
        }
    }

    private fun nuevoId() = UUID.randomUUID().toString()

    private companion object {
        val CAMBIAN_EL_LOTE = setOf("registrado", "asignado")
        const val REFRESCO_MS = 3_000L
        const val RECONEXION_MS = 5_000L
    }
}
