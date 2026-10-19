"""
Escaneos que llegan del celular usado como lector de códigos (QR, barras).

Dos partes, las dos sin interfaz ni red:

1. QUÉ ES CADA CÓDIGO. Una etiqueta trae varios códigos juntos (S/N, P/N,
   EAN, a veces un QR con una URL) y la cámara los ve a la vez. Acá se limpia
   cada lectura, se descarta lo que nunca es un serial y se elige el que
   corresponde a lo que se está escaneando. Las reglas por tipo (qué forma
   tiene el serial de un transformador, de un monitor…) viven en un JSON
   editable, no en el código.

2. QUÉ HACER CON ÉL. Registrar un equipo en un lote (OT de entrega o guía de
   retiro) o asignarle un transformador. Escribe con las mismas funciones que
   el resto de la app, así el JSON que deja el celular es igual al del PC y el
   HTML/FUSIONADO se regeneran como siempre.

El celular nombra SIEMPRE el lote en cada escaneo (no se usa "el lote activo
del PC"): si alguien cambia de OT en el PC mientras se escanea, nada cae en
la OT equivocada.

Este módulo SOLO SUMA: no cambia nada de lo existente. Usa las funciones de
lotes/transformadores tal como están, y los registros que crea son JSON
comunes que el resto de la app lee sin saber que vinieron del celular.
"""

import json
import os
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from .lotes import (
    MOV_CFG,
    buscar_serial_en_abiertos,
    contar_equipos,
    esta_cerrado,
    etiqueta_lote,
    guardar_registro_en_lote,
    hacer_lote,
    normalizar_cliente,
    normalizar_numero,
    numero_sec_en_disco,
    numeros_lote,
)
from .reporte_html import TRANSF_PENDIENTE
from .transformadores import (
    equipos_en_orden_de_escaneo,
    guardar_transformadores,
    normalizar_sn_transf,
    transformador_actual,
)

# Qué es cada registro del lote. Los JSON sin TIPO_EQUIPO son los de siempre
# (notebooks escaneados en el PC), por eso es el valor por defecto al leer.
TIPO_EQUIPO_DEFAULT = "Notebook"
TIPOS_EQUIPO = (TIPO_EQUIPO_DEFAULT, "Monitor", "Impresora")
TIPO_TRANSFORMADOR = "Transformador"
TIPOS_CODIGO = TIPOS_EQUIPO + (TIPO_TRANSFORMADOR,)

# Marca de los registros creados desde el celular: no tienen escaneo de
# hardware. Si después el equipo se escanea en el PC, guardar_equipo_general
# pisa el registro completo y la marca desaparece sola.
ORIGEN_CELULAR = "celular"

ARCHIVO_REGLAS = "reglas_codigos.json"


def tipo_equipo(jdata):
    return jdata.get("TIPO_EQUIPO") or TIPO_EQUIPO_DEFAULT


# ─────────────────────────────────────────────────────────
#  1. Lecturas: limpiar, descartar y elegir
# ─────────────────────────────────────────────────────────
# Formatos (nombres de ML Kit) que son códigos de producto: identifican el
# modelo, nunca la unidad.
_FORMATOS_PRODUCTO = {"EAN_13", "EAN_8", "UPC_A", "UPC_E"}

# Nombres con que un QR o una URL rotula el serial.
_CLAVES_SERIAL = {
    "S",
    "SN",
    "SERIAL",
    "SERIALNO",
    "SERIALNUM",
    "SERIALNUMBER",
    "SERVICETAG",
    "NS",
    "SERIE",
    "NSERIE",
    "NDESERIE",
    "NUMERODESERIE",
}

# Rótulo pegado adelante del serial ("S/N: 5CD805DVNV", "SERIAL 123…"). "SN"
# solo se quita con separador: "SN12345" puede ser un serial real.
_RE_ROTULO = re.compile(
    r"^(?:S/N|N/S)\s*[:#.\-]?\s*"
    r"|^(?:SN|SERIAL(?:\s*(?:NO|NUMBER|NUM)\.?)?|SERIE|N[°º]?\s*DE\s*SERIE)"
    r"\s*(?:[:#=]\s*|\s+)",
    re.IGNORECASE,
)
_RE_MAC = re.compile(r"^[0-9A-F]{2}(?:[:\-][0-9A-F]{2}){5}$")
_RE_SERIAL = re.compile(r"^[A-Z0-9\-/._]+$")
_LARGO_MIN, _LARGO_MAX = 5, 40


