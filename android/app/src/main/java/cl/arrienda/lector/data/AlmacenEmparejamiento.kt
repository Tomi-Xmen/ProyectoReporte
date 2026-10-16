package cl.arrienda.lector.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.preferencias: DataStore<Preferences> by preferencesDataStore(name = "lector")

/**
 * Recuerda el último emparejamiento para no escanear el QR cada vez que se
 * abre la app. Si el PC apagó y volvió a encender el panel, el token ya no
 * sirve: el primer pedido da 401 y la app vuelve a pedir el QR.
 */
class AlmacenEmparejamiento(private val context: Context) {
    private val claveQr = stringPreferencesKey("emparejamiento")

    suspend fun leer(): Emparejamiento? =
        context.preferencias.data.first()[claveQr]?.let(Emparejamiento::desdeQr)

    suspend fun guardar(e: Emparejamiento) {
        context.preferencias.edit { it[claveQr] = json.encodeToString(Emparejamiento.serializer(), e) }
    }

    suspend fun borrar() {
        context.preferencias.edit { it.remove(claveQr) }
    }
}
