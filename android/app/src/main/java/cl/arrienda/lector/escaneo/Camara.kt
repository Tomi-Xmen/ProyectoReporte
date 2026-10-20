package cl.arrienda.lector.escaneo

import android.os.SystemClock
import android.util.Log
import android.util.Size
import androidx.annotation.OptIn
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size as TamanoUi
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import cl.arrienda.lector.data.Lectura
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.delay

/** Nombre del formato como lo espera el PC (motivo_descarte reconoce EAN/UPC por nombre). */
fun nombreFormato(formato: Int): String = when (formato) {
    Barcode.FORMAT_CODE_128 -> "CODE_128"
    Barcode.FORMAT_CODE_39 -> "CODE_39"
    Barcode.FORMAT_CODE_93 -> "CODE_93"
    Barcode.FORMAT_CODABAR -> "CODABAR"
    Barcode.FORMAT_DATA_MATRIX -> "DATA_MATRIX"
    Barcode.FORMAT_EAN_13 -> "EAN_13"
    Barcode.FORMAT_EAN_8 -> "EAN_8"
    Barcode.FORMAT_ITF -> "ITF"
    Barcode.FORMAT_QR_CODE -> "QR_CODE"
    Barcode.FORMAT_UPC_A -> "UPC_A"
    Barcode.FORMAT_UPC_E -> "UPC_E"
    Barcode.FORMAT_PDF417 -> "PDF417"
    Barcode.FORMAT_AZTEC -> "AZTEC"
    else -> ""
}

/**
 * Lo que la cámara está viendo, para mostrarlo encima de la imagen: si ML Kit
 * no detecta nada, si el recuadro lo deja afuera o si la lectura sale bien
 * pero el PC no la toma, se nota a simple vista.
 */
private data class Visto(
    val cuadros: Int = 0,
    val cajas: List<Pair<Caja, Boolean>> = emptyList(), // en coordenadas de la vista; true = adentro
    val ultima: String? = null,
    val error: String? = null,
)

private const val TAG = "Lector"

/**
 * Preview y análisis en 4:3 los dos, para que muestren el mismo campo y el
 * recuadro dibujado coincida con lo que lee ML Kit. 1280×960 en vez de los
 * 640×480 de fábrica: a esa resolución los QR chicos de los transformadores
 * no se leen.
 */
private fun selectorResolucion(ancho: Int, alto: Int) = ResolutionSelector.Builder()
    .setAspectRatioStrategy(AspectRatioStrategy.RATIO_4_3_FALLBACK_AUTO_STRATEGY)
    .setResolutionStrategy(
        ResolutionStrategy(Size(ancho, alto), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER),
    )
    .build()

/**
 * Vista de cámara que lee códigos. Llama a [alLeer] con todos los códigos de
 * una etiqueta cuando quedó firme (ver [Estabilizador]), solo mientras
 * [activo] sea true: con una pregunta abierta o un envío en curso no lee.
 *
 * Con [recuadro] (fracción del tamaño de la vista, ver [Recuadro]) se dibuja
 * la mira y solo cuentan los códigos cuyo centro cae adentro; null lee todo.
 *
 * Tocar la imagen enfoca ahí. Con [zoom] (fracción 0..1, ver [Zoom]) se
 * puede pellizcar para acercar, y cada cambio pide [alCambiarZoom]; después
 * de acomodarse el zoom se enfoca solo el centro, donde está el recuadro.
 */