def _clave(texto):
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def _serial_en_url(texto):
    try:
        partes = urlsplit(texto)
    except ValueError:
        return None
    for clave, valor in parse_qsl(partes.query):
        if _clave(clave) in _CLAVES_SERIAL and valor.strip():
            return valor
    return None


def _serial_en_campos(texto):
    """QR con varios campos ('MODEL:X\\nSN:Y' o 'MODEL=X;SN=Y'): el rotulado como serial."""
    for campo in re.split(r"[\r\n;]+", texto):
        m = re.match(r"\s*([^:=]+?)\s*[:=]\s*(\S.*)$", campo)
        if m and _clave(m.group(1)) in _CLAVES_SERIAL:
            return m.group(2)
    return None


def normalizar_lectura(texto):
    """
    Serial limpio desde el texto crudo de un código: sin caracteres de
    control, sin rótulo 'S/N:', en mayúsculas, y sacado de adentro de una URL
    o de un QR de varios campos cuando viene así.
    """
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(texto or "")).strip()
    if re.match(r"^https?://", texto, re.IGNORECASE):
        texto = _serial_en_url(texto) or texto
    elif re.search(r"[\r\n;]", texto):
        texto = _serial_en_campos(texto) or texto
    texto = _RE_ROTULO.sub("", texto.strip(), count=1)
    return texto.strip().upper()


def motivo_descarte(valor, formato=""):
    """Por qué una lectura ya normalizada NO puede ser un serial, o None."""
    if not valor:
        return "Código vacío."
    if (formato or "").upper() in _FORMATOS_PRODUCTO:
        return "Es un código de producto (EAN/UPC), no un serial."
    if re.match(r"^HTTPS?://", valor):
        return "Es un enlace sin número de serie."
    if _RE_MAC.match(valor):
        return "Parece una dirección MAC."
    if "#" in valor:
        return "Parece un número de parte (P/N)."
    if re.search(r"\s", valor):
        return "Tiene espacios: parece texto, no un serial."
    if len(valor) < _LARGO_MIN:
        return "Muy corto para ser un serial."
    if len(valor) > _LARGO_MAX:
        return "Muy largo para ser un serial."
    if not _RE_SERIAL.match(valor):
        return "Tiene caracteres que un serial no lleva."
    return None


def cargar_reglas(ruta=None):
    """
    Reglas por tipo desde reglas_codigos.json (junto al programa). Formato:

        [{"tipo": "Transformador", "nombre": "HP 45W", "patron": "^WDJTH[0-9A-Z]{9}$"}]

    Una regla rota se salta y se avisa por consola: un patrón mal escrito no
    debe dejar sin lector a nadie. Sin archivo no hay reglas, y el tipo lo da
    lo que se está escaneando.
    """
    ruta = ruta or os.path.join(os.getcwd(), ARCHIVO_REGLAS)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudas = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"⚠️  {ARCHIVO_REGLAS} ilegible: {e}")
        return []

    reglas = []
    for r in crudas if isinstance(crudas, list) else []:
        try:
            if r["tipo"] not in TIPOS_CODIGO:
                raise ValueError(f"tipo desconocido {r['tipo']!r}")
            reglas.append(
                {
                    "tipo": r["tipo"],
                    "nombre": r.get("nombre", ""),
                    "re": re.compile(r["patron"], re.IGNORECASE),
                }
            )
        except Exception as e:
            print(f"⚠️  Regla ignorada {r!r}: {e}")
    return reglas


def tipos_que_coinciden(valor, reglas):
    """Tipos cuyas reglas aceptan el valor, sin repetir y en orden de regla."""
    tipos = []
    for r in reglas:
        if r["re"].search(valor) and r["tipo"] not in tipos:
            tipos.append(r["tipo"])
    return tipos


def _puntaje_forma(valor):
    """Un serial casi siempre mezcla letras y números; uno solo de dígitos suele ser otra cosa."""
    letras = any(c.isalpha() for c in valor)
    digitos = any(c.isdigit() for c in valor)
    if letras and digitos:
        return 10
    return -5 if letras else 0


