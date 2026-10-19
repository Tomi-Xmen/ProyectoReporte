"""
API del lector celular: qué responde el PC a cada pedido del celular.

Sin red ni Qt: recibe el pedido ya separado (método, ruta, cabeceras, cuerpo)
y devuelve (código HTTP, dict). El transporte (ui/servidor_celular.py) solo
mueve bytes, así toda la lógica se prueba sin abrir un puerto.

    GET  /api/v1/estado     ping; el celular confirma que el emparejamiento sirve
    GET  /api/v1/lotes      OT/guías abiertas
    GET  /api/v1/clientes   clientes existentes (para autocompletar)
    POST /api/v1/lotes      crear o reabrir un lote {mov, cliente, numero, numero_sec, reabrir}
    POST /api/v1/lote       equipos de un lote {lote: {mov, cliente, numero}}
    POST /api/v1/escaneo    un escaneo (ver _escaneo)
    POST /api/v1/equipo     ficha de un equipo {lote, serial} (ver nucleo/fichas.py)
    POST /api/v1/equipo/editar  editar su JSON {lote, serial, version, cambios}

Seguridad: el token viaja solo en el QR de emparejamiento; sin él todo
responde 401. Se guarda en lector_celular.json (junto al programa) para que
el celular siga emparejado entre reinicios; "Código nuevo" en el panel lo
cambia y desempareja a todos. El transporte además rechaza conexiones que no
vengan de la red local.

El celular NO cambia la OT activa del PC ni cierra lotes: trabaja sobre el
lote que nombra en cada pedido, y el cierre sigue siendo una decisión del PC.
"""

import hmac
import ipaddress
import json
import secrets
import socket
from collections import OrderedDict
from datetime import datetime

from . import fichas
from .escaneos import (
    TIPO_TRANSFORMADOR,
    TIPOS_CODIGO,
    LoteInvalido,
    asignar_transformador,
    cargar_reglas,
    elegir_codigo,
    estado_lote,
    lote_desde_formulario,
    registrar_equipo,
    resolver_lote,
)
from .lotes import (
    abrir_lote,
    clientes_existentes,
    esta_cerrado,
    etiqueta_lote,
    leer_cerrado,
    listar_lotes_abiertos,
    reabrir_lote,
)

VERSION_API = 1
APP_ID = "inventario-arrienda"
PREFIJO = f"/api/v{VERSION_API}"

# Respuestas recordadas por id de escaneo: si el celular reintenta porque se
# cortó el Wi-Fi justo después de mandar, recibe la misma respuesta y el
# equipo no se procesa dos veces.
_MAX_RECORDADAS = 500
_MAX_LECTURAS = 20


ARCHIVO_PREFERENCIAS = "lector_celular.json"
_LARGO_MIN_TOKEN = 16


