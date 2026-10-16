package cl.arrienda.lector.ui

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import cl.arrienda.lector.escaneo.Nivel

/**
 * Sonido + vibración por respuesta, para escanear sin mirar la pantalla:
 * un bip corto es OK, dos es "ojo", uno largo es error.
 */
class Feedback(context: Context) {
    private val tonos = runCatching { ToneGenerator(AudioManager.STREAM_NOTIFICATION, 90) }.getOrNull()
    private val vibrador: Vibrator? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }

    fun dar(nivel: Nivel) {
        val (tono, duracionTono, patron) = when (nivel) {
            Nivel.OK -> Triple(ToneGenerator.TONE_PROP_BEEP, 120, longArrayOf(0, 60))
            Nivel.AVISO -> Triple(ToneGenerator.TONE_PROP_BEEP2, 220, longArrayOf(0, 60, 80, 60))
            Nivel.PREGUNTA -> Triple(ToneGenerator.TONE_PROP_ACK, 200, longArrayOf(0, 40, 60, 40, 60, 40))
            Nivel.ERROR -> Triple(ToneGenerator.TONE_SUP_ERROR, 450, longArrayOf(0, 400))
        }
        tonos?.startTone(tono, duracionTono)
        vibrador?.vibrate(VibrationEffect.createWaveform(patron, -1))
    }

    fun liberar() {
        tonos?.release()
    }
}