def elegir_codigo(lecturas, esperado=None, reglas=()):
    """
    De todos los códigos que la cámara vio juntos, el que es el serial buscado.

    lecturas: [{"texto": …, "formato": …}] con 'formato' en nombres de ML Kit.
    esperado: tipo que se está escaneando (de TIPOS_CODIGO) o None.

    Devuelve {"valor", "tipo", "candidatos", "descartes"}:
      - valor/tipo: el elegido, o valor None si no hay o hay empate;
      - candidatos: los empatados, para que el usuario toque el correcto;
      - descartes: [{"texto", "motivo"}] de lo que no podía ser un serial.

    Si lo único válido es de OTRO tipo (se esperaba un transformador y se leyó
    un notebook según las reglas), se devuelve igual con su tipo real: quien
    llama compara contra 'esperado' y avisa.
    """
    mejores = {}
    descartes = []
    for lectura in lecturas:
        crudo = lectura.get("texto", "")
        valor = normalizar_lectura(crudo)
        motivo = motivo_descarte(valor, lectura.get("formato", ""))
        if motivo:
            descartes.append({"texto": crudo, "motivo": motivo})
            continue

        tipos = tipos_que_coinciden(valor, reglas)
        if esperado and esperado in tipos:
            puntaje, tipo = 100, esperado
        elif tipos and (esperado or len(tipos) == 1):
            # Las reglas dicen que es otra cosa (o, sin esperado, qué es).
            puntaje, tipo = (-100 if esperado else 50), tipos[0]
        else:
            puntaje, tipo = 0, esperado
        puntaje += _puntaje_forma(valor)

        if valor not in mejores or puntaje > mejores[valor][0]:
            mejores[valor] = (puntaje, tipo)

    if not mejores:
        return {"valor": None, "tipo": None, "candidatos": [], "descartes": descartes}

    orden = sorted(mejores.items(), key=lambda kv: kv[1][0], reverse=True)
    tope = orden[0][1][0]
    empatados = [valor for valor, (puntaje, _) in orden if puntaje == tope]
    if len(empatados) > 1:
        return {"valor": None, "tipo": None, "candidatos": empatados, "descartes": descartes}
    valor, (_, tipo) = orden[0]
    return {"valor": valor, "tipo": tipo, "candidatos": [], "descartes": descartes}


# ─────────────────────────────────────────────────────────
#  2. Aplicar el escaneo al lote
# ─────────────────────────────────────────────────────────
class LoteInvalido(ValueError):
    """
    Datos de lote que no se pueden usar. Trae título y mensaje para el usuario
    y un código HTTP para la API: 400 dato mal formado, 404 el lote no existe,
    409 existe pero está cerrado.
    """

    def __init__(self, titulo, mensaje, codigo=400):
        super().__init__(mensaje)
        self.titulo = titulo
        self.mensaje = mensaje
        self.codigo = codigo


def lote_desde_formulario(mov, cliente, numero, numero_sec=""):
    """
    Lote normalizado desde lo que se escribió a mano en el celular. Mismas
    reglas y mensajes que el diálogo de nueva OT del PC, para que "OT 553" y
    "553" terminen en la misma carpeta se cree desde donde se cree.
    """
    if mov not in MOV_CFG:
        raise LoteInvalido("Movimiento inválido", f"Movimiento desconocido: {mov}")
    if not str(cliente or "").strip():
        raise LoteInvalido("Falta el cliente", "Elegí o escribí un cliente.")
    num = normalizar_numero(numero or "", mov)
    if not num:
        raise LoteInvalido(
            "Número inválido",
            "Escribí el número de OT / guía.\n\nSolo letras, números, '-' y '_'.",
        )
    return hacer_lote(
        mov,
        normalizar_cliente(cliente),
        num,
        numero_sec=normalizar_numero(numero_sec or "", mov),
    )


