package cl.arrienda.lector.escaneo

import java.nio.ByteBuffer

/**
 * Los cargadores (HP y otros) traen el serial en un Data Matrix grabado en
 * blanco sobre la etiqueta negra. ML Kit solo busca códigos oscuros sobre
 * fondo claro: a esos no los ve. Cada cuadro se le pasa también invertido.
 *
 * Arma un NV21 con la luminancia invertida y el color en gris (los lectores
 * de códigos solo miran la luminancia). [plano] es el plano Y de la cámara,
 * con sus [pasoFila] y [pasoPixel]. Reusa [destino] si tiene el tamaño justo.
 *
 * Sin Android adentro: se prueba en la JVM.
 */
fun luminanciaInvertidaNv21(
    plano: ByteBuffer,
    ancho: Int,
    alto: Int,
    pasoFila: Int,
    pasoPixel: Int,
    destino: ByteArray? = null,
): ByteArray {
    val tamano = ancho * alto * 3 / 2
    val salida = if (destino != null && destino.size == tamano) destino else ByteArray(tamano)
    val origen = plano.duplicate()
    if (pasoPixel == 1) {
        // Lo normal en el plano Y: se copia fila por fila de una vez.
        for (y in 0 until alto) {
            origen.position(y * pasoFila)
            origen.get(salida, y * ancho, ancho)
        }
        for (i in 0 until ancho * alto) salida[i] = (salida[i].toInt() xor 0xFF).toByte()
    } else {
        var i = 0
        for (y in 0 until alto) {
            val inicio = y * pasoFila
            for (x in 0 until ancho) {
                salida[i++] = (origen.get(inicio + x * pasoPixel).toInt() xor 0xFF).toByte()
            }
        }
    }
    salida.fill(128.toByte(), ancho * alto, tamano)
    return salida
}
