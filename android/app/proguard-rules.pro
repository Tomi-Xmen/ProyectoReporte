# kotlinx.serialization: conservar los serializadores generados de los modelos.
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class cl.arrienda.lector.data.** {
    *** Companion;
}
-keepclasseswithmembers class cl.arrienda.lector.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