@OptIn(ExperimentalGetImage::class)
@Composable
fun VistaCamara(
    activo: Boolean,
    linterna: Boolean,
    estabilizador: Estabilizador,
    alLeer: (List<Lectura>) -> Unit,
    modifier: Modifier = Modifier,
    recuadro: Float? = null,
    zoom: Float? = null,
    alCambiarZoom: (Float) -> Unit = {},
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val activoActual by rememberUpdatedState(activo)
    val alLeerActual by rememberUpdatedState(alLeer)
    val recuadroActual by rememberUpdatedState(recuadro)
    val zoomActual by rememberUpdatedState(zoom)
    val alCambiarZoomActual by rememberUpdatedState(alCambiarZoom)
    val vista = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    val camara = remember { mutableStateOf<Camera?>(null) }
    var foco by remember { mutableStateOf<Offset?>(null) }
    var visto by remember { mutableStateOf(Visto()) }
    val principal = remember { ContextCompat.getMainExecutor(context) }

    DisposableEffect(lifecycleOwner) {
        val lector = BarcodeScanning.getClient()
        val hilo = Executors.newSingleThreadExecutor()
        // Uno solo en uso a la vez: KEEP_ONLY_LATEST no pasa otro cuadro hasta cerrar este.
        var invertida: ByteArray? = null
        val futuro = ProcessCameraProvider.getInstance(context)

        val analisis = ImageAnalysis.Builder()
            .setResolutionSelector(selectorResolucion(1280, 960))
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
        analisis.setAnalyzer(hilo) { proxy: ImageProxy ->
            val imagen = proxy.image
            if (imagen == null || !activoActual) {
                // Sin leer, las cajas de antes ya no dicen nada.
                principal.execute { if (visto.cajas.isNotEmpty()) visto = visto.copy(cajas = emptyList()) }
                proxy.close()
                return@setAnalyzer
            }
            val rotacion = proxy.imageInfo.rotationDegrees
            val y = proxy.planes[0]
            invertida = luminanciaInvertidaNv21(
                y.buffer, proxy.width, proxy.height, y.rowStride, y.pixelStride, invertida,
            )
            // Dos pasadas por cuadro: tal cual y en negativo (ver Invertir.kt).
            val normal = lector.process(InputImage.fromMediaImage(imagen, rotacion))
            val negativo = lector.process(
                InputImage.fromByteArray(invertida!!, proxy.width, proxy.height, rotacion, InputImage.IMAGE_FORMAT_NV21),
            )
            Tasks.whenAllComplete(normal, negativo)
                .continueWith { _ ->
                    if (!normal.isSuccessful && !negativo.isSuccessful) throw normal.exception ?: negativo.exception!!
                    val vistos = (if (normal.isSuccessful) normal.result else emptyList()) +
                        (if (negativo.isSuccessful) negativo.result else emptyList())
                    vistos.distinctBy { it.rawValue }
                }
                .addOnSuccessListener { codigos ->
                    val fraccion = recuadroActual
                    val anchoVista = vista.width.toFloat()
                    val altoVista = vista.height.toFloat()
                    val cajas = ArrayList<Pair<Caja, Boolean>>()
                    val cuadro = codigos
                        .filter { c ->
                            val b = c.boundingBox ?: return@filter true
                            val caja = Caja(b.left.toFloat(), b.top.toFloat(), b.right.toFloat(), b.bottom.toFloat())
                            val adentro = fraccion == null || Recuadro.contiene(
                                caja, proxy.width, proxy.height, rotacion, anchoVista, altoVista, fraccion,
                            )
                            if (anchoVista > 0f && altoVista > 0f) {
                                cajas += Recuadro.aVista(caja, proxy.width, proxy.height, rotacion, anchoVista, altoVista) to adentro
                            }
                            adentro
                        }
                        .mapNotNull { c -> c.rawValue?.let { Lectura(it, nombreFormato(c.format)) } }
                    val etiqueta = estabilizador.alimentar(cuadro, SystemClock.elapsedRealtime())
                    if (codigos.isNotEmpty()) {
                        Log.d(TAG, "${codigos.size} código(s), ${cuadro.size} en el recuadro: ${cuadro.map { it.texto.take(40) }}")
                    }
                    principal.execute {
                        visto = visto.copy(
                            cuadros = visto.cuadros + 1,
                            cajas = cajas,
                            ultima = etiqueta?.joinToString(" · ") { it.texto.take(30) } ?: visto.ultima,
                            error = null,
                        )
                    }
                    if (etiqueta != null && activoActual) alLeerActual(etiqueta)
                }
                .addOnFailureListener { e ->
                    Log.e(TAG, "ML Kit falló", e)
                    principal.execute { visto = visto.copy(error = e.message ?: e.javaClass.simpleName) }
                }
                .addOnCompleteListener { proxy.close() }
        }

        futuro.addListener({
            val proveedor = futuro.get()
            val preview = Preview.Builder()
                .setResolutionSelector(selectorResolucion(1440, 1080))
                .build().also { it.setSurfaceProvider(vista.surfaceProvider) }
            proveedor.unbindAll()
            camara.value = proveedor.bindToLifecycle(
                lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analisis,
            )
        }, ContextCompat.getMainExecutor(context))

        onDispose {
            runCatching { futuro.get().unbindAll() }
            camara.value = null
            hilo.shutdown()
            lector.close()
        }
    }

    LaunchedEffect(zoom, camara.value) {
        val c = camara.value ?: return@LaunchedEffect
        val z = zoom ?: return@LaunchedEffect
        val (min, max) = limitesZoom(c)
        c.cameraControl.setZoomRatio(Zoom.aAumento(z, min, max))
        // Mientras se pellizca llegan muchos cambios: se enfoca al soltar.
        delay(400)
        enfocar(c, vista, vista.width / 2f, vista.height / 2f)
    }

    LaunchedEffect(foco) {
        if (foco != null) {
            delay(1_000)
            foco = null
        }
    }

    LaunchedEffect(linterna, camara.value) {
        camara.value?.let { if (it.cameraInfo.hasFlashUnit()) it.cameraControl.enableTorch(linterna) }
    }

    Box(modifier) {
        AndroidView(factory = { vista }, modifier = Modifier.fillMaxSize())
        recuadro?.let { MiraRecuadro(it) }
        CajasVistas(visto.cajas)
        foco?.let { AnilloFoco(it) }
        Text(
            textoVisto(visto),
            color = Color.White,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .fillMaxWidth()
                .background(Color(0x99000000))
                .padding(horizontal = 8.dp, vertical = 4.dp),
        )
        Box(
            Modifier
                .fillMaxSize()
                .pointerInput(Unit) {
                    detectTapGestures { punto ->
                        camara.value?.let { c ->
                            enfocar(c, vista, punto.x, punto.y)
                            foco = punto
                        }
                    }
                }
                .pointerInput(Unit) {
                    detectTransformGestures { _, _, cambio, _ ->
                        val z = zoomActual ?: return@detectTransformGestures
                        val c = camara.value ?: return@detectTransformGestures
                        if (cambio == 1f) return@detectTransformGestures
                        val (min, max) = limitesZoom(c)
                        val aumento = Zoom.aAumento(z, min, max) * cambio
                        alCambiarZoomActual(Zoom.aFraccion(aumento, min, max))
                    }
                },
        )
    }
}