def resolver_lote(mov, cliente, numero):
    """
    Lote ABIERTO que nombra el celular. Cliente y número tienen que venir ya
    normalizados (tal como los da listar_lotes_abiertos): llegan por la red y
    terminan en una ruta, así que lo que no está en forma canónica se rechaza
    en vez de "arreglarse" —un '../' nunca llega a os.path.
    """
    if mov not in MOV_CFG:
        raise LoteInvalido("Movimiento inválido", f"Movimiento desconocido: {mov}")
    if not cliente or cliente != normalizar_cliente(cliente):
        raise LoteInvalido("Cliente inválido", f"Cliente no reconocido: {cliente!r}")
    if not numero or numero != normalizar_numero(numero, mov):
        raise LoteInvalido("Número inválido", f"Número no reconocido: {numero!r}")

    lote = hacer_lote(mov, cliente, numero)
    if not os.path.isdir(lote["ruta"]):
        raise LoteInvalido("Lote inexistente", f"No existe {etiqueta_lote(lote)}.", 404)
    if esta_cerrado(lote["ruta"]):
        raise LoteInvalido("Lote cerrado", f"{etiqueta_lote(lote)} ya está cerrado.", 409)
    lote["numero_sec"] = numero_sec_en_disco(lote["ruta"])
    return lote


def _buscar_en_lote(lote, serial):
    """(ruta, jdata) del equipo con ese serial en el lote, sin importar mayúsculas ni símbolos."""
    clave = _clave(serial)
    for ruta, jdata in equipos_en_orden_de_escaneo(lote):
        if _clave(jdata.get("SERIAL", "")) == clave:
            return ruta, jdata
    return None


def _registro_celular(lote, serial, tipo, modelo, obs):
    """
    JSON de un equipo leído solo por su código: mismo esquema que
    guardar_equipo_general, con lo que no se conoce en PENDIENTE (o N/A
    cuando no aplica, como la licencia de Windows de un monitor).
    """
    ahora = datetime.now()
    num_ot, num_guia = numeros_lote(lote)
    modelo = (modelo or "").strip() or tipo
    es_notebook = tipo == TIPO_EQUIPO_DEFAULT
    return {
        "CLIENTE": lote["cliente"],
        "SERIAL": serial,
        "SN_Win": "PENDIENTE" if es_notebook else "N/A",
        # PENDIENTE y no N/A: la reconstrucción del HTML lee SN_HDD como lista
        # de seriales de disco y solo ignora PENDIENTE.
        "SN_HDD": "PENDIENTE",
        "SN_Transf": TRANSF_PENDIENTE,
        "SN_APP": "PENDIENTE",
        "MODELO": modelo,
        "TIPO_MOVIMIENTO": lote["mov"],
        "GUIA_ID": num_guia,
        "OT_ID": num_ot,
        "OBS": (obs or "").strip() or "Sin observaciones",
        "DETALLE_COMPONENTES": [],
        "TIENE_FALLAS": False,
        "DATA": {
            "serial": serial,
            "model": modelo,
            "fecha": ahora.strftime("%d/%m/%Y %H:%M"),
        },
        "OFFICE": "No",
        "TIPO_EQUIPO": tipo,
        "ORIGEN": ORIGEN_CELULAR,
        "ESCANEADO": ahora.isoformat(timespec="seconds"),
    }


def registrar_equipo(lote, serial, tipo=TIPO_EQUIPO_DEFAULT, modelo="", obs="", forzar=False):
    """
    Agrega al lote un equipo leído por su código. Devuelve {"estado", …}:

      registrado   — nuevo en el lote ('total' = equipos del lote)
      ya_estaba    — ya existía (escaneado en el PC o antes): no se toca
      en_otra_ot   — está en otro lote abierto ('otro'); con forzar=True se
                     registra igual, como cuando en el PC se confirma el aviso
      invalido     — el serial no sirve ('motivo')
    """
    if tipo not in TIPOS_EQUIPO:
        raise ValueError(f"Tipo de equipo desconocido: {tipo!r}")
    serial = normalizar_lectura(serial)
    motivo = motivo_descarte(serial)
    if motivo:
        return {"estado": "invalido", "serial": serial, "motivo": motivo}

    existente = _buscar_en_lote(lote, serial)
    if existente:
        jdata = existente[1]
        return {
            "estado": "ya_estaba",
            "serial": jdata.get("SERIAL", serial),
            "tipo": tipo_equipo(jdata),
            "total": contar_equipos(lote["ruta"]),
        }

    if not forzar:
        otro = buscar_serial_en_abiertos(serial, excluir_ruta=lote["ruta"])
        if otro:
            return {"estado": "en_otra_ot", "serial": serial, "otro": etiqueta_lote(otro)}

    total = guardar_registro_en_lote(lote, _registro_celular(lote, serial, tipo, modelo, obs))
    return {"estado": "registrado", "serial": serial, "tipo": tipo, "total": total}


