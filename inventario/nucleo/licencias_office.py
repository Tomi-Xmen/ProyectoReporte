"""
Base de licencias de Office: cada caja comprada (su código, la key que trae
adentro) y a qué equipo está asignada.

Vive en 'licencias_office.db' (SQLite) junto al programa, igual que
Reportes_Guardados. Es la fuente de verdad: la planilla "OFFICE ARRIENDA" se
importa una vez con su estado y su historial, y de ahí en adelante se asigna
y libera desde la app (exportar_csv() la devuelve en formato planilla). No va
al repositorio: tiene las keys.

Asignar es atómico: la caja se marca como asignada en la misma transacción
en que se comprueba que estaba libre, así dos equipos nunca se quedan con la
misma caja aunque la pidan a la vez.

Una caja se encuentra por cualquiera de sus dos códigos: el CODIGO CAJA o el
COD. BARRA (las 2013/2016 traen ambos y la pistola puede leer cualquiera).
En las 2021/2024 esa segunda columna es la cuenta outlook a la que está
ligada la licencia, y se guarda como 'cuenta'.
"""

import csv
import io
import os
import re
import sqlite3
import unicodedata
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from .fichas import VERSIONES_OFFICE

ARCHIVO_BASE = "licencias_office.db"

DISPONIBLE = "disponible"
ASIGNADA = "asignada"
DESHABILITADA = "deshabilitada"