private fun limitesZoom(camara: Camera): Pair<Float, Float> {
    val estado = camara.cameraInfo.zoomState.value
    return (estado?.minZoomRatio ?: 1f) to (estado?.maxZoomRatio ?: 1f)
}

/** Enfoca y mide la luz en ese punto de la vista; a los segundos vuelve al autofoco continuo. */
private fun enfocar(camara: Camera, vista: PreviewView, x: Float, y: Float) {
    if (vista.width == 0 || vista.height == 0) return
    val punto = vista.meteringPointFactory.createPoint(x, y)
    val accion = FocusMeteringAction.Builder(punto, FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE)
        .setAutoCancelDuration(4, TimeUnit.SECONDS)
        .build()
    camara.cameraControl.startFocusAndMetering(accion)
}

private fun textoVisto(v: Visto): String {
    if (v.error != null) return "⚠ Falla del lector: ${v.error}"
    if (v.cuadros == 0) return "Esperando la cámara…"
    val adentro = v.cajas.count { it.second }
    val ahora = when {
        v.cajas.isEmpty() -> "No veo ningún código"
        adentro == 0 -> "Veo ${v.cajas.size} código(s), ninguno en el recuadro"
        else -> "Veo ${v.cajas.size} código(s), $adentro en el recuadro"
    }
    return v.ultima?.let { "$ahora\nÚltimo leído: $it" } ?: ahora
}

/** Verde: cuenta (adentro del recuadro). Amarillo: se ve pero se ignora. */
@Composable
private fun CajasVistas(cajas: List<Pair<Caja, Boolean>>) {
    if (cajas.isEmpty()) return
    Canvas(Modifier.fillMaxSize()) {
        for ((c, adentro) in cajas) {
            drawRect(
                color = if (adentro) Color(0xFF22C55E) else Color(0xFFFACC15),
                topLeft = Offset(c.izq, c.arriba),
                size = TamanoUi(c.der - c.izq, c.abajo - c.arriba),
                style = Stroke(width = 3.dp.toPx()),
            )
        }
    }
}

@Composable
private fun AnilloFoco(centro: Offset) {
    Canvas(Modifier.fillMaxSize()) {
        drawCircle(Color.White, radius = 28.dp.toPx(), center = centro, style = Stroke(width = 2.dp.toPx()))
    }
}

/** Oscurece lo que queda afuera del recuadro y le marca el borde. */
@Composable
private fun MiraRecuadro(fraccion: Float) {
    Canvas(Modifier.fillMaxSize()) {
        val c = Recuadro.enVista(size.width, size.height, fraccion)
        val radio = CornerRadius(12.dp.toPx())
        val hueco = RoundRect(c.izq, c.arriba, c.der, c.abajo, radio)
        val fuera = Path().apply {
            fillType = PathFillType.EvenOdd
            addRect(Rect(Offset.Zero, size))
            addRoundRect(hueco)
        }
        drawPath(fuera, Color(0x88000000))
        drawRoundRect(
            color = Color.White,
            topLeft = Offset(c.izq, c.arriba),
            size = TamanoUi(c.der - c.izq, c.abajo - c.arriba),
            cornerRadius = radio,
            style = Stroke(width = 3.dp.toPx()),
        )
    }
}
