package cl.arrienda.lector.escaneo

import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import cl.arrienda.lector.data.Lectura
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors

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
 * Vista de cámara que lee códigos. Llama a [alLeer] con todos los códigos de
 * una etiqueta cuando quedó firme (ver [Estabilizador]), solo mientras
 * [activo] sea true: con una pregunta abierta o un envío en curso no lee.
 */
@OptIn(ExperimentalGetImage::class)
@Composable
fun VistaCamara(
    activo: Boolean,
    linterna: Boolean,
    estabilizador: Estabilizador,
    alLeer: (List<Lectura>) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val activoActual by rememberUpdatedState(activo)
    val alLeerActual by rememberUpdatedState(alLeer)
    val vista = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    val camara = remember { mutableStateOf<Camera?>(null) }

    DisposableEffect(lifecycleOwner) {
        val lector = BarcodeScanning.getClient()
        val hilo = Executors.newSingleThreadExecutor()
        val futuro = ProcessCameraProvider.getInstance(context)

        val analisis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
        analisis.setAnalyzer(hilo) { proxy: ImageProxy ->
            val imagen = proxy.image
            if (imagen == null || !activoActual) {
                proxy.close()
                return@setAnalyzer
            }
            lector.process(InputImage.fromMediaImage(imagen, proxy.imageInfo.rotationDegrees))
                .addOnSuccessListener { codigos ->
                    val cuadro = codigos.mapNotNull { c ->
                        c.rawValue?.let { Lectura(it, nombreFormato(c.format)) }
                    }
                    val etiqueta = estabilizador.alimentar(cuadro, SystemClock.elapsedRealtime())
                    if (etiqueta != null && activoActual) alLeerActual(etiqueta)
                }
                .addOnCompleteListener { proxy.close() }
        }

        futuro.addListener({
            val proveedor = futuro.get()
            val preview = Preview.Builder().build().also { it.setSurfaceProvider(vista.surfaceProvider) }
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

    LaunchedEffect(linterna, camara.value) {
        camara.value?.let { if (it.cameraInfo.hasFlashUnit()) it.cameraControl.enableTorch(linterna) }
    }

    AndroidView(factory = { vista }, modifier = modifier)
}
