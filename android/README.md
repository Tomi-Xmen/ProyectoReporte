# Lector Arrienda (Android)

App que usa el celular como lector de códigos (QR y de barras) para las OT y
guías del programa de escritorio (REPORTE3). El celular no guarda reportes: lee
el código y lo manda al PC, que registra el equipo con los mismos JSON, HTML y
FUSIONADO de siempre.

## Cómo se usa

1. En el PC: menú → **Lector celular** → **Encender**.
2. En el celular: abrir la app y escanear el QR del panel. El celular y el PC
   tienen que estar en el mismo Wi-Fi.
3. Elegir una OT/guía abierta o crear una nueva.
4. Elegir qué se escanea y apuntar a la etiqueta:
   - **Notebook + cargador** (guiado): notebook, después su cargador, y así.
   - **Notebooks**, **Monitores**, **Impresoras**: uno tras otro.
   - **Cargadores en ráfaga**: cada cargador va al siguiente notebook sin
     cargador, en el orden en que se escanearon.

Cada respuesta suena y vibra distinto (OK, aviso, pregunta, error), así que
se puede escanear sin mirar la pantalla. Si la etiqueta tiene varios códigos
(S/N, P/N, EAN…) el PC elige el serial; si hay duda, pregunta. Una etiqueta
ilegible se escribe a mano.

Si se corta el Wi-Fi, el escaneo queda pendiente y se reintenta con el botón;
el PC reconoce el reintento y no registra dos veces.

## Estructura

```
app/src/main/java/cl/arrienda/lector/
  data/      contrato con el PC: modelos, cliente HTTP, emparejamiento guardado
  escaneo/   cámara + ML Kit, cuándo una lectura está firme, modo guiado, textos
  ui/        pantallas (Compose), ViewModel, sonido y vibración
app/src/test/  tests JVM (sin celular)
```

La lógica que decide (qué es un serial, a qué lote va, duplicados) vive en el
PC (`inventario/nucleo/escaneos.py`); la app solo lee, pregunta y muestra.

## Contrato con el PC

`app/src/test/resources/contrato/respuestas_api.json` son respuestas reales de
la API de Python, generadas por `tests/test_contrato_celular.py`. Los tests de
la app las decodifican en modo estricto y los de Python fallan si la API
cambia de forma sin regenerarlas: así las dos partes no se desincronizan.

## Compilar

Con Android Studio: abrir la carpeta `android/` y ejecutar. Desde consola
(JDK 17 y SDK de Android 35):

```
gradlew testDebugUnitTest      tests
gradlew assembleDebug          APK en app/build/outputs/apk/debug/
```

Para instalar en un celular: activar *Opciones de desarrollador → Depuración
USB* y `adb install app/build/outputs/apk/debug/app-debug.apk`, o copiar el APK
al celular y abrirlo (pide permitir "instalar apps desconocidas").

## Seguridad

- El QR trae un token que cambia cada vez que se enciende el panel del PC.
- El PC solo acepta conexiones de la red local.
- El tráfico es HTTP dentro del Wi-Fi (ver `res/xml/network_security_config.xml`).
  Mejora pendiente: TLS con certificado propio del PC y su huella en el QR.