def asignar_transformador(lote, sn_transf, serial_equipo=None):
    """
    Asigna un transformador a un equipo del lote. Devuelve {"estado", …}:

      asignado              — escrito ('equipo'; 'reemplazo' si pisó otro)
      ya_estaba             — ese transformador ya era de ese equipo
      duplicado             — ya pertenece a OTRO equipo del lote ('equipo')
      equipo_no_encontrado  — serial_equipo no está en el lote
      sin_equipo_pendiente  — modo ráfaga y no queda notebook sin transformador
      es_equipo             — el código es el serial de un equipo del lote
                              (se escaneó la etiqueta del notebook): no se toca
      invalido              — serial vacío

    Con serial_equipo va a ese equipo (escaneo guiado: equipo y después su
    transformador). Sin él, al primer notebook sin transformador en orden de
    escaneo: la misma regla de la carga masiva, que asume que se etiquetaron
    en el orden en que se escanearon.
    """
    nuevo = normalizar_sn_transf(normalizar_lectura(sn_transf))
    if not nuevo:
        return {"estado": "invalido", "motivo": "Serial de transformador vacío."}

    equipos = equipos_en_orden_de_escaneo(lote)
    clave = _clave(nuevo)
    if any(_clave(jdata.get("SERIAL", "")) == clave for _, jdata in equipos):
        return {"estado": "es_equipo", "sn_transf": nuevo}
    portador = next(
        (par for par in equipos if transformador_actual(par[1]).upper() == nuevo.upper()),
        None,
    )

    if serial_equipo:
        destino = _buscar_en_lote(lote, serial_equipo)
        if not destino:
            return {"estado": "equipo_no_encontrado", "serial": serial_equipo}
    elif portador:
        # Ráfaga y el mismo transformador otra vez: lectura repetida, no un error.
        destino = portador
    else:
        destino = next(
            (
                par
                for par in equipos
                if tipo_equipo(par[1]) == TIPO_EQUIPO_DEFAULT
                and transformador_actual(par[1]) == TRANSF_PENDIENTE
            ),
            None,
        )
        if not destino:
            return {"estado": "sin_equipo_pendiente", "sn_transf": nuevo}

    ruta, jdata = destino
    serial_destino = jdata.get("SERIAL", "?")
    if portador:
        if portador[0] == ruta:
            return {"estado": "ya_estaba", "sn_transf": nuevo, "equipo": serial_destino}
        return {
            "estado": "duplicado",
            "sn_transf": nuevo,
            "equipo": portador[1].get("SERIAL", "?"),
        }

    anterior = transformador_actual(jdata)
    errores = guardar_transformadores(lote, [(ruta, jdata, nuevo)])
    if errores:
        raise OSError(errores[0])
    return {
        "estado": "asignado",
        "sn_transf": nuevo,
        "equipo": serial_destino,
        "reemplazo": None if anterior == TRANSF_PENDIENTE else anterior,
    }


def estado_lote(lote):
    """Resumen del lote para la lista del celular, en orden de escaneo."""
    equipos = [
        {
            "serial": jdata.get("SERIAL", "?"),
            "tipo": tipo_equipo(jdata),
            "modelo": jdata.get("MODELO", ""),
            "sn_transf": None
            if transformador_actual(jdata) == TRANSF_PENDIENTE
            else transformador_actual(jdata),
            "sin_hardware": jdata.get("ORIGEN") == ORIGEN_CELULAR,
        }
        for _, jdata in equipos_en_orden_de_escaneo(lote)
    ]
    return {
        "mov": lote["mov"],
        "cliente": lote["cliente"],
        "numero": lote["numero"],
        "numero_sec": lote.get("numero_sec", ""),
        "etiqueta": etiqueta_lote(lote),
        "equipos": equipos,
    }