# Cómo terminó la carga de la key en el equipo (activacion_office).
ACTIVADA = "activada"
SOLO_CARGADA = "cargada"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS licencias (
    caja         TEXT PRIMARY KEY,
    clave        TEXT NOT NULL UNIQUE,
    codigo_barra TEXT NOT NULL DEFAULT '',
    cuenta       TEXT NOT NULL DEFAULT '',
    version      TEXT NOT NULL DEFAULT '',
    producto     TEXT NOT NULL DEFAULT '',
    ubicacion    TEXT NOT NULL DEFAULT '',
    estado       TEXT NOT NULL DEFAULT 'disponible',
    serial       TEXT NOT NULL DEFAULT '',
    modelo       TEXT NOT NULL DEFAULT '',
    cliente      TEXT NOT NULL DEFAULT '',
    documento    TEXT NOT NULL DEFAULT '',
    asignada     TEXT NOT NULL DEFAULT '',
    activacion   TEXT NOT NULL DEFAULT '',
    nota         TEXT NOT NULL DEFAULT '',
    importada    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS licencias_serial ON licencias(serial);
CREATE INDEX IF NOT EXISTS licencias_barra ON licencias(codigo_barra);
CREATE TABLE IF NOT EXISTS historial (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha   TEXT NOT NULL,
    caja    TEXT NOT NULL,
    evento  TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT ''
);
"""


class ErrorLicencia(Exception):
    """
    'codigo' dice qué pasó, para que la UI decida qué preguntar: no_existe,
    asignada (a otro equipo), deshabilitada, otra_caja (el equipo ya tiene
    otra) o dato (algo ilegible).
    """

    def __init__(self, codigo, mensaje, licencia=None):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.licencia = codigo, mensaje, licencia


def ruta_base():
    # El directorio de trabajo es la carpeta del programa (config hace chdir),
    # el mismo criterio que lotes.ruta_reportes().
    return os.path.join(os.getcwd(), ARCHIVO_BASE)


def existe_base():
    return os.path.exists(ruta_base())


@contextmanager
def _conexion(escribir=False):
    """
    Conexión con el esquema creado. Para escribir toma el candado de la base
    desde el principio (BEGIN IMMEDIATE): leer-y-después-marcar queda atómico.
    """
    con = sqlite3.connect(ruta_base(), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_ESQUEMA)
        if escribir:
            con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except BaseException:
            if escribir:
                con.execute("ROLLBACK")
            raise
        if escribir:
            con.execute("COMMIT")
    finally:
        con.close()


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def _historial(con, caja, evento, detalle=""):
    con.execute(
        "INSERT INTO historial (fecha, caja, evento, detalle) VALUES (?, ?, ?, ?)",
        (_ahora(), caja, evento, detalle),
    )


# ─────────────────────────────────────────────────────────
#  Normalización
# ─────────────────────────────────────────────────────────
def normalizar_clave(texto):
    """'xxxxx xxxxx-…' → 'XXXXX-XXXXX-XXXXX-XXXXX-XXXXX', o '' si no es una key."""
    limpio = re.sub(r"[\s\-]", "", str(texto or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{25}", limpio):
        return ""
    return "-".join(limpio[i : i + 5] for i in range(0, 25, 5))


def _numero_excel(texto):
    """Excel guarda los códigos numéricos largos como número: '123.0' o '1.23E+12' → '123'."""
    if re.fullmatch(r"\d+(\.\d+)?([eE]\+\d+)?", texto):
        try:
            valor = Decimal(texto)
        except InvalidOperation:
            return texto
        if valor == valor.to_integral_value():
            return str(int(valor))
    return texto


def normalizar_codigo(texto):
    """Código de caja o de barra tal como se lee: mayúsculas, sin espacios de más."""
    codigo = re.sub(r"\s+", " ", str(texto or "")).strip().strip("'\"").strip().upper()
    return _numero_excel(codigo)[:64]


def _sin_guiones(codigo):
    return re.sub(r"[\s\-]", "", codigo)


def normalizar_version(texto):
    """'Office 2016 Hogar y Empresas' → '2016'; 'Microsoft 365' → '365'; '' si no."""
    for v in VERSIONES_OFFICE:
        if re.search(rf"(?<!\d){v}(?!\d)", str(texto or "")):
            return v
    return ""


def enmascarar(clave):
    """Solo el último grupo a la vista: '•••••-•••••-•••••-•••••-ABCDE'."""
    return "•••••-" * 4 + clave[-5:] if clave else ""


# ─────────────────────────────────────────────────────────
#  Lectura de la planilla
# ─────────────────────────────────────────────────────────
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _columna(ref):
    """'C12' → 2."""
    n = 0
    for letra in re.match(r"[A-Z]*", ref).group(0):
        n = n * 26 + ord(letra) - 64
    return max(n - 1, 0)


def _filas_xlsx(ruta):
    """
    Filas de la primera hoja de un .xlsx, como listas de texto. Se lee el XML
    directo para no sumar una dependencia al .exe solo por esto.
    """
    with zipfile.ZipFile(ruta) as z:
        nombres = z.namelist()
        compartidos = []
        if "xl/sharedStrings.xml" in nombres:
            raiz = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            compartidos = [
                "".join(t.text or "" for t in si.iter(f"{_NS}t"))
                for si in raiz.findall(f"{_NS}si")
            ]
        hojas = sorted(
            (n for n in nombres if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group(0)),
        )
        if not hojas:
            return []
        raiz = ElementTree.fromstring(z.read(hojas[0]))

    filas = []
    for fila in raiz.iter(f"{_NS}row"):
        celdas = {}
        for c in fila.findall(f"{_NS}c"):
            tipo = c.get("t", "")
            if tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
            else:
                v = c.find(f"{_NS}v")
                valor = v.text if v is not None and v.text else ""
                if tipo == "s" and valor:
                    valor = compartidos[int(valor)]
            celdas[_columna(c.get("r", "A"))] = valor
        filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)] if celdas else [])
    return filas


def filas_de_texto(texto):
    """Filas de un CSV o de lo copiado desde Excel (tabs), detectando el separador."""
    lineas = [l for l in str(texto or "").splitlines() if l.strip()]
    if not lineas:
        return []
    muestra = "\n".join(lineas[:20])
    try:
        separador = csv.Sniffer().sniff(muestra, delimiters="\t;,|").delimiter
    except csv.Error:
        separador = "\t" if "\t" in muestra else ";"
    return list(csv.reader(io.StringIO("\n".join(lineas)), delimiter=separador))


def leer_planilla(ruta):
    """Filas de un .xlsx o .csv. Lanza ErrorLicencia si no se puede leer."""
    if ruta.lower().endswith(".xls"):
        raise ErrorLicencia(
            "dato",
            "El formato .xls (Excel 97-2003) no se puede leer.\n\n"
            "Abrilo en Excel, 'Guardar como' → 'Libro de Excel (.xlsx)' "
            "y volvé a importarlo.",
        )
    try:
        if ruta.lower().endswith(".xlsx"):
            return _filas_xlsx(ruta)
        with open(ruta, "rb") as f:
            crudo = f.read()
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as e:
        raise ErrorLicencia("dato", f"No se pudo leer el archivo:\n{e}") from e
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return filas_de_texto(crudo.decode(codificacion))
        except UnicodeDecodeError:
            continue
    return filas_de_texto(crudo.decode("latin-1"))


def _encabezado(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", texto.upper()).strip()


# Encabezado de la planilla → campo. El primero que aparezca gana.
_COLUMNAS = {
    "LICENCIA": "clave",
    "KEY": "clave",
    "CLAVE": "clave",
    "CODIGO CAJA": "caja",
    "LICENCIA COD BARRA": "barra",
    "COD BARRA": "barra",
    "CODIGO BARRA": "barra",
    "PRODUCTO": "producto",
    "VERSION": "producto",
    "ESTADO": "estado",
    "SERIAL": "serial",
    "MODELO": "modelo",
    "CLIENTE": "cliente",
    "GUIA": "guia",
    "FECHA EVENTO": "fecha_evento",
    "REASIGNACION": "reasignacion",
    "CAJA": "ubicacion",
}

_ESTADOS = {
    "DISPONIBLE": DISPONIBLE,
    "ASIGNADA": ASIGNADA,
    "REASIGNADA": ASIGNADA,
    "DESHABILITADA": DESHABILITADA,
}


def _fecha(texto):
    """Fecha de la planilla: un número de serie de Excel pasa a ISO; el texto queda igual."""
    texto = str(texto or "").strip()
    if re.fullmatch(r"\d{5}(\.\d+)?", texto):
        return (date(1899, 12, 30) + timedelta(days=int(float(texto)))).isoformat()
    return texto


def interpretar_filas(filas, version_por_defecto=""):
    """
    ([licencia], [(n° de fila, motivo)]) desde las filas crudas.

    Con la planilla maestra (encabezados LICENCIA, CODIGO CAJA, ESTADO…) se
    traen también el estado, el equipo y la nota. Sin encabezados conocidos,
    por ejemplo una lista nueva pegada a mano, la key es la celda con forma de
    key, la versión la que nombra un año de Office y la caja la primera que
    sobra; esas entran como disponibles.
    """
    filas = [[str(c or "").strip() for c in f] for f in filas]
    cols = {}
    if filas:
        for i, celda in enumerate(filas[0]):
            campo = _COLUMNAS.get(_encabezado(celda))
            if campo and campo not in cols:
                cols[campo] = i
    con_encabezado = "clave" in cols and "caja" in cols
    if con_encabezado:
        # La maestra tiene una nota libre en la columna sin nombre que sigue
        # al último encabezado (en un .xlsx esa celda vacía ni existe).
        cols["nota"] = max(i for i, c in enumerate(filas[0]) if c) + 1

    licencias, invalidas = [], []
    cajas, claves = set(), set()
    for n, celdas in enumerate(filas, start=1):
        if not any(celdas) or (n == 1 and (con_encabezado or not any(map(normalizar_clave, celdas)))):
            continue
        if con_encabezado:
            lic = _licencia_con_encabezado(celdas, cols, version_por_defecto)
        else:
            lic = _licencia_sin_encabezado(celdas, version_por_defecto)
        if isinstance(lic, str):
            invalidas.append((n, lic))
            continue
        if _sin_guiones(lic["caja"]) in cajas:
            invalidas.append((n, f"la caja {lic['caja']} está repetida en la planilla"))
            continue
        if lic["clave"] in claves:
            invalidas.append((n, f"la key …{lic['clave'][-5:]} está repetida en la planilla"))
            continue
        cajas.add(_sin_guiones(lic["caja"]))
        claves.add(lic["clave"])
        licencias.append(lic)
    return licencias, invalidas


def _licencia_vacia(caja, clave, version):
    return {
        "caja": caja, "clave": clave, "codigo_barra": "", "cuenta": "",
        "version": version, "producto": "", "ubicacion": "", "estado": DISPONIBLE,
        "serial": "", "modelo": "", "cliente": "", "documento": "", "asignada": "",
        "nota": "", "anterior": "",
    }


def _licencia_con_encabezado(celdas, cols, version_por_defecto):
    def celda(campo):
        i = cols.get(campo)
        return celdas[i] if i is not None and i < len(celdas) else ""

    clave = normalizar_clave(celda("clave"))
    if not clave:
        return "no tiene una key válida (5 grupos de 5)"
    caja = normalizar_codigo(celda("caja"))
    if not caja:
        return "no tiene código de caja"
    estado_texto = _encabezado(celda("estado"))
    estado = _ESTADOS.get(estado_texto)
    if estado is None:
        return f"estado desconocido: {celda('estado')!r}"

    producto = celda("producto")
    lic = _licencia_vacia(caja, clave, normalizar_version(producto) or version_por_defecto)
    barra = celda("barra")
    if "@" in barra:
        lic["cuenta"] = barra.lower()
    else:
        lic["codigo_barra"] = normalizar_codigo(barra)
    lic["producto"] = producto
    lic["ubicacion"] = _numero_excel(celda("ubicacion"))
    lic["estado"] = estado
    lic["nota"] = " · ".join(
        t for t in (celda("nota"), celda("reasignacion") if estado != ASIGNADA else "") if t
    )

    serial, guia = celda("serial"), _numero_excel(celda("guia"))
    # Una asignada puede no tener serial (está a nombre de una persona): sigue
    # asignada, con el cliente como única referencia.
    if estado == ASIGNADA:
        lic.update(
            serial=serial,
            modelo=celda("modelo"),
            cliente=celda("cliente"),
            documento=f"Guía {guia}" if guia else "",
            asignada=_fecha(celda("fecha_evento")),
        )
        if celda("reasignacion"):
            lic["nota"] = " · ".join(t for t in (lic["nota"], f"Reasignada: {celda('reasignacion')}") if t)
    elif serial or guia:
        # Libre, pero la planilla recuerda dónde estuvo: va al historial.
        lic["anterior"] = " · ".join(
            t
            for t in (
                f"SN {serial}" if serial else "",
                celda("modelo"),
                celda("cliente"),
                f"guía {guia}" if guia else "",
                _fecha(celda("fecha_evento")),
            )
            if t
        )
    return lic


def _licencia_sin_encabezado(celdas, version_por_defecto):
    clave = next((normalizar_clave(c) for c in celdas if normalizar_clave(c)), "")
    if not clave:
        return "no tiene una key válida (5 grupos de 5)"
    resto = [c for c in celdas if c and normalizar_clave(c) != clave]
    version = next((normalizar_version(c) for c in resto if normalizar_version(c)), "")
    resto = [c for c in resto if not normalizar_version(c)]
    if not resto:
        return "no tiene código de caja"
    lic = _licencia_vacia(normalizar_codigo(resto[0]), clave, version or version_por_defecto)
    if len(resto) > 1:
        if "@" in resto[1]:
            lic["cuenta"] = resto[1].lower()
        else:
            lic["codigo_barra"] = normalizar_codigo(resto[1])
    return lic


# ─────────────────────────────────────────────────────────
#  Base
# ─────────────────────────────────────────────────────────
_CAMPOS_INSERT = (
    "caja", "clave", "codigo_barra", "cuenta", "version", "producto", "ubicacion",
    "estado", "serial", "modelo", "cliente", "documento", "asignada", "nota",
)


def importar(licencias):
    """
    Agrega las licencias nuevas con su estado. Nunca pisa una existente: si
    la caja o la key ya están, se informa en vez de cambiar lo que hay (así
    importar dos veces la misma planilla no deshace lo asignado en la app).
    Devuelve {"nuevas": n, "repetidas": n, "conflictos": [(caja, motivo)]}.
    """
    resultado = {"nuevas": 0, "repetidas": 0, "conflictos": []}
    with _conexion(escribir=True) as con:
        for lic in licencias:
            por_caja = con.execute(
                "SELECT clave FROM licencias WHERE REPLACE(caja, '-', '') = ?",
                (_sin_guiones(lic["caja"]),),
            ).fetchone()
            por_clave = con.execute(
                "SELECT caja FROM licencias WHERE clave = ?", (lic["clave"],)
            ).fetchone()
            if por_caja and por_caja["clave"] == lic["clave"]:
                resultado["repetidas"] += 1
            elif por_caja:
                resultado["conflictos"].append((lic["caja"], "la caja ya está en la base con otra key"))
            elif por_clave:
                resultado["conflictos"].append(
                    (lic["caja"], f"esa key ya está en la base en la caja {por_clave['caja']}")
                )
            else:
                valores = [lic.get(c, "") for c in _CAMPOS_INSERT]
                con.execute(
                    f"INSERT INTO licencias ({', '.join(_CAMPOS_INSERT)}, importada) "
                    f"VALUES ({', '.join('?' * len(_CAMPOS_INSERT))}, ?)",
                    (*valores, _ahora()),
                )
                if lic.get("anterior"):
                    _historial(con, lic["caja"], "antes de importar", lic["anterior"])
                _historial(con, lic["caja"], "importada", lic["estado"])
                resultado["nuevas"] += 1
    return resultado


def _dict(fila):
    return dict(fila) if fila else None


def _buscar(con, codigo):
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return None
    return _dict(
        con.execute(
            "SELECT * FROM licencias WHERE REPLACE(caja, '-', '') = ? OR codigo_barra = ?",
            (_sin_guiones(codigo), codigo),
        ).fetchone()
    )


def buscar(codigo):
    """La licencia con ese código de caja o de barra, o None. No crea la base."""
    if not existe_base():
        return None
    with _conexion() as con:
        return _buscar(con, codigo)


def caja_de_equipo(serial):
    """La licencia asignada a ese serial, o None."""
    serial = str(serial or "").strip()
    if not serial or not existe_base():
        return None
    with _conexion() as con:
        return _dict(
            con.execute(
                "SELECT * FROM licencias WHERE estado = ? AND serial = ? ORDER BY asignada DESC",
                (ASIGNADA, serial),
            ).fetchone()
        )


def describir_asignacion(lic):
    """'SN 5CD123 · ACME · OT-553 · 2026-11-03' para los avisos."""
    return " · ".join(
        p
        for p in (
            f"SN {lic['serial']}" if lic["serial"] else "sin equipo",
            lic["cliente"].replace("_", " "),
            lic["documento"],
            lic["asignada"][:10],
        )
        if p
    )


def asignar(codigo, serial, modelo="", cliente="", documento="", reemplazar=False):
    """
    Asigna la caja al equipo y devuelve la licencia. Reasignarla al mismo
    equipo no cambia nada. Lanza ErrorLicencia si la caja no existe, está
    deshabilitada, es de otro equipo o si el equipo ya tiene otra caja (salvo
    reemplazar=True, que libera esa otra en la misma transacción).
    """
    serial = str(serial or "").strip()
    if not normalizar_codigo(codigo) or not serial:
        raise ErrorLicencia("dato", "Falta el código de caja o el serial del equipo.")
    with _conexion(escribir=True) as con:
        lic = _buscar(con, codigo)
        if not lic:
            raise ErrorLicencia(
                "no_existe", f"El código {normalizar_codigo(codigo)} no está en la base de licencias."
            )
        if lic["estado"] == DESHABILITADA:
            raise ErrorLicencia(
                "deshabilitada", f"La caja {lic['caja']} está deshabilitada.\n{lic['nota']}".strip(), lic
            )
        if lic["estado"] == ASIGNADA:
            if lic["serial"] == serial:
                return lic
            raise ErrorLicencia(
                "asignada",
                f"La caja {lic['caja']} ya está asignada a otro equipo:\n{describir_asignacion(lic)}",
                lic,
            )
        previa = _dict(
            con.execute(
                "SELECT * FROM licencias WHERE estado = ? AND serial = ?", (ASIGNADA, serial)
            ).fetchone()
        )
        if previa and not reemplazar:
            raise ErrorLicencia(
                "otra_caja", f"El equipo {serial} ya tiene asignada la caja {previa['caja']}.", previa
            )
        if previa:
            _liberar(con, previa["caja"], f"reemplazada por {lic['caja']}")
        return _marcar_asignada(con, lic, serial, modelo, cliente, documento)


def _marcar_asignada(con, lic, serial, modelo, cliente, documento):
    cambios = {
        "estado": ASIGNADA, "serial": serial, "modelo": modelo, "cliente": cliente,
        "documento": documento, "asignada": _ahora(), "activacion": "",
    }
    con.execute(
        f"UPDATE licencias SET {', '.join(f'{c} = ?' for c in cambios)} WHERE caja = ?",
        (*cambios.values(), lic["caja"]),
    )
    _historial(con, lic["caja"], "asignada", describir_asignacion({**lic, **cambios}))
    lic.update(cambios)
    return lic


def reasignar(pares, cliente="", documento="", modelos=None):
    """
    Deja cada equipo con la caja que se eligió para él, todo junto o nada.

    'pares' es {serial: código de caja o de barra}; '' deja al equipo sin
    caja. Mover cajas entre los mismos equipos vale (intercambiar dos): primero
    se sueltan las que cambian de dueño y después se asignan las nuevas, en la
    misma transacción. Devuelve {serial: licencia o None}. Si algo no se puede
    (código que no existe, caja de un equipo de afuera, repetida…) no cambia
    nada y lanza ErrorLicencia('varios') con todos los problemas juntos.
    """
    modelos = modelos or {}
    with _conexion(escribir=True) as con:
        problemas, elegidas, vistas = [], {}, {}
        for serial, codigo in pares.items():
            if not normalizar_codigo(codigo):
                elegidas[serial] = None
                continue
            lic = _buscar(con, codigo)
            if not lic:
                problemas.append(f"{serial}: el código {normalizar_codigo(codigo)} no está en la base")
            elif lic["estado"] == DESHABILITADA:
                problemas.append(f"{serial}: la caja {lic['caja']} está deshabilitada")
            elif lic["estado"] == ASIGNADA and lic["serial"] != serial and lic["serial"] not in pares:
                problemas.append(
                    f"{serial}: la caja {lic['caja']} es de otro equipo ({describir_asignacion(lic)})"
                )
            elif lic["caja"] in vistas:
                problemas.append(f"{serial}: la caja {lic['caja']} también está en {vistas[lic['caja']]}")
            else:
                vistas[lic["caja"]] = serial
                elegidas[serial] = lic
        if problemas:
            raise ErrorLicencia("varios", "\n".join(problemas))

        for serial, nueva in elegidas.items():
            actual = con.execute(
                "SELECT caja FROM licencias WHERE estado = ? AND serial = ?", (ASIGNADA, serial)
            ).fetchone()
            if actual and (nueva is None or nueva["caja"] != actual["caja"]):
                _liberar(con, actual["caja"], f"cambiada de equipo en {documento}".strip())

        resultado = {}
        for serial, lic in elegidas.items():
            if lic is None:
                resultado[serial] = None
                continue
            fresca = _dict(con.execute("SELECT * FROM licencias WHERE caja = ?", (lic["caja"],)).fetchone())
            if fresca["estado"] == ASIGNADA and fresca["serial"] == serial:
                resultado[serial] = fresca
            else:
                resultado[serial] = _marcar_asignada(
                    con, fresca, serial, modelos.get(serial, ""), cliente, documento
                )
        return resultado


def listar_disponibles(version):
    """
    Cajas libres de esa versión, por ubicación física y código: el orden en
    que conviene sacarlas para no abrir una caja de almacenamiento nueva.
    """
    if not existe_base():
        return []
    with _conexion() as con:
        filas = con.execute(
            "SELECT * FROM licencias WHERE estado = ? AND version = ? "
            "ORDER BY ubicacion = '', CAST(ubicacion AS INTEGER), ubicacion, caja",
            (DISPONIBLE, version),
        ).fetchall()
    return [dict(f) for f in filas]


def disponibles(version):
    """Cuántas cajas de esa versión quedan libres."""
    if not existe_base():
        return 0
    with _conexion() as con:
        return con.execute(
            "SELECT COUNT(*) FROM licencias WHERE estado = ? AND version = ?",
            (DISPONIBLE, version),
        ).fetchone()[0]


def _liberar(con, caja, motivo):
    con.execute(
        "UPDATE licencias SET estado = ?, serial = '', modelo = '', cliente = '', "
        "documento = '', asignada = '', activacion = '' WHERE caja = ?",
        (DISPONIBLE, caja),
    )
    _historial(con, caja, "liberada", motivo)


def liberar(caja, motivo=""):
    """
    Devuelve la caja a disponible (equipo retirado, asignación errónea). El
    equipo anterior queda en el historial.
    """
    with _conexion(escribir=True) as con:
        lic = _buscar(con, caja)
        if not lic:
            raise ErrorLicencia("no_existe", f"La caja {caja} no está en la base de licencias.")
        if lic["estado"] == ASIGNADA:
            motivo = " · ".join(p for p in (motivo, f"estaba en {describir_asignacion(lic)}") if p)
        _liberar(con, lic["caja"], motivo)


def registrar_activacion(caja, estado, detalle=""):
    """Anota cómo terminó la carga de la key en el equipo (ACTIVADA, SOLO_CARGADA o el error)."""
    with _conexion(escribir=True) as con:
        con.execute("UPDATE licencias SET activacion = ? WHERE caja = ?", (estado, caja))
        _historial(con, caja, "activacion", f"{estado} {detalle}".strip())


def listar(filtro=""):
    """Licencias que contienen el filtro en caja, código, serial, cliente o versión."""
    if not existe_base():
        return []
    patron = f"%{str(filtro or '').strip().upper()}%"
    with _conexion() as con:
        filas = con.execute(
            "SELECT * FROM licencias WHERE UPPER(caja || ' ' || codigo_barra || ' ' || serial "
            "|| ' ' || cliente || ' ' || documento || ' ' || version || ' ' || ubicacion) LIKE ? "
            "ORDER BY CASE estado WHEN 'disponible' THEN 0 WHEN 'asignada' THEN 1 ELSE 2 END, "
            "version, caja",
            (patron,),
        ).fetchall()
    return [dict(f) for f in filas]


def historial(caja):
    """Eventos de la caja, del más reciente al más antiguo."""
    with _conexion() as con:
        filas = con.execute(
            "SELECT fecha, evento, detalle FROM historial WHERE caja = ? ORDER BY id DESC", (caja,)
        ).fetchall()
    return [dict(f) for f in filas]


def cajas_del_serial(serial):
    """
    Cajas que alguna vez estuvieron en ese equipo, según el historial (una
    caja liberada ya no guarda el serial en su fila): [(caja, fecha)], de la
    más reciente a la más vieja, una vez cada caja.
    """
    serial = str(serial or "").strip()
    if not serial or not existe_base():
        return []
    patron = re.compile(rf"(?:^|\s)SN {re.escape(serial)}(?:$|\s|·)")
    with _conexion() as con:
        filas = con.execute(
            "SELECT caja, fecha, detalle FROM historial "
            "WHERE evento IN ('asignada', 'antes de importar') AND detalle LIKE ? "
            "ORDER BY id DESC",
            (f"%SN {serial}%",),
        ).fetchall()
    vistas, cajas = set(), []
    for f in filas:
        if f["caja"] not in vistas and patron.search(f["detalle"]):
            vistas.add(f["caja"])
            cajas.append((f["caja"], f["fecha"]))
    return cajas


def resumen():
    """{version: {disponible: n, asignada: n, deshabilitada: n}}."""
    if not existe_base():
        return {}
    with _conexion() as con:
        filas = con.execute(
            "SELECT version, estado, COUNT(*) AS n FROM licencias GROUP BY version, estado"
        ).fetchall()
    total = {}
    for f in filas:
        por_estado = total.setdefault(f["version"], {DISPONIBLE: 0, ASIGNADA: 0, DESHABILITADA: 0})
        por_estado[f["estado"]] = f["n"]
    return total


_EXPORTAR = (
    ("CODIGO CAJA", "caja"),
    ("COD. BARRA", "codigo_barra"),
    ("CUENTA", "cuenta"),
    ("LICENCIA", "clave"),
    ("PRODUCTO", "producto"),
    ("ESTADO", "estado"),
    ("SERIAL", "serial"),
    ("MODELO", "modelo"),
    ("CLIENTE", "cliente"),
    ("DOCUMENTO", "documento"),
    ("FECHA ASIGNACION", "asignada"),
    ("ACTIVACION", "activacion"),
    ("CAJA", "ubicacion"),
    ("NOTA", "nota"),
)


def exportar_csv(ruta):
    """
    Toda la base como planilla (separador ';' y BOM, para que Excel en
    español la abra directo). Lleva las keys completas. Devuelve cuántas filas.
    """
    filas = listar()
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([titulo for titulo, _ in _EXPORTAR])
        for lic in filas:
            w.writerow(
                [lic[c].upper() if c == "estado" else lic[c] for _, c in _EXPORTAR]
            )
    return len(filas)