def cargar_preferencias(ruta=None):
    """
    Preferencias del lector: {"encender_al_iniciar", "token", "puerto"}. Sin
    archivo, o con uno roto, vuelve todo apagado: un JSON dañado nunca abre
    un puerto ni deja pasar un token que no es.
    """
    prefs = {"encender_al_iniciar": False, "token": None, "puerto": None}
    try:
        with open(ruta or ARCHIVO_PREFERENCIAS, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return prefs
    if not isinstance(datos, dict):
        return prefs
    prefs["encender_al_iniciar"] = datos.get("encender_al_iniciar") is True
    token = datos.get("token")
    if isinstance(token, str) and len(token) >= _LARGO_MIN_TOKEN:
        prefs["token"] = token
    puerto = datos.get("puerto")
    if isinstance(puerto, int) and not isinstance(puerto, bool) and 1024 <= puerto <= 65535:
        prefs["puerto"] = puerto
    return prefs


def guardar_preferencias(prefs, ruta=None):
    """Escribe las preferencias. Un error se avisa por consola: no corta el lector."""
    try:
        with open(ruta or ARCHIVO_PREFERENCIAS, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=4)
    except OSError as e:
        print(f"⚠️  No se pudo guardar {ARCHIVO_PREFERENCIAS}: {e}")


def token_nuevo():
    return secrets.token_urlsafe(24)


def es_red_local(ip):
    """True para loopback y direcciones privadas (192.168.x, 10.x, 172.16-31.x)."""
    try:
        direccion = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if getattr(direccion, "ipv4_mapped", None):
        direccion = direccion.ipv4_mapped
    return direccion.is_loopback or direccion.is_private


def ip_principal():
    """
    IP de esta PC en la red local: la de la interfaz con salida por defecto.
    Conectar un socket UDP no manda ningún paquete; solo hace que el sistema
    elija la interfaz. None si no hay red.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return ip if es_red_local(ip) and not ip.startswith("127.") else None
    except OSError:
        return None


def describir_respuesta(r):
    """Una línea legible para el registro del panel."""
    estado = r.get("estado")
    if estado == "editado":
        return f"✏️ Ficha editada desde el celular: {', '.join(r['campos'])}"
    if estado == "registrado":
        return f"✅ {r['tipo']} registrado ({r['total']} en el lote)"
    if estado == "asignado":
        extra = f" (reemplazó a {r['reemplazo']})" if r.get("reemplazo") else ""
        return f"🔌 Transformador → {r['equipo']}{extra}"
    if estado == "ya_estaba":
        return f"☑️ Ya estaba en el lote{' (' + r['equipo'] + ')' if r.get('equipo') else ''}"
    if estado == "en_otra_ot":
        return f"⚠️ Ya está en {r['otro']}"
    if estado == "duplicado":
        return f"⚠️ Ese transformador ya es de {r['equipo']}"
    if estado == "otro_tipo":
        return f"❔ Parece {r['tipo']}, no {r['esperado']}"
    if estado == "invalido":
        return f"❌ {r.get('motivo', 'Código inválido')}"
    return {
        "equipo_no_encontrado": "⚠️ El equipo no está en el lote",
        "sin_equipo_pendiente": "⚠️ No quedan notebooks sin transformador",
        "es_equipo": "⚠️ Es el serial de un equipo del lote, no de un transformador",
        "elegir": "❔ Varios códigos: se pidió elegir uno",
        "sin_serial": "❌ Ningún código era un serial",
        "sin_tipo": "❔ Se pidió qué tipo de equipo es",
    }.get(estado, str(estado))


class ErrorPedido(Exception):
    def __init__(self, codigo, error, mensaje):
        super().__init__(mensaje)
        self.codigo, self.error, self.mensaje = codigo, error, mensaje


def _lote_publico(lote):
    """Lo que el celular necesita de un lote, sin rutas del disco del PC."""
    return {
        "mov": lote["mov"],
        "cliente": lote["cliente"],
        "numero": lote["numero"],
        "numero_sec": lote.get("numero_sec", ""),
        "equipos": lote.get("equipos", 0),
        "etiqueta": etiqueta_lote(lote),
    }


class ApiCelular:
    def __init__(self, token=None, reglas=None, al_evento=None):
        """
        al_evento(dict): avisa cada escaneo procesado, para el registro del
        panel. Nunca debe cortar la respuesta: sus errores se ignoran.
        """
        self.token = token or token_nuevo()
        self.reglas = cargar_reglas() if reglas is None else reglas
        self.al_evento = al_evento
        self._recordadas = OrderedDict()

    # ── Emparejamiento ───────────────────────────────────
    def datos_emparejamiento(self, host, puerto):
        return {
            "app": APP_ID,
            "v": VERSION_API,
            "url": f"http://{host}:{puerto}",
            "token": self.token,
        }

    def texto_qr(self, host, puerto):
        return json.dumps(self.datos_emparejamiento(host, puerto), separators=(",", ":"))

    def autorizado(self, cabeceras):
        valor = cabeceras.get("authorization", "")
        esperado = f"Bearer {self.token}"
        return hmac.compare_digest(valor.encode(), esperado.encode())

    # ── Entrada ──────────────────────────────────────────
    def atender(self, metodo, ruta, cabeceras, cuerpo=b""):
        """(código HTTP, dict). Nunca lanza: todo error vuelve como respuesta."""
        try:
            if not self.autorizado(cabeceras):
                raise ErrorPedido(401, "no_autorizado", "Emparejá el celular de nuevo.")
            datos = self._json(cuerpo) if metodo == "POST" else {}
            return 200, self._enrutar(metodo, ruta.split("?", 1)[0], datos)
        except ErrorPedido as e:
            return e.codigo, {"error": e.error, "mensaje": e.mensaje}
        except LoteInvalido as e:
            return e.codigo, {"error": "lote", "titulo": e.titulo, "mensaje": e.mensaje}
        except fichas.ErrorFicha as e:
            return e.codigo, {"error": e.error, "mensaje": e.mensaje}
        except Exception as e:  # un bug no debe tumbar el servidor ni la app
            return 500, {"error": "interno", "mensaje": str(e) or type(e).__name__}

    @staticmethod
    def _json(cuerpo):
        try:
            datos = json.loads((cuerpo or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErrorPedido(400, "json_invalido", "El cuerpo no es JSON válido.")
        if not isinstance(datos, dict):
            raise ErrorPedido(400, "json_invalido", "Se esperaba un objeto JSON.")
        return datos

    def _enrutar(self, metodo, ruta, datos):
        rutas = {
            ("GET", "/estado"): lambda: {"app": APP_ID, "v": VERSION_API},
            ("GET", "/lotes"): lambda: {
                "lotes": [_lote_publico(l) for l in listar_lotes_abiertos()]
            },
            ("GET", "/clientes"): lambda: {"clientes": clientes_existentes()},
            ("POST", "/lotes"): lambda: self._crear_lote(datos),
            ("POST", "/lote"): lambda: estado_lote(self._lote(datos)),
            ("POST", "/escaneo"): lambda: self._escaneo(datos),
            ("POST", "/equipo"): lambda: fichas.ficha(
                self._lote(datos), self._texto(datos, "serial")
            ),
            ("POST", "/equipo/editar"): lambda: self._editar(datos),
        }
        if not ruta.startswith(PREFIJO):
            raise ErrorPedido(404, "ruta", f"Ruta desconocida: {ruta}")
        sub = ruta[len(PREFIJO):] or "/"
        if (metodo, sub) in rutas:
            return rutas[(metodo, sub)]()
        if any(r == sub for _, r in rutas):
            raise ErrorPedido(405, "metodo", f"{metodo} no se usa en {ruta}")
        raise ErrorPedido(404, "ruta", f"Ruta desconocida: {ruta}")

    # ── Lotes ────────────────────────────────────────────
    @staticmethod
    def _texto(datos, clave, obligatorio=True):
        valor = datos.get(clave, "")
        if not isinstance(valor, str) or (obligatorio and not valor.strip()):
            raise ErrorPedido(400, "dato", f"Falta '{clave}'.")
        return valor

    def _lote(self, datos):
        ref = datos.get("lote")
        if not isinstance(ref, dict):
            raise ErrorPedido(400, "dato", "Falta 'lote'.")
        return resolver_lote(
            self._texto(ref, "mov"), self._texto(ref, "cliente"), self._texto(ref, "numero")
        )

    def _crear_lote(self, datos):
        """
        Mismas reglas que el diálogo de nueva OT del PC, incluida la de no
        reabrir una OT cerrada en silencio: sin 'reabrir': true devuelve 409 y
        el celular pregunta, igual que el PC.
        """
        lote = lote_desde_formulario(
            self._texto(datos, "mov"),
            self._texto(datos, "cliente", obligatorio=False),
            self._texto(datos, "numero", obligatorio=False),
            self._texto(datos, "numero_sec", obligatorio=False),
        )
        if esta_cerrado(lote["ruta"]):
            if datos.get("reabrir") is not True:
                meta = leer_cerrado(lote["ruta"])
                raise ErrorPedido(
                    409,
                    "cerrado",
                    f"{etiqueta_lote(lote)} ya está cerrado "
                    f"({meta.get('equipos', '?')} equipo(s)). ¿Reabrirlo?",
                )
            reabrir_lote(lote)
        return estado_lote(abrir_lote(lote))

    # ── Ficha ────────────────────────────────────────────
    def _editar(self, datos):
        lote = self._lote(datos)
        cambios = datos.get("cambios")
        ficha = fichas.editar(
            lote, self._texto(datos, "serial"), cambios, self._texto(datos, "version")
        )
        self._avisar(lote, ficha["serial"], {"estado": "editado", "campos": sorted(cambios)})
        return ficha

    # ── Escaneo ──────────────────────────────────────────
    def _escaneo(self, datos):
        """
        {
          "id": "uuid del escaneo (reintentos)",
          "lote": {"mov", "cliente", "numero"},
          "lecturas": [{"texto", "formato"}],   todo lo que la cámara vio junto
          "esperado": "Notebook" | … | null,    qué se está escaneando
          "tipo": opcional, el usuario eligió el tipo a mano (ignora reglas)
          "serial_equipo": opcional, transformador para ESE equipo
          "forzar": opcional, registrar aunque esté en otra OT
          "modelo", "obs": opcionales
        }

        Además de los estados de registrar_equipo / asignar_transformador:
          elegir      — varios códigos posibles ('candidatos'): el usuario toca uno
          sin_serial  — ningún código servía ('descartes' dice por qué)
          otro_tipo   — las reglas dicen que es otra cosa ('tipo' vs 'esperado')
          sin_tipo    — no se sabe qué es: el celular pregunta el tipo
        """
        id_escaneo = str(datos.get("id") or "")
        if id_escaneo and id_escaneo in self._recordadas:
            self._recordadas.move_to_end(id_escaneo)
            return self._recordadas[id_escaneo]

        lote = self._lote(datos)
        lecturas = self._lecturas(datos)
        tipo_forzado = self._tipo(datos, "tipo")
        esperado = tipo_forzado or self._tipo(datos, "esperado")

        if tipo_forzado:
            # El usuario ya dijo qué es: las reglas no lo contradicen.
            eleccion = elegir_codigo(lecturas, tipo_forzado, ())
        else:
            eleccion = elegir_codigo(lecturas, esperado, self.reglas)
        valor, tipo = eleccion["valor"], eleccion["tipo"]

        if valor is None:
            respuesta = {
                "estado": "elegir" if eleccion["candidatos"] else "sin_serial",
                "candidatos": eleccion["candidatos"],
            }
        elif esperado and tipo != esperado:
            respuesta = {"estado": "otro_tipo", "valor": valor, "tipo": tipo, "esperado": esperado}
        elif not tipo:
            respuesta = {"estado": "sin_tipo", "valor": valor}
        elif tipo == TIPO_TRANSFORMADOR:
            respuesta = asignar_transformador(
                lote, valor, serial_equipo=datos.get("serial_equipo") or None
            )
        else:
            respuesta = registrar_equipo(
                lote,
                valor,
                tipo,
                modelo=str(datos.get("modelo") or ""),
                obs=str(datos.get("obs") or ""),
                forzar=datos.get("forzar") is True,
            )
        respuesta["descartes"] = eleccion["descartes"]
        respuesta["lote"] = etiqueta_lote(lote)

        if id_escaneo:
            self._recordadas[id_escaneo] = respuesta
            while len(self._recordadas) > _MAX_RECORDADAS:
                self._recordadas.popitem(last=False)
        self._avisar(lote, valor, respuesta)
        return respuesta

    @staticmethod
    def _lecturas(datos):
        lecturas = datos.get("lecturas")
        if not isinstance(lecturas, list) or not lecturas:
            raise ErrorPedido(400, "dato", "Falta 'lecturas'.")
        limpias = []
        for l in lecturas[:_MAX_LECTURAS]:
            if not isinstance(l, dict) or not isinstance(l.get("texto"), str):
                raise ErrorPedido(400, "dato", "Cada lectura necesita 'texto'.")
            limpias.append({"texto": l["texto"], "formato": str(l.get("formato") or "")})
        return limpias

    @staticmethod
    def _tipo(datos, clave):
        tipo = datos.get(clave)
        if tipo in (None, ""):
            return None
        if tipo not in TIPOS_CODIGO:
            raise ErrorPedido(400, "dato", f"Tipo desconocido: {tipo!r}")
        return tipo

    def _avisar(self, lote, valor, respuesta):
        if not self.al_evento:
            return
        try:
            self.al_evento(
                {
                    "hora": datetime.now().strftime("%H:%M:%S"),
                    "lote": etiqueta_lote(lote),
                    "valor": valor or "",
                    "respuesta": respuesta,
                }
            )
        except Exception:
            pass
